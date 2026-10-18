"""Offline tests for controller/run_all.py: options, ports, env wiring, URL table, child handling, reset.

  .venv/bin/python -m controller.test_run_all

Uses ports 8260 to 8263 only (a fake HTTP server and one fake-arm controller). No voice, no tunnel, no browser.
"""
import json
import signal
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import httpx

from controller import run_all as R

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
        self.assertEqual(t["vision preview"], "http://localhost:8001/")
        self.assertEqual(t["vision stream"], "http://localhost:8001/stream")
        self.assertEqual(t["voice health"], "http://localhost:3000/health")
        self.assertNotIn("sim viewer", t)
        self.assertNotIn("ledger page", t)

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
                             env=dict(R.os.environ, MONGODB_URI=""), stdout=subprocess.DEVNULL,
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
