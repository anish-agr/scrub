"""One command for the whole Scrub stack (L7), the between-judges reset, the sim backup run and the full-stack check (L10).

  .venv/bin/python -m controller.run_all                       # fake arm, vision --fake, voice, opens the dashboard
  .venv/bin/python -m controller.run_all --arm sim             # MuJoCo arm (sim_vision stands in for vision/)
  .venv/bin/python -m controller.run_all --arm real --vision real --tunnel --judge
  .venv/bin/python -m controller.run_all --base-port 8240 --no-voice --no-open   # a test stack beside the live one
  .venv/bin/python -m controller.run_all reset                 # between judges: clear the count, surgical tray, normal light
  .venv/bin/python -m controller.run_all backup [--loop]       # the arm failed: sim arm stack plus a scripted demo run
  .venv/bin/python -m controller.run_all check [--url URL]     # L10 full-stack check (own fake stack on --base-port 8100)

Ports: controller --port (8000), vision --vision-port (8001), sim viewer --sim-port (8002), voice --voice-port (3000),
ledger page --ledger-port (8080). --base-port N moves them together: N, N+1, N+2, N-5000 and N+3.
Children get CONTROLLER_URL, VISION_URL and VOICE_PORT. Ctrl-C stops every child.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
LEDGER_BUFFER = Path(os.environ.get("LEDGER_BUFFER") or ROOT / "ledger" / "buffer.jsonl")  # read only
COMMANDS = ("start", "reset", "backup", "check")
TUNNEL_SCRIPTS = {"pinggy": "tunnel", "cf": "tunnel:cf", "ngrok": "tunnel:ngrok"}
TUNNEL_RE = re.compile(r"https://[A-Za-z0-9.-]+\.(?:pinggy-free\.link|pinggy\.link|pinggy\.online|trycloudflare\.com"
                       r"|ngrok-free\.app|ngrok-free\.dev|ngrok\.app|ngrok\.io)\b")
SETTING_ITEMS = {"surgical": {"scalpel", "hemostat", "mayo_scissors"},
                 "bench": {"needle_nose_pliers", "wire_cutters", "hex_key"},
                 "dental": {"mouth_mirror", "explorer", "cotton_pliers"}}
BACKUP_SCRIPT = [("handover", "hemostat"), ("handover", "scalpel"), ("handover", "mayo_scissors"),
                 ("return", "hemostat"), ("count", None)]
IDLE = ("idle", "stopped", "error")


# ---------------------------------------------------------------- options
def parse(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv and argv[0] in COMMANDS else "start"
    p = argparse.ArgumentParser(prog=f"python -m controller.run_all [{'|'.join(COMMANDS[1:])}]",
                                description=__doc__.split("\n")[0])
    p.add_argument("--arm", choices=["fake", "sim", "real"], default=None, help="fake (default; sim for backup)")
    p.add_argument("--vision", choices=["real", "fake", "none"], default=None,
                   help="fake (default), none with --arm sim (sim_vision posts the tray in-process)")
    p.add_argument("--no-voice", action="store_true", help="don't start voice/ (skipped anyway without node_modules)")
    p.add_argument("--tunnel", nargs="?", const="pinggy", choices=sorted(TUNNEL_SCRIPTS),
                   help="public tunnel to voice: npm run tunnel (pinggy), tunnel:cf or tunnel:ngrok")
    p.add_argument("--tunnel-cmd", help=argparse.SUPPRESS)  # tests: a fake tunnel command
    p.add_argument("--ledger", action="store_true", help="also start the ledger public page (python -m ledger serve)")
    p.add_argument("--open", action=argparse.BooleanOptionalAction, default=True, help="open the dashboard (default on)")
    p.add_argument("--judge", action="store_true", help="pass --judge to the controller (judge mode)")
    p.add_argument("--setting", default="surgical", metavar="surgical|bench")
    p.add_argument("--motion-s", type=float, help="fake arm seconds per motion (controller default 1.0)")
    p.add_argument("--pull-s", type=float, help="fake arm simulated pull after this many seconds")
    p.add_argument("--offline", action="store_true",
                   help="tests: voice ignores .env keys (VOICE_NO_KEYS=1), ledger buffers locally (MONGODB_URI empty)")
    p.add_argument("--base-port", type=int, default=None, help="controller port; the others follow (default 8000)")
    for name in ("port", "vision-port", "sim-port", "voice-port", "ledger-port"):
        p.add_argument(f"--{name}", type=int)
    p.add_argument("--url", help="reset/check/backup: an already-running controller (default http://localhost:<port>)")
    p.add_argument("--vision-url", help="check: vision to probe (default VISION_URL of the stack)")
    p.add_argument("--voice-url", help="check: voice to probe")
    p.add_argument("--loop", action="store_true", help="backup: repeat the scripted run until Ctrl-C")
    p.add_argument("--pause", type=float, default=1.0, help="backup: seconds between steps")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for each health check")
    p.add_argument("--verbose", action="store_true", help="also print vision's per-request HTTP log lines")
    a = p.parse_args(argv)
    a.cmd = cmd
    if a.base_port is None:
        a.base_port = 8100 if cmd == "check" and not a.url else 8000
    if a.arm is None:
        a.arm = "sim" if cmd == "backup" else "fake"
    if a.vision is None:
        a.vision = "none" if a.arm == "sim" or cmd == "backup" else "fake"
    if cmd == "check" and not a.url:  # a private fake stack: fast motions, no voice, nothing opened
        a.no_voice, a.open, a.tunnel = True, False, None
        if a.motion_s is None and a.arm == "fake":
            a.motion_s = 0.2
        if a.pull_s is None and a.arm == "fake":
            a.pull_s = 0.5
    if a.arm == "real" and cmd in ("backup", "check") and not a.url:
        p.error(f"{cmd} never starts the real arm")
    return a


def ports(a) -> dict:
    b = a.base_port
    return {"controller": a.port or b, "vision": a.vision_port or b + 1, "sim": a.sim_port or b + 2,
            "voice": a.voice_port or b - 5000, "ledger": a.ledger_port or (8080 if b == 8000 else b + 3)}


def controller_url(a) -> str:
    return (a.url or f"http://localhost:{ports(a)['controller']}").rstrip("/")


# ---------------------------------------------------------------- what to start
@dataclass
class Child:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict
    health: str | None
    critical: bool = False
    stop_sig: int = signal.SIGINT  # SIGINT lets the sim controller and uvicorn shut down cleanly
    proc: subprocess.Popen | None = None
    reported: bool = False
    pump: threading.Thread | None = None
    lines: list[str] = field(default_factory=list)


def child_env(a, P: dict) -> dict:
    env = dict(os.environ)
    env.update(PYTHONUNBUFFERED="1", CONTROLLER_URL=f"http://localhost:{P['controller']}",
               VISION_URL=f"http://localhost:{P['vision']}", VOICE_PORT=str(P["voice"]))
    if a.offline:
        env.update(VOICE_NO_KEYS="1", MONGODB_URI="")
    if a.cmd == "check":
        env["SCRUB_STATE_FILE"] = ""  # a throwaway check stack never saves or restores a count
    return env


def dashboard_url(a) -> str:
    """The dashboard reads vision on :8001 and the ledger on :8080 unless told otherwise: a moved stack names its own."""
    P = ports(a)
    url = f"http://localhost:{P['controller']}/"
    if P["vision"] != 8001 or P["ledger"] != 8080:
        url += f"?vision=http://localhost:{P['vision']}&ledger=http://localhost:{P['ledger']}"
    return url


def controller_has_judge() -> bool:
    try:
        out = subprocess.run([PY, "-m", "controller", "--help"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        return "--judge" in out.stdout
    except Exception:
        return False


def voice_skip_reason(a) -> str | None:
    if a.no_voice:
        return "--no-voice"
    if not (ROOT / "voice" / "node_modules").is_dir():
        return "voice/node_modules missing (cd voice && npm install)"
    if not shutil.which("npm"):
        return "npm not on PATH"
    return None


def plan(a, judge_ok: bool | None = None) -> tuple[list[Child], list[str]]:
    """The children to start, in order, and notes about what was skipped."""
    P, env, notes = ports(a), child_env(a, ports(a)), []
    c = [PY, "-u", "-m", "controller", "--port", str(P["controller"]), "--setting", a.setting]
    if a.arm == "sim":
        c += ["--sim-arm", "--sim-port", str(P["sim"])]
    elif a.arm == "real":
        c += ["--real-arm"]
    else:
        c += ["--fake-arm"]
        if a.motion_s is not None:
            c += ["--motion-s", str(a.motion_s)]
        if a.pull_s is not None:
            c += ["--pull-s", str(a.pull_s)]
    if a.judge:
        if judge_ok is None:
            judge_ok = controller_has_judge()
        if judge_ok:
            c += ["--judge"]
        else:
            notes.append("controller has no --judge yet: started without it")
    kids = [Child("controller", c, ROOT, env, f"http://localhost:{P['controller']}/state", critical=True)]
    if a.vision != "none":
        v = [PY, "-u", "-m", "vision", "--port", str(P["vision"])] + (["--fake"] if a.vision == "fake" else [])
        kids.append(Child("vision", v, ROOT, dict(env, VISION_PORT=str(P["vision"])),
                          f"http://localhost:{P['vision']}/health"))
    if a.arm == "sim" and a.vision == "fake":
        notes.append("vision --fake and the sim's own tray poster will both post TrayStates; --vision none is usual")
    skip = voice_skip_reason(a)
    if skip:
        notes.append(f"voice not started: {skip}")
    else:
        kids.append(Child("voice", ["npm", "run", "dev"], ROOT / "voice", env, f"http://localhost:{P['voice']}/health"))
    if a.ledger:
        kids.append(Child("ledger", [PY, "-u", "-m", "ledger", "serve"], ROOT, dict(env, PORT=str(P["ledger"])),
                          f"http://localhost:{P['ledger']}/", stop_sig=signal.SIGTERM))  # no traceback on stop
    if a.tunnel:
        if skip and not a.tunnel_cmd:
            notes.append("tunnel not started: no voice to tunnel to")
        else:
            cmd = shlex.split(a.tunnel_cmd) if a.tunnel_cmd else ["npm", "run", TUNNEL_SCRIPTS[a.tunnel]]
            kids.append(Child("tunnel", cmd, ROOT / "voice", env, None))
    return kids, notes


def url_table(a, public_url: str | None = None, lan: str | None = None, skipped: set | None = None) -> list[tuple[str, str]]:
    P, skipped = ports(a), skipped or set()
    c = f"http://localhost:{P['controller']}"
    rows = [("dashboard", dashboard_url(a)), ("judge console", f"{c}/demo"), ("nurse console", f"{c}/nurse"),
            ("tablet", f"{c}/tablet.html"), ("state", f"{c}/state")]
    if lan:
        rows.append(("tablet (LAN)", f"http://{lan}:{P['controller']}/tablet.html"))
    if a.arm == "sim":
        rows.append(("sim viewer", f"http://localhost:{P['sim']}/web/viewer.html"))
        rows.append(("sim camera", f"http://localhost:{P['sim']}/stream"))
    if a.vision != "none":
        v = f"http://localhost:{P['vision']}"
        rows += [("vision preview", f"{v}/"), ("vision stream", f"{v}/stream")]
    if "voice" not in skipped and not voice_skip_reason(a):
        rows.append(("voice health", f"http://localhost:{P['voice']}/health"))
    if a.ledger:
        rows.append(("ledger page", f"http://localhost:{P['ledger']}/"))
    if a.tunnel:
        rows.append(("public tunnel", public_url or "(not seen yet; watch the [tunnel] lines)"))
        if public_url:
            rows.append(("ElevenLabs LLM URL", f"{public_url}/v1"))
    return rows


def format_table(rows) -> str:
    w = max(len(k) for k, _ in rows)
    return "\n".join(f"  {k:<{w}}  {v}" for k, v in rows)


def lan_ip() -> str | None:
    try:  # UDP connect sends nothing; it only picks the outgoing interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def answers(url: str, timeout: float = 2.0) -> bool:
    try:
        return httpx.get(url, timeout=timeout).status_code < 500
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------- running children
class Stack:
    def __init__(self, out=None, verbose: bool = False):
        self.verbose = verbose
        self.children: list[Child] = []
        self.public_url: str | None = None
        self.stopping = False
        self._out, self._lock = out or (lambda text: print(text, flush=True)), threading.Lock()

    def say(self, text: str) -> None:
        with self._lock:
            self._out(text)

    def start(self, ch: Child) -> Child:
        ch.proc = subprocess.Popen(ch.cmd, cwd=ch.cwd, env=ch.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                                   start_new_session=True)  # own process group: we stop npm and its node together
        self.children.append(ch)
        ch.pump = threading.Thread(target=self._pump, args=(ch,), daemon=True)
        ch.pump.start()
        return ch

    def _pump(self, ch: Child) -> None:
        for line in ch.proc.stdout:
            line = line.rstrip("\n")
            ch.lines = (ch.lines + [line])[-50:]
            if ch.name == "tunnel" and not self.public_url:
                m = TUNNEL_RE.search(line)
                if m:
                    self.public_url = m.group(0)
                    self.say(f"PUBLIC URL {self.public_url}  (ElevenLabs Custom LLM Server URL: {self.public_url}/v1)")
            if not self.verbose and "INFO HTTP Request: " in line:
                continue  # vision logs every httpx call to the controller at INFO; --verbose shows them
            self.say(f"[{ch.name}] {line}")
        ch.proc.stdout.close()

    def wait_healthy(self, ch: Child, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if ch.proc.poll() is not None:
                return False
            if ch.health is None or answers(ch.health, 1.0):
                return True
            time.sleep(0.3)
        return False

    def wait_tunnel(self, ch: Child, timeout: float) -> str | None:
        end, ngrok = time.time() + timeout, "ngrok" in " ".join(ch.cmd)
        while time.time() < end and not self.public_url and ch.proc.poll() is None:
            if ngrok:  # ngrok draws a screen instead of printing; its local API has the URL
                try:
                    for t in httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=1).json().get("tunnels", []):
                        if t.get("public_url", "").startswith("https://"):
                            self.public_url = t["public_url"]
                except (httpx.HTTPError, ValueError):
                    pass
            time.sleep(0.3)
        return self.public_url

    def crashed(self) -> list[Child]:
        out = []
        for ch in self.children:
            if not ch.reported and ch.proc.poll() is not None:
                ch.reported = True
                out.append(ch)
        return out

    def stop(self) -> None:
        self.stopping = True
        for ch in reversed(self.children):
            if ch.proc.poll() is None:
                _signal(ch.proc, ch.stop_sig)
        for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
            end = time.time() + wait
            while time.time() < end and any(ch.proc.poll() is None for ch in self.children):
                time.sleep(0.1)
            for ch in self.children:
                if ch.proc.poll() is None:
                    _signal(ch.proc, sig)
        for ch in self.children:
            try:
                ch.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            if ch.pump:
                ch.pump.join(timeout=2)


def _signal(proc: subprocess.Popen, sig) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def bring_up(a, stack: Stack) -> tuple[bool, set]:
    """Start every child and wait for its health check. Reuses an optional service already on its port."""
    kids, notes = plan(a)
    for n in notes:
        stack.say(f"run_all: {n}")
    skipped = set()
    P = ports(a)
    port_of = {"controller": P["controller"], "vision": P["vision"], "voice": P["voice"], "ledger": P["ledger"]}
    if a.arm == "sim" and port_busy(P["sim"]):
        stack.say(f"run_all: port {P['sim']} (sim viewer) is in use. Pick other ports with --base-port or --sim-port.")
        return False, skipped
    for ch in kids:
        port = port_of.get(ch.name)
        if port and port_busy(port):
            if ch.critical:
                stack.say(f"run_all: port {port} is in use, so a controller (or something) is already there. "
                          f"Stop it, or run beside it with --base-port.")
                return False, skipped
            if ch.health and answers(ch.health):
                stack.say(f"run_all: {ch.name} already answers on :{port}; using it, not starting another")
            else:
                stack.say(f"run_all: port {port} is in use by something that isn't {ch.name}; {ch.name} not started")
                skipped.add(ch.name)
            continue
        stack.say(f"run_all: starting {ch.name}: {' '.join(ch.cmd)}")
        stack.start(ch)
        if ch.name == "tunnel":
            if not stack.wait_tunnel(ch, 30):
                stack.say("run_all: no public URL from the tunnel yet; it prints below when it appears")
            continue
        if not stack.wait_healthy(ch, a.timeout):
            code = ch.proc.poll()
            stack.say(f"run_all: {ch.name} {'exited with code ' + str(code) if code is not None else 'did not answer'} "
                      f"{ch.health or ''}")
            if ch.critical:
                return False, skipped
            skipped.add(ch.name)
        else:
            stack.say(f"run_all: {ch.name} up")
    return True, skipped


def print_table(a, stack: Stack, skipped: set) -> None:
    title = f"Scrub stack: {a.arm} arm, vision {a.vision}, voice {'off' if voice_skip_reason(a) or 'voice' in skipped else 'on'}"
    stack.say(f"\n{title}\n{format_table(url_table(a, stack.public_url, lan_ip(), skipped))}\nCtrl-C stops everything.\n")


def open_pages(a) -> None:
    if not a.open:
        return
    P = ports(a)
    webbrowser.open(dashboard_url(a))
    if a.arm == "sim":
        webbrowser.open(f"http://localhost:{P['sim']}/web/viewer.html")


def watch(stack: Stack) -> int:
    """Until Ctrl-C. A controller crash stops everything; any other crash is reported and the rest keeps going."""
    while True:
        for ch in stack.crashed():
            stack.say(f"run_all: {ch.name} EXITED (code {ch.proc.returncode}). Last lines:")
            for line in ch.lines[-5:]:
                stack.say(f"    {line}")
            if ch.critical:
                stack.say("run_all: the controller is gone; stopping the rest")
                return 1
            if ch.name == "tunnel":
                stack.say("run_all: free tunnels end after about 60 min: rerun with --tunnel and paste the new URL")
            stack.say(f"run_all: still running: {', '.join(c.name for c in stack.children if c.proc.poll() is None)}")
        time.sleep(0.5)


def _sigterm(*_):
    raise KeyboardInterrupt


def cmd_start(a) -> int:
    stack = Stack(verbose=a.verbose)
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        ok, skipped = bring_up(a, stack)
        if not ok:
            return 1
        print_table(a, stack, skipped)
        open_pages(a)
        return watch(stack)
    except KeyboardInterrupt:
        stack.say("\nrun_all: stopping")
        return 0
    finally:
        if stack.children:
            stack.stop()
            stack.say("run_all: all children stopped")


# ---------------------------------------------------------------- reset (between judges)
def wait_idle(c: httpx.Client, timeout: float = 60.0) -> dict:
    end = time.time() + timeout
    st = c.get("/state").json()
    while st.get("step") not in IDLE and time.time() < end:
        time.sleep(0.2)
        st = c.get("/state").json()
    return st


def _post_retry(c: httpx.Client, path: str, body, timeout: float) -> httpx.Response:
    """409 means the arm is busy: wait for idle and try again."""
    end = time.time() + timeout
    while True:
        r = c.post(path, json=body)
        if r.status_code != 409 or time.time() > end:
            return r
        wait_idle(c, max(0.5, end - time.time()))
        time.sleep(0.3)


def reset_stack(c: httpx.Client, sim_url: str | None = None, say=print, timeout: float = 60.0) -> dict:
    """Clear the count, rearm, surgical tray, normal light. No /stop and no voice summary.
    On the sim arm, first put every instrument back in its slot (the sim server's own scene reset, so
    the call hears "Reset. Ready." once; the controller's /sim/scene_reset when the sim server isn't reachable)."""
    if c.get("/sim/vision").status_code == 200:
        wait_idle(c, timeout)  # never reload the scene under a running handover
        try:
            httpx.post(f"{sim_url}/scene/setting", json={"setting": "surgical"}, timeout=10).raise_for_status()
            r = httpx.post(f"{sim_url}/scene/reset", timeout=10)
            r.raise_for_status()
            say(f"  sim scene reset ({sim_url}): {r.json()}")
        except (httpx.HTTPError, TypeError):
            r = c.post("/sim/scene_reset")
            say(f"  sim scene reset (controller): {r.json()}")
            wait_idle(c, timeout)
    r = _post_retry(c, "/reset", {"clear_count": True}, timeout)
    say(f"  reset (clear count): {r.status_code} {r.json()}")
    wait_idle(c, timeout)
    if c.get("/state").json().get("setting") != "surgical":  # a switch starts another case: only when needed
        r = _post_retry(c, "/setting", {"setting": "surgical"}, timeout)
        say(f"  setting surgical: {r.status_code} {r.json().get('label', r.json()) if r.status_code == 200 else r.text}")
    else:
        say("  setting surgical: already")
    r = c.post("/lighting", json={"lighting": "normal", "lux": None})
    say(f"  lighting normal: {r.status_code} {r.json()}")
    st = wait_idle(c, timeout)
    return st


def cmd_reset(a) -> int:
    url = controller_url(a)
    print(f"reset {url}")
    with httpx.Client(base_url=url, timeout=10) as c:
        try:
            st = reset_stack(c, f"http://localhost:{ports(a)['sim']}", timeout=a.timeout)
        except httpx.HTTPError as e:
            print(f"controller not reachable at {url}: {e}")
            return 1
    print("state: " + json.dumps(st))
    ok = st.get("step") == "idle" and not st.get("out") and st.get("setting") == "surgical"
    print("READY for the next judge" if ok else "NOT ready: check the state above")
    return 0 if ok else 1


# ---------------------------------------------------------------- backup (scripted sim demo)
def _events_since(c: httpx.Client, t0: float) -> list[dict]:
    return [e for e in c.get("/events/recent", params={"n": 200}).json() if (e.get("t") or 0) >= t0]


def sim_return(c: httpx.Client, item: str, judge: bool, timeout: float = 60.0) -> tuple[bool, str]:
    """Set the item in the return spot. Auto return (F1) takes it back after 2 s; else ask for the return."""
    from .smoke import one
    t0 = time.time()
    if c.post("/sim/return_spot", json={"item": item}).json().get("ok") is not True:
        return False, "couldn't place it in the return spot"
    end, auto = time.time() + timeout, False
    while time.time() < end:
        evs = [e for e in _events_since(c, t0) if e.get("item") == item]
        auto = auto or any(e["type"] == "command" and e.get("source") == "auto" for e in evs)
        if any(e["type"] == "returned" for e in evs):
            return True, " / ".join(e["say"] for e in evs if e.get("say")) + "  (auto return)"
        if any(e["type"] in ("missed", "error", "stopped") for e in evs):
            return False, ",".join(e["type"] for e in evs)
        if not auto and time.time() - t0 > 5 and not judge:
            ok, said, _ = one(c, "return", item, False, timeout)
            return ok, said
        time.sleep(0.25)
    return False, "no return"


def demo_run(c: httpx.Client, say=print, pause: float = 1.0) -> bool:
    from .smoke import one
    judge = bool(c.get("/state").json().get("judge"))
    clean = True
    for action, item in BACKUP_SCRIPT:
        if action == "handover":
            ok, said, rth = one(c, "handover", item, False, 90)
            say(f"  {'ok  ' if ok else 'FAIL'}  handover {item:14} {f'{rth:5.1f}s' if rth else '      '}  {said}")
        elif action == "return":
            ok, said = sim_return(c, item, judge)
            say(f"  {'ok  ' if ok else 'FAIL'}  return   {item:14}         {said}")
        else:
            r = c.post("/command", json={"action": "count", "source": "keyboard", "t": time.time()}).json()
            ok = bool(r.get("accepted"))
            say(f"  {'ok  ' if ok else 'FAIL'}  count                           {r.get('say')}")
        clean &= ok
        time.sleep(pause)
    return clean


def cmd_backup(a) -> int:
    url, P = controller_url(a), ports(a)
    stack = Stack(verbose=a.verbose)
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        if answers(f"{url}/state"):
            if httpx.get(f"{url}/sim/vision", timeout=3).status_code != 200:
                print(f"run_all backup: {url} is a controller without the sim arm. Stop it (Ctrl-C in its terminal), "
                      f"then run backup again, or run beside it: backup --base-port 8100")
                return 1
            print(f"run_all backup: using the sim controller already at {url}")
        else:
            a.arm, a.vision = "sim", "none" if a.vision == "fake" else a.vision
            ok, skipped = bring_up(a, stack)
            if not ok:
                return 1
            print_table(a, stack, skipped)
        if a.open:
            webbrowser.open(f"{url}/" if a.url else dashboard_url(a))
            webbrowser.open(f"http://localhost:{P['sim']}/web/viewer.html")
        run, best = 0, True
        with httpx.Client(base_url=url, timeout=10) as c:
            while True:
                run += 1
                stack.say(f"\nbackup run {run}: resetting the tray")
                reset_stack(c, f"http://localhost:{P['sim']}", say=stack.say, timeout=a.timeout)
                time.sleep(1.5)  # a TrayState of the reset tray
                clean = demo_run(c, stack.say, a.pause)
                best &= clean
                stack.say(f"backup run {run}: {'CLEAN' if clean else 'NOT CLEAN'}")
                if not a.loop:
                    break
                time.sleep(3)
        if stack.children:
            stack.say("run_all backup: the sim stack keeps running for the demo. Ctrl-C stops it.")
            return watch(stack)
        return 0 if best else 1
    except KeyboardInterrupt:
        stack.say("\nrun_all: stopping")
        return 0
    finally:
        stack.stop()


# ---------------------------------------------------------------- check (L10)
def stats_problems(d) -> list[str]:
    """What the dashboard's paintStats/fillTable read from GET /stats (ledger.stats() shape)."""
    if not isinstance(d, dict):
        return ["not a JSON object"]
    bad = []
    if "source" in d:
        bad.append(f"controller fallback, not the ledger ({d['source']})")
    for key, label in (("by_item", "item"), ("by_lighting", "lighting")):
        rows = d.get(key)
        if not isinstance(rows, list):
            bad.append(f"{key} is {type(rows).__name__}, want a list")
            continue
        for row in rows:
            missing = {label, "attempts", "successes", "success_rate", "median_request_to_hand_s"} - set(row or {})
            if missing:
                bad.append(f"{key} row missing {sorted(missing)}")
                break
    m = d.get("median_request_to_hand_s", "absent")
    if not (m is None or isinstance(m, (int, float))):
        bad.append(f"median_request_to_hand_s is {m!r}")
    if not isinstance(d.get("out"), list):
        bad.append("out is not a list")
    return bad


def setting_problems(s, sid: str | None = None) -> list[str]:
    if not isinstance(s, dict):
        return ["not a JSON object"]
    bad = []
    if sid and s.get("id") != sid:
        bad.append(f"id {s.get('id')!r}, want {sid!r}")
    for key in ("id", "label", "items", "return_spot"):
        if key not in s:
            bad.append(f"no {key}")
    items = s.get("items") or []
    ids = {i.get("id") for i in items}
    want = SETTING_ITEMS.get(s.get("id"))
    if want and ids != want:
        bad.append(f"items {sorted(ids)}, contract says {sorted(want)}")
    for i in items:
        if not isinstance(i.get("aliases"), list) or not isinstance(i.get("sharp"), bool) or not i.get("name"):
            bad.append(f"item {i.get('id')} needs name, aliases list, sharp bool")
    return bad


def _buffer_size() -> int:
    try:
        return LEDGER_BUFFER.stat().st_size
    except OSError:
        return 0


def _buffer_tail(start: int) -> str:
    try:
        with LEDGER_BUFFER.open("rb") as f:  # read only; the ledger owns this file
            f.seek(start)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def run_checks(url: str, vision_url: str | None = None, voice_url: str | None = None, local: bool = True,
               say=print) -> list[tuple[str, bool | None, str]]:
    from .smoke import one
    res: list[tuple[str, bool | None, str]] = []

    def rec(name, ok, detail=""):
        res.append((name, ok, detail))
        say(f"  {'PASS' if ok else 'SKIP' if ok is None else 'FAIL'}  {name:22} {detail}")

    c = httpx.Client(base_url=url, timeout=10)
    try:
        st = c.get("/state").json()
    except httpx.HTTPError as e:
        rec("controller /state", False, str(e))
        return res
    rec("controller /state", "step" in st, f"step {st.get('step')}, setting {st.get('setting')}, fake_arm {st.get('fake_arm')}")

    # dashboard pages served by the controller
    r = c.get("/")
    same = r.status_code == 200 and r.text == (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    rec("GET / = dashboard", same if local else (r.status_code == 200 and "app.js" in r.text),
        f"{r.status_code}" + ("" if same or not local else ", differs from dashboard/index.html (placeholder?)"))
    for path, kind in (("/app.js", "javascript"), ("/style.css", "css"), ("/tablet.html", "html"),
                       ("/tablet.js", "javascript"), ("/tablet.css", "css")):
        r = c.get(path)
        ok = r.status_code == 200 and kind in r.headers.get("content-type", "") and len(r.content) > 0
        if ok and local:
            ok = r.content == (ROOT / "dashboard" / path.lstrip("/")).read_bytes()
        rec(f"GET {path}", ok, f"{r.status_code} {r.headers.get('content-type', '')} {len(r.content)} B")
    for path in ("/demo", "/nurse"):
        r = c.get(path)
        rec(f"GET {path}", r.status_code == 200 and "<html" in r.text.lower()[:500], f"{r.status_code} {len(r.content)} B")

    # settings: surgical and bench load, then back to where it was
    original = st.get("setting") or "surgical"
    for sid in ("surgical", "bench"):
        r = _post_retry(c, "/setting", {"setting": sid}, 60)
        g = c.get("/setting").json() if r.status_code == 200 else None
        bad = [f"POST {r.status_code}"] if r.status_code != 200 else setting_problems(r.json(), sid) + setting_problems(g, sid)
        rec(f"setting {sid}", not bad, "; ".join(bad) or f"{g.get('label')}: {', '.join(i['id'] for i in g['items'])} ({g.get('_source', '')})")
    if original != "bench":
        _post_retry(c, "/setting", {"setting": original}, 60)

    # vision posts reach the controller
    v = c.get("/vision").json()
    tray_ok = v.get("tray") is not None and (v.get("tray_age_s") or 99) < 3
    rec("vision tray -> /vision", tray_ok, f"tray age {v.get('tray_age_s')}" if v.get("tray") else "no TrayState posted")
    sim = c.get("/sim/vision")
    if sim.status_code == 200 and not sim.json().get("on"):
        rec("vision hand -> /vision", None, "sim hand tracking is off (POST /sim/hand {\"on\": true})")
    else:
        hand_ok = v.get("hand") is not None and (v.get("hand_age_s") or 99) < 1
        rec("vision hand -> /vision", hand_ok, f"hand age {v.get('hand_age_s')}" if v.get("hand") else "no Hand posted")
    if vision_url:
        try:
            h = httpx.get(f"{vision_url}/health", timeout=5).json()
            s = httpx.get(f"{vision_url}/snapshot", timeout=5)
            rec("vision service", h.get("ok") is True and s.headers.get("content-type") == "image/jpeg",
                f"camera {h.get('camera')}, snapshot {s.headers.get('content-type')} {len(s.content)} B")
        except (httpx.HTTPError, ValueError) as e:
            rec("vision service", False, f"{vision_url}: {e}")
    else:  # the controller proxies its VISION_URL's /snapshot
        s = c.get("/camera/overhead")
        if s.status_code == 200:
            rec("vision service", s.headers.get("content-type") == "image/jpeg",
                f"via controller /camera/overhead: {s.headers.get('content-type')} {len(s.content)} B")
        else:
            rec("vision service", None, f"no vision process behind the controller (/camera/overhead {s.status_code})")

    # WS /events delivers (the dashboard and voice listen there)
    try:
        from websockets.sync.client import connect
        with connect(url.replace("http", "ws", 1) + "/events", open_timeout=5) as ws:
            c.post("/command", json={"action": "count", "source": "dashboard", "t": time.time()})
            end, got = time.time() + 5, None
            while time.time() < end and got is None:
                ev = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
                got = ev if ev.get("type") == "count" else None
        rec("WS /events", got is not None, f"count event: {got.get('say')!r}" if got else "no count event in 5 s")
    except Exception as e:  # noqa: BLE001
        rec("WS /events", False, f"{type(e).__name__}: {e}")

    # a fake handover reaches the ledger
    if not st.get("fake_arm"):
        rec("handover -> ledger", None, "real arm: not moving it from a check")
    else:
        wait_idle(c, 60)
        if c.post("/sim/scene_reset").status_code == 200:  # sim: the hemostat may be off the tray from earlier runs
            wait_idle(c, 60)
            time.sleep(1.5)  # a TrayState of the reset tray
        if c.get("/state").json().get("step") != "idle":
            c.post("/reset", json={"clear_count": False})
            wait_idle(c, 60)
        before = _buffer_size()
        cid_events = []
        ok, said, rth = one(c, "handover", "hemostat", False, 90)
        rec("fake handover", ok, f"{rth:.1f}s  {said}" if rth else said)
        cid = next((e.get("command_id") for e in reversed(c.get("/events/recent", params={"n": 60}).json())
                    if e.get("item") == "hemostat" and e.get("type") == "command"), None)
        end = time.time() + 5
        while time.time() < end and local:
            tail = _buffer_tail(before)
            cid_events = [ln for ln in tail.splitlines() if cid and cid in ln]
            if any('"released"' in ln or '"set_down"' in ln for ln in cid_events):
                break
            time.sleep(0.3)
        if cid_events:
            rec("events -> ledger buffer", True, f"{len(cid_events)} lines for command {cid[:8]} in ledger/buffer.jsonl")
        else:
            s = c.get("/stats").json()
            rec("events -> ledger", "hemostat" in (s.get("out") or []) and "source" not in s,
                "not in ledger/buffer.jsonl (Mongo up, or a remote stack); checked stats out instead: "
                f"{s.get('out')}")

    # GET /stats has the tables the dashboard paints
    s = c.get("/stats")
    bad = stats_problems(s.json()) if s.status_code == 200 else [f"{s.status_code}"]
    d = s.json() if s.status_code == 200 else {}
    rec("GET /stats shape", not bad, "; ".join(bad) or
        f"by_item {len(d['by_item'])} rows, by_lighting {len(d['by_lighting'])} rows, median {d.get('median_request_to_hand_s')}, out {d.get('out')}")

    if voice_url:
        try:
            h = httpx.get(f"{voice_url}/health", timeout=5).json()
            rec("voice /health", h.get("ok") is True and h.get("controller") is True, f"controller {h.get('controller')}")
        except (httpx.HTTPError, ValueError) as e:
            rec("voice /health", False, f"{voice_url}: {e}")
    c.close()
    return res


def cmd_check(a) -> int:
    stack = Stack(verbose=a.verbose)
    P = ports(a)
    signal.signal(signal.SIGTERM, _sigterm)
    try:
        if a.url:
            url = a.url.rstrip("/")
            local = "localhost" in url or "127.0.0.1" in url
            vision_url, voice_url = a.vision_url, a.voice_url
        else:
            ok, skipped = bring_up(a, stack)
            if not ok:
                return 1
            url, local = controller_url(a), True
            vision_url = a.vision_url or (None if a.vision == "none" or "vision" in skipped else f"http://localhost:{P['vision']}")
            voice_url = a.voice_url
            time.sleep(2.5)  # a couple of TrayState and Hand posts
        print(f"\ncheck {url}")
        res = run_checks(url, vision_url, voice_url, local)
        fails = [n for n, ok, _ in res if ok is False]
        print(f"\n{sum(1 for _, ok, _ in res if ok)} passed, {len(fails)} failed, "
              f"{sum(1 for _, ok, _ in res if ok is None)} skipped" + (f": {', '.join(fails)}" if fails else ""))
        return 1 if fails else 0
    except KeyboardInterrupt:
        return 1
    finally:
        stack.stop()


def main(argv: list[str] | None = None) -> int:
    a = parse(argv)
    return {"start": cmd_start, "reset": cmd_reset, "backup": cmd_backup, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
