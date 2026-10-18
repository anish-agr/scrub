"""Offline tests for controller/run_all.py: options, ports, env wiring, URL table, child handling, reset.

  .venv/bin/python -m controller.test_run_all

Uses ports 8260 to 8263 only (a fake HTTP server and one fake-arm controller). No voice, no tunnel, no browser.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import httpx

# The fake-arm controller this starts never reaches MongoDB or Backboard; its events say test: true.
os.environ.update(MONGODB_URI="", BACKBOARD_API_KEY="", SCRUB_TEST="1",
                  LEDGER_BUFFER=os.path.join(tempfile.mkdtemp(prefix="scrub-test-run-all-"), "buffer.jsonl"))

from controller import run_all as R  # noqa: E402

FAKE_PORT, BUSY_PORT, CTL_PORT = 8260, 8261, 8262


class FakeController(BaseHTTPRequestHandler):
    """Records every request. sim=True answers /sim/scene_reset; busy_resets 409s that many /reset calls."""
    calls: list = []
    sim = False
    busy_resets = 0
    state = {"step": "idle", "out": ["hemostat"], "setting": "bench", "lighting": "dim", "fake_arm": True}

    def log_message(self, *_):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.calls.append(("GET", self.path, None))
        if self.path == "/state":
            return self._send(200, self.state)
        if self.path == "/sim/vision" and self.sim:
            return self._send(200, {"on": False})
        self._send(404, {"detail": "Not Found"})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"null")
        cls = type(self)
        cls.calls.append(("POST", self.path, body))
        if self.path in ("/scene/setting", "/scene/reset") and cls.sim:  # the sim server (8002)
            return self._send(200, {"ok": True})
        if self.path == "/sim/scene_reset":
            return self._send(200, {"ok": True}) if cls.sim else self._send(404, {"detail": "Not Found"})
        if self.path == "/reset":
            if cls.busy_resets > 0:
                cls.busy_resets -= 1
                return self._send(409, {"detail": "busy"})
            cls.state = dict(cls.state, out=[])
            return self._send(200, {"ok": True})
        if self.path == "/setting":
            cls.state = dict(cls.state, setting=body["setting"], out=[])
            return self._send(200, {"id": body["setting"], "label": "Operating room", "items": []})
        if self.path == "/lighting":
            cls.state = dict(cls.state, lighting=body["lighting"])
            return self._send(200, {"ok": True})
        self._send(404, {"detail": "Not Found"})


def serve(port, handler=FakeController):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Quiet:
    def __init__(self):
        self.lines = []

    def __call__(self, text):
        self.lines.append(text)


class TestOptions(unittest.TestCase):
    def test_defaults_are_the_contract_ports(self):
        a = R.parse([])
        self.assertEqual((a.cmd, a.arm, a.vision, a.open, a.tunnel, a.judge), ("start", "fake", "fake", True, None, False))
        self.assertEqual(R.ports(a), {"controller": 8000, "vision": 8001, "sim": 8002, "voice": 3000, "ledger": 8080})
        self.assertEqual(R.controller_url(a), "http://localhost:8000")

    def test_base_port_moves_everything_and_single_ports_override(self):
        a = R.parse(["--base-port", "8240"])
        self.assertEqual(R.ports(a), {"controller": 8240, "vision": 8241, "sim": 8242, "voice": 3240, "ledger": 8243})
        a = R.parse(["--base-port", "8240", "--port", "8245", "--voice-port", "3249"])
        self.assertEqual((R.ports(a)["controller"], R.ports(a)["vision"], R.ports(a)["voice"]), (8245, 8241, 3249))

    def test_sim_defaults_to_no_vision_process(self):
        self.assertEqual(R.parse(["--arm", "sim"]).vision, "none")
        self.assertEqual(R.parse(["--arm", "sim", "--vision", "fake"]).vision, "fake")
        self.assertEqual(R.parse(["--arm", "real"]).vision, "fake")

    def test_flags(self):
        self.assertEqual(R.parse(["--tunnel"]).tunnel, "pinggy")
        self.assertEqual(R.parse(["--tunnel", "cf"]).tunnel, "cf")
        self.assertFalse(R.parse(["--no-open"]).open)
        self.assertTrue(R.parse(["--judge"]).judge)
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            R.parse(["--tunnel", "bogus"])

    def test_subcommands(self):
        a = R.parse(["check"])
        self.assertEqual((a.cmd, a.base_port, a.no_voice, a.open, a.motion_s, a.pull_s), ("check", 8100, True, False, 0.2, 0.5))
        a = R.parse(["check", "--url", "http://localhost:8000"])
        self.assertEqual((a.base_port, a.open), (8000, True))
        a = R.parse(["backup", "--loop"])
        self.assertEqual((a.cmd, a.arm, a.vision, a.loop), ("backup", "sim", "none", True))
        self.assertEqual(R.parse(["reset", "--url", "http://x:9"]).cmd, "reset")
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            R.parse(["backup", "--arm", "real"])


class TestPlan(unittest.TestCase):
    def plan(self, argv, judge_ok=True):
        with mock.patch.object(R, "voice_skip_reason", return_value=None):
            return R.plan(R.parse(argv), judge_ok=judge_ok)

    def test_env_wiring_to_every_child(self):
        kids, _ = self.plan(["--base-port", "8240", "--ledger", "--tunnel"])
        self.assertEqual([k.name for k in kids], ["controller", "vision", "voice", "ledger", "tunnel"])
        for k in kids:
            self.assertEqual(k.env["CONTROLLER_URL"], "http://localhost:8240")
            self.assertEqual(k.env["VISION_URL"], "http://localhost:8241")
            self.assertEqual(k.env["VOICE_PORT"], "3240")
        by = {k.name: k for k in kids}
        self.assertEqual(by["ledger"].env["PORT"], "8243")
        self.assertEqual(by["voice"].cmd, ["npm", "run", "dev"])
        self.assertEqual(by["voice"].cwd, R.ROOT / "voice")
        self.assertEqual(by["tunnel"].cmd, ["npm", "run", "tunnel"])
        self.assertEqual(by["vision"].cmd[-3:], ["--port", "8241", "--fake"])
        self.assertEqual(by["controller"].health, "http://localhost:8240/state")
        self.assertEqual(by["vision"].health, "http://localhost:8241/health")
        self.assertEqual(by["voice"].health, "http://localhost:3240/health")
        self.assertTrue(by["controller"].critical)

    def test_controller_command_per_arm(self):
        c = self.plan(["--arm", "sim", "--base-port", "8240"])[0][0].cmd
        self.assertEqual(c[c.index("--port") + 1], "8240")
        self.assertIn("--sim-arm", c)
        self.assertEqual(c[c.index("--sim-port") + 1], "8242")
        self.assertIn("--real-arm", self.plan(["--arm", "real"])[0][0].cmd)
        c = self.plan(["--motion-s", "0.2", "--pull-s", "0.5", "--setting", "bench"])[0][0].cmd
        self.assertEqual(c[c.index("--motion-s") + 1:c.index("--motion-s") + 4], ["0.2", "--pull-s", "0.5"])
        self.assertEqual(c[c.index("--setting") + 1], "bench")
        kids, _ = self.plan(["--arm", "sim"])
        self.assertEqual([k.name for k in kids], ["controller", "voice"])  # sim_vision stands in for vision/

    def test_judge_only_when_asked_and_supported(self):
        self.assertNotIn("--judge", self.plan([])[0][0].cmd)
        self.assertIn("--judge", self.plan(["--judge"], judge_ok=True)[0][0].cmd)
        kids, notes = self.plan(["--judge"], judge_ok=False)
        self.assertNotIn("--judge", kids[0].cmd)
        self.assertTrue(any("no --judge" in n for n in notes))

    def test_skills_and_real_arm_pass_through(self):
        c = self.plan(["--skills", "taught"])[0][0].cmd
        self.assertEqual(c[c.index("--skills") + 1], "taught")
        self.assertNotIn("--skills", self.plan([])[0][0].cmd)
        self.assertIn("--real-arm", self.plan(["--real-arm"])[0][0].cmd)
        with self.assertRaises(SystemExit):
            R.parse(["--skills", "both"])

    def test_backup_runs_the_picker(self):
        a = R.parse(["backup", "--offline", "--base-port", "8240"])
        self.assertEqual(a.skills, "smart")
        c = self.plan(["backup", "--base-port", "8240"])[0][0].cmd
        self.assertEqual(c[c.index("--skills") + 1], "smart")
        self.assertEqual(R.parse(["backup", "--skills", "model"]).skills, "model")
        self.assertEqual(R.parse(["--skills", "smart"]).skills, "smart")

    def test_real_preset_is_the_judging_stack(self):
        a = R.parse(["--real"])
        self.assertEqual((a.arm, a.vision, a.ledger, a.judge, a.skills), ("real", "real", True, True, "auto"))
        kids, _ = self.plan(["--real"], judge_ok=True)
        c = kids[0].cmd
        self.assertEqual([k.name for k in kids if k.name != "voice"], ["controller", "vision", "ledger"])
        self.assertTrue({"--real-arm", "--judge"} <= set(c))
        self.assertEqual(c[c.index("--skills") + 1], "auto")
        self.assertNotIn("--fake", kids[1].cmd)
        self.assertEqual(R.parse(["--real", "--skills", "taught"]).skills, "taught")
        self.assertEqual(R.parse(["--real", "--arm", "sim"]).arm, "sim")
        self.assertEqual(R.parse(["backup", "--real"]).arm, "sim")  # backup never starts the real arm

    def test_tunnel_variants_and_skips(self):
        by = {k.name: k for k in self.plan(["--tunnel", "cf"])[0]}
        self.assertEqual(by["tunnel"].cmd, ["npm", "run", "tunnel:cf"])
        by = {k.name: k for k in self.plan(["--tunnel", "--tunnel-cmd", "echo hi"])[0]}
        self.assertEqual(by["tunnel"].cmd, ["echo", "hi"])
        kids, notes = R.plan(R.parse(["--no-voice", "--tunnel"]), judge_ok=True)
        self.assertEqual([k.name for k in kids], ["controller", "vision"])
        self.assertTrue(any("voice not started" in n for n in notes) and any("tunnel not started" in n for n in notes))

    def test_offline_blanks_keys_for_children(self):
        env = self.plan(["--offline"])[0][0].env
        self.assertEqual((env["VOICE_NO_KEYS"], env["MONGODB_URI"]), ("1", ""))

    def test_check_stack_saves_no_count(self):
        self.assertEqual(self.plan(["check", "--base-port", "8240"])[0][0].env["SCRUB_STATE_FILE"], "")
        a = R.parse([])
        self.assertEqual(R.child_env(a, R.ports(a)).get("SCRUB_STATE_FILE"), os.environ.get("SCRUB_STATE_FILE"))


class TestUrls(unittest.TestCase):
    def table(self, argv, **kw):
        with mock.patch.object(R, "voice_skip_reason", return_value=None):
            return dict(R.url_table(R.parse(argv), **kw))

    def test_fake_stack(self):
        t = self.table([])
        self.assertEqual(t["dashboard"], "http://localhost:8000/")
        self.assertEqual(t["judge console"], "http://localhost:8000/demo")
        self.assertEqual(t["nurse console"], "http://localhost:8000/nurse")
        self.assertEqual(t["tablet"], "http://localhost:8000/tablet.html")
        self.assertEqual(t["ops"], "http://localhost:8000/ops")
        self.assertEqual(t["vision preview"], "http://localhost:8001/")
        self.assertEqual(t["vision stream"], "http://localhost:8001/stream")
        self.assertEqual(t["voice health"], "http://localhost:3000/health")
        self.assertNotIn("sim viewer", t)
        self.assertNotIn("ledger page", t)

    def test_moved_stack_dashboard_names_its_vision_and_ledger(self):
        """M6: on moved ports the dashboard would read the live :8001 camera and :8080 ledger without these."""
        t = self.table(["--base-port", "8240"])
        self.assertEqual(t["dashboard"], "http://localhost:8240/?vision=http://localhost:8241&ledger=http://localhost:8243")
        self.assertEqual(R.dashboard_url(R.parse([])), "http://localhost:8000/")

    def test_sim_ledger_tunnel_lan(self):
        t = self.table(["--arm", "sim", "--base-port", "8240", "--ledger", "--tunnel"],
                       public_url="https://abc.a.free.pinggy.link", lan="10.0.0.5")
        self.assertEqual(t["sim viewer"], "http://localhost:8242/web/viewer.html")
        self.assertNotIn("vision preview", t)
        self.assertEqual(t["ledger page"], "http://localhost:8243/")
        self.assertEqual(t["public tunnel"], "https://abc.a.free.pinggy.link")
        self.assertEqual(t["ElevenLabs LLM URL"], "https://abc.a.free.pinggy.link/v1")
        self.assertEqual(t["tablet (LAN)"], "http://10.0.0.5:8240/tablet.html")
        text = R.format_table(R.url_table(R.parse([])))
        self.assertIn("  dashboard ", text)

    def test_no_voice_row_without_voice(self):
        self.assertNotIn("voice health", dict(R.url_table(R.parse(["--no-voice"]))))

    def test_tunnel_url_pattern(self):
        for line, want in (("You can access local server via following URL(s):", None),
                           ("http://rnxyz-1-2.a.free.pinggy.link https://rnxyz-1-2.a.free.pinggy.link", "https://rnxyz-1-2.a.free.pinggy.link"),
                           ("https://quiet-cat.run.pinggy-free.link", "https://quiet-cat.run.pinggy-free.link"),
                           ("|  https://some-words-here.trycloudflare.com  |", "https://some-words-here.trycloudflare.com"),
                           ("Dashboard https://dashboard.pinggy.io", None)):
            m = R.TUNNEL_RE.search(line)
            self.assertEqual(m.group(0) if m else None, want, line)


class TestChildren(unittest.TestCase):
    def child(self, name, code, critical=False):
        return R.Child(name, [sys.executable, "-u", "-c", code], R.ROOT, {}, None, critical=critical)

    def test_tunnel_url_seen_and_stop_kills_the_group(self):
        out = Quiet()
        st = R.Stack(out)
        ch = st.start(self.child("tunnel", "import time; print('connecting'); print('https://fake-1.a.free.pinggy.link'); time.sleep(60)"))
        self.assertEqual(st.wait_tunnel(ch, 10), "https://fake-1.a.free.pinggy.link")
        st.stop()
        self.assertIsNotNone(ch.proc.poll())
        self.assertTrue(any(l.startswith("PUBLIC URL https://fake-1") for l in out.lines))
        self.assertIn("[tunnel] connecting", out.lines)

    def test_sigint_ignored_falls_back_to_sigterm(self):
        st = R.Stack(Quiet())
        ch = st.start(self.child("stubborn", "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('up', flush=True); time.sleep(60)"))
        time.sleep(0.5)
        t0 = time.time()
        st.stop()
        if os.name == "nt":  # Windows process groups receive CTRL_BREAK rather than POSIX SIGTERM.
            self.assertNotEqual(ch.proc.returncode, 0)
        else:
            self.assertEqual(ch.proc.returncode, -signal.SIGTERM)
        self.assertLess(time.time() - t0, 8)

    def test_crash_names_the_child(self):
        out = Quiet()
        st = R.Stack(out)
        st.start(self.child("vision", "import time; time.sleep(60)"))
        st.start(self.child("controller", "print('boom'); raise SystemExit(3)", critical=True))
        try:
            self.assertEqual(R.watch(st), 1)
        finally:
            st.stop()
        text = "\n".join(out.lines)
        self.assertIn("controller EXITED (code 3)", text)
        self.assertIn("boom", text)
        self.assertIn("stopping the rest", text)

    def test_noncritical_crash_keeps_going(self):
        out = Quiet()
        st = R.Stack(out)
        st.start(self.child("voice", "raise SystemExit(2)"))
        st.children[0].proc.wait()
        crashed = st.crashed()
        self.assertEqual([c.name for c in crashed], ["voice"])
        self.assertEqual(st.crashed(), [])  # reported once
        st.stop()

    def test_bring_up_refuses_a_busy_controller_port(self):
        srv = serve(BUSY_PORT)
        try:
            out = Quiet()
            st = R.Stack(out)
            ok, _ = R.bring_up(R.parse(["--port", str(BUSY_PORT), "--no-voice", "--vision", "none"]), st)
            self.assertFalse(ok)
            self.assertEqual(st.children, [])
            self.assertTrue(any(f"port {BUSY_PORT} is in use" in l for l in out.lines))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_health_wait_gives_up_when_the_child_exits(self):
        st = R.Stack(Quiet())
        ch = R.Child("x", [sys.executable, "-c", "pass"], R.ROOT, {}, "http://127.0.0.1:8263/state")
        st.start(ch)
        self.assertFalse(st.wait_healthy(ch, 10))
        st.stop()


class TestPhoneCall(unittest.TestCase):
    """--real: a tunnel by default, the sim when the arm is busy, the agent pointed at each new URL, the number shown."""
    ok_arm = dict(holders=lambda p: [], exists=lambda p: True)

    def test_real_starts_a_tunnel_by_default(self):
        a = R.parse(["--real"])
        self.assertEqual(R.prepare_start(a, {"SO101_PORT": "/dev/tty.usbmodem1"}, **self.ok_arm), [])
        self.assertIn(a.tunnel, ("cf", "pinggy"))
        self.assertEqual((a.arm, a.vision), ("real", "real"))
        a = R.parse(["--real", "--tunnel", "ngrok"])
        R.prepare_start(a, {"SO101_PORT": "/dev/x"}, **self.ok_arm)
        self.assertEqual(a.tunnel, "ngrok")
        for argv in (["--real", "--no-tunnel"], ["--real", "--no-voice"], []):
            a = R.parse(argv)
            R.prepare_start(a, {"SO101_PORT": "/dev/x"}, **self.ok_arm)
            self.assertIsNone(a.tunnel, argv)

    def test_busy_or_missing_arm_runs_the_sim(self):
        for wiring, holders, exists, want in (({"SO101_PORT": ""}, [], True, "SO101_PORT is empty"),
                                              ({"SO101_PORT": "/dev/tty.usbmodem1"}, [], False, "not found"),
                                              ({"SO101_PORT": "/dev/tty.usbmodem1"}, [4242], True, "held by PID 4242")):
            a = R.parse(["--real"])
            notes = R.prepare_start(a, wiring, holders=lambda p, h=holders: h, exists=lambda p, e=exists: e)
            self.assertEqual((a.arm, a.vision), ("sim", "none"), want)
            self.assertTrue(any(want in n and "SIM arm" in n for n in notes), notes)
            self.assertIn(want, a.arm_note)
            with mock.patch.object(R, "voice_skip_reason", return_value=None):
                kids, _ = R.plan(a, judge_ok=True)
            self.assertIn("--sim-arm", kids[0].cmd)
            self.assertNotIn("vision", [k.name for k in kids])
        a = R.parse(["--arm", "real", "--vision", "fake"])  # an explicit vision choice is kept
        R.prepare_start(a, {"SO101_PORT": ""}, **self.ok_arm)
        self.assertEqual((a.arm, a.vision), ("sim", "fake"))

    def fake_agent(self, body):
        path = Path(tempfile.mkdtemp()) / "agent.py"
        path.write_text(body)
        return f"{sys.executable} {path}"

    def test_agent_update_gets_the_url_and_reads_the_phone(self):
        cmd = self.fake_agent("import sys\nprint('[agent] updated: Custom LLM ' + sys.argv[1] + '/v1')\n"
                              "print('AGENT agent_x')\nprint('PHONE +15550001111  (Scrub Photon, sip_trunk)')\n")
        a, out = R.parse(["--tunnel", "--agent-cmd", cmd]), Quiet()
        self.assertEqual(R.agent_update(a, "https://x.trycloudflare.com", out), ["+15550001111"])
        self.assertIn("[agent] updated: Custom LLM https://x.trycloudflare.com/v1", out.lines)
        st = R.Stack(Quiet())
        st.public_url = "https://x.trycloudflare.com"
        with mock.patch.object(R, "run_agent", wraps=R.run_agent) as up:
            chk = mock.Mock()
            R.sync_agent(a, st, chk)
            R.sync_agent(a, st, chk)  # same URL: not again
            st.public_url = "https://y.trycloudflare.com"
            R.sync_agent(a, st, chk)
        self.assertEqual([c.args[0:2][1] for c in up.call_args_list], ["https://x.trycloudflare.com", "https://y.trycloudflare.com"])
        self.assertEqual(R.phone_number(a, st, {"PHOTON_LINE": ""}), "+15550001111")
        self.assertEqual(R.phone_number(a, st, {"PHOTON_LINE": "+12065550100"}), "+12065550100")
        st.public_url = "https://z.trycloudflare.com"
        with mock.patch.object(R, "run_agent") as up:
            R.sync_agent(R.parse(["--tunnel", "--no-agent"]), st)
        up.assert_not_called()

    def test_agent_failure_is_reported_not_fatal(self):
        out = Quiet()
        a = R.parse(["--agent-cmd", self.fake_agent("print('[agent] HTTP 401')\nraise SystemExit(1)\n")])
        self.assertEqual(R.agent_update(a, "https://x.trycloudflare.com", out), [])
        self.assertTrue(any("agent update FAILED (exit 1)" in l and "https://x.trycloudflare.com/v1" in l for l in out.lines))

    def test_phone_row_in_the_url_table(self):
        with mock.patch.object(R, "voice_skip_reason", return_value=None):
            t = dict(R.url_table(R.parse(["--tunnel"]), public_url="https://x.trycloudflare.com", phone="+15550001111"))
            self.assertEqual(t["phone (call it)"], "+15550001111")
            empty = dict(R.url_table(R.parse(["--tunnel"])))["phone (call it)"]
            self.assertIn("no line yet", empty)
            self.assertIn("npm run photon -- setup +1", empty)
            self.assertNotIn("phone (call it)", dict(R.url_table(R.parse([]))))

    def test_expired_tunnel_restarts_and_quick_death_does_not(self):
        out = Quiet()
        st = R.Stack(out)
        ch = st.start(R.Child("tunnel", [sys.executable, "-u", "-c", "print('https://old-1.a.free.pinggy.link')"], R.ROOT, {}, None))
        ch.proc.wait()
        st.tunnel_fails = R.TUNNEL_QUICK_DEATHS - 1
        self.assertIsNone(R.restart_tunnel(st, ch, sleep=lambda s: None))  # dies right away over and over: give up
        ch.started -= 60
        st.public_url = "https://old-1.a.free.pinggy.link"
        new = R.restart_tunnel(st, ch)
        try:
            self.assertIsNotNone(new)
            self.assertIs(st.children[-1], new)
            self.assertEqual(st.wait_tunnel(new, 10), "https://old-1.a.free.pinggy.link")
            self.assertTrue(any("restarting the tunnel" in l for l in out.lines))
        finally:
            st.stop()

    def test_quick_death_is_retried_then_given_up(self):
        st = R.Stack(Quiet())
        ch = R.Child("tunnel", ["x"], R.ROOT, {}, None)
        ch.started = time.time()
        pauses = []
        with mock.patch.object(st, "start", side_effect=lambda c: c):
            for n in range(1, R.TUNNEL_QUICK_DEATHS):
                self.assertIsNotNone(R.restart_tunnel(st, ch, sleep=pauses.append), n)
            self.assertIsNone(R.restart_tunnel(st, ch, sleep=pauses.append))
            self.assertEqual(len(pauses), R.TUNNEL_QUICK_DEATHS - 1)
            ch.started -= 60  # a long-lived tunnel dying resets the count
            self.assertIsNotNone(R.restart_tunnel(st, ch, sleep=pauses.append))
            self.assertEqual(st.tunnel_fails, 0)

    def test_new_url_after_restart_repoints_agent_and_self_checks(self):
        a, st, calls = R.parse(["--tunnel", "--agent-cmd", "x"]), R.Stack(Quiet()), []
        with mock.patch.object(R, "run_agent", side_effect=lambda a_, u, say=print: (calls.append(u) or (True, ["+1555"]))):
            chk = mock.Mock()
            st.public_url = "https://a.trycloudflare.com"
            R.sync_agent(a, st, chk)
            st.public_url = None  # tunnel died; cloudflared restarted with a new URL
            st.public_url = "https://b.trycloudflare.com"
            R.sync_agent(a, st, chk)
        self.assertEqual(calls, ["https://a.trycloudflare.com", "https://b.trycloudflare.com"])
        self.assertEqual([c.args[0] for c in chk.call_args_list], calls)
        self.assertEqual(st.phones, ["+1555"])

    def test_failed_agent_update_is_retried_loudly_then_gives_up(self):
        out = Quiet()
        a, st = R.parse(["--tunnel", "--agent-cmd", "x"]), R.Stack(out)
        st.public_url = "https://a.trycloudflare.com"
        chk = mock.Mock()
        with mock.patch.object(R, "run_agent", return_value=(False, [])) as ra:
            for _ in range(R.AGENT_TRIES + 3):
                st.agent_next = 0  # skip the backoff wait
                R.sync_agent(a, st, chk)
        self.assertEqual(ra.call_count, R.AGENT_TRIES)
        chk.assert_not_called()  # no self-check claimed for an agent that wasn't updated
        self.assertTrue(any("GAVE UP" in l and "npm run agent -- https://a.trycloudflare.com" in l for l in out.lines))
        # backoff: a failure right now means no immediate retry
        st2, calls = R.Stack(Quiet()), mock.Mock(return_value=(False, []))
        st2.public_url = "https://c.trycloudflare.com"
        with mock.patch.object(R, "run_agent", calls):
            R.sync_agent(a, st2, chk)
            R.sync_agent(a, st2, chk)
        self.assertEqual(calls.call_count, 1)

    def test_agent_nonzero_exit_says_so_loudly(self):
        out = Quiet()
        a = R.parse(["--agent-cmd", self.fake_agent("raise SystemExit(1)\n")])
        ok, _ = R.run_agent(a, "https://x.trycloudflare.com", out)
        self.assertFalse(ok)
        self.assertTrue(any("!!" in l and "FAILED" in l for l in out.lines))

    def test_public_check(self):
        resp = lambda code: mock.Mock(status_code=code)
        out = Quiet()
        seq = iter([OSError("dns"), resp(502), resp(200)])
        def get(url, timeout):
            r = next(seq)
            if isinstance(r, Exception):
                raise r
            self.assertEqual(url, "https://x.trycloudflare.com/health")
            return r
        self.assertTrue(R.public_check("https://x.trycloudflare.com", out, tries=5, delay=0, get=get))
        self.assertTrue(any("self-check OK" in l and "200" in l for l in out.lines))
        out = Quiet()
        self.assertFalse(R.public_check("https://x.trycloudflare.com", out, tries=2, delay=0, get=lambda u, timeout: resp(530)))
        self.assertTrue(any("self-check FAILED" in l and "530" in l for l in out.lines))


class TestReset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve(FAKE_PORT)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeController.calls, FakeController.sim, FakeController.busy_resets = [], False, 0
        FakeController.state = {"step": "idle", "out": ["hemostat"], "setting": "bench", "lighting": "dim", "fake_arm": True}

    def posts(self):
        return [(p, b) for m, p, b in FakeController.calls if m == "POST"]

    def run_reset(self, sim_url=None):
        with httpx.Client(base_url=f"http://127.0.0.1:{FAKE_PORT}", timeout=5) as c:
            return R.reset_stack(c, sim_url, say=Quiet(), timeout=5)

    def test_fake_arm_sequence(self):
        st = self.run_reset()
        self.assertEqual(self.posts(), [("/reset", {"clear_count": True}),
                                        ("/setting", {"setting": "surgical"}),
                                        ("/lighting", {"lighting": "normal", "lux": None})])
        self.assertEqual((st["out"], st["setting"], st["lighting"]), ([], "surgical", "normal"))
        self.assertNotIn("/stop", [p for p, _ in self.posts()])
        self.assertNotIn("/summary", [p for p, _ in self.posts()])

    def test_sim_resets_the_scene_first(self):
        FakeController.sim = True
        self.run_reset(f"http://127.0.0.1:{FAKE_PORT}")  # the sim server's own reset: one "Reset. Ready." on the call
        self.assertEqual(self.posts(), [("/scene/setting", {"setting": "surgical"}), ("/scene/reset", None),
                                        ("/reset", {"clear_count": True}), ("/setting", {"setting": "surgical"}),
                                        ("/lighting", {"lighting": "normal", "lux": None})])

    def test_sim_without_the_sim_server_uses_the_controller_hook(self):
        FakeController.sim = True
        self.run_reset(None)
        self.assertEqual([p for p, _ in self.posts()], ["/sim/scene_reset", "/reset", "/setting", "/lighting"])

    def test_busy_reset_is_retried(self):
        FakeController.busy_resets = 2
        st = self.run_reset()
        self.assertEqual([p for p, _ in self.posts()].count("/reset"), 3)
        self.assertEqual(st["setting"], "surgical")

    def test_already_surgical_makes_no_extra_case(self):
        """M10: /setting starts a new case, so it is posted only when the tray isn't surgical already."""
        FakeController.state = dict(FakeController.state, setting="surgical")
        st = self.run_reset()
        self.assertEqual([p for p, _ in self.posts()], ["/reset", "/lighting"])
        self.assertEqual((st["out"], st["setting"]), ([], "surgical"))


class TestShapes(unittest.TestCase):
    def test_stats(self):
        good = {"by_item": [{"item": "hemostat", "attempts": 2, "successes": 1, "success_rate": 0.5,
                             "median_request_to_hand_s": 6.0}],
                "by_lighting": [], "median_request_to_hand_s": None, "out": [], "t": 1.0}
        self.assertEqual(R.stats_problems(good), [])
        self.assertTrue(R.stats_problems({"source": "controller memory (ledger not loaded)", "by_item": {},
                                          "median_request_to_hand_s": None}))
        self.assertTrue(R.stats_problems(dict(good, by_item=[{"item": "hemostat"}])))
        self.assertTrue(R.stats_problems([]))

    def test_setting(self):
        s = {"id": "surgical", "label": "Operating room", "return_spot": None,
             "items": [{"id": i, "name": i, "aliases": [], "sharp": False} for i in ("scalpel", "hemostat", "mayo_scissors")]}
        self.assertEqual(R.setting_problems(s, "surgical"), [])
        self.assertTrue(R.setting_problems(s, "bench"))
        self.assertTrue(R.setting_problems(dict(s, items=s["items"][:2])))


class TestRealController(unittest.TestCase):
    """The reset sequence against the real controller (fake arm) on a test port."""

    def test_reset_after_a_handover(self):
        from controller.smoke import one
        p = subprocess.Popen([sys.executable, "-m", "controller", "--fake-arm", "--port", str(CTL_PORT),
                              "--motion-s", "0.05", "--pull-s", "0.2"], cwd=R.ROOT,
                             env=dict(R.os.environ, MONGODB_URI="", SCRUB_STATE_FILE=""), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            url = f"http://127.0.0.1:{CTL_PORT}"
            end = time.time() + 30
            while time.time() < end and not R.answers(f"{url}/state", 0.5):
                time.sleep(0.2)
            with httpx.Client(base_url=url, timeout=5) as c:
                ok, _, _ = one(c, "handover", "hemostat", False, 30)
                self.assertTrue(ok)
                c.post("/lighting", json={"lighting": "dim", "lux": None})
                self.assertEqual(c.get("/state").json()["out"], ["hemostat"])
                st = R.reset_stack(c, None, say=Quiet(), timeout=20)
            self.assertEqual((st["step"], st["out"], st["setting"], st["lighting"]), ("idle", [], "surgical", "normal"))
        finally:
            R._signal(p, signal.SIGTERM)
            p.wait(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=1)
