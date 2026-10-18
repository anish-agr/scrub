"""One-command check of every Scrub service, key, log and hardware hint.
Run: .venv/bin/python -m controller.doctor [--no-ai] [--json]
Reads .env for key PRESENCE only. Never opens serial ports or cameras. Exit 0 if the controller is up, else 1."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_S = 2.0
LOG_DIR = Path.home() / "scrub-logs"
DEFAULT_MODEL = "gemini-3.5-flash-lite"  # same default as voice/src/config.ts

# What goes dark when a name is missing, from the comments in .env.example.
FEATURE = {
    "PERCEPTRON_TEAM_API_KEY": "Robotics API: datasets, training, deployments",
    "PERCEPTRON_API_KEY": "Perceptron vision calls",
    "PERCEPTRON_DEPLOYMENT_ID": "--real-arm (no model to run)",
    "GEMINI_API_KEY": "voice parsing falls back to alias match; spoken texts and summaries fall back to fixed lines",
    "GEMINI_MODEL": "default model id",
    "GEMINI_TIMEOUT_MS": "default 1500 ms",
    "ELEVENLABS_API_KEY": "arm speaking in the room, ElevenLabs agent",
    "ELEVENLABS_AGENT_ID": "ElevenLabs phone/voice agent",
    "VOICE_LLM_SECRET": "no shared-secret check on voice /v1/chat/completions",
    "PHOTON_API_KEY": "end-of-case text message",
    "PHOTON_PROJECT_ID": "end-of-case text message",
    "PHOTON_SUMMARY_TO": "summary text when the call has no caller id",
    "SCRUB_PUBLIC_URL": "case replay link after the summary text",
    "MONGODB_URI": "ledger writes only to ledger/buffer.jsonl, public page has no shared data",
    "HF_TOKEN": "LeRobot dataset upload and download",
    "SO101_PORT": "--real-arm cannot find the arm",
    "SO101_ROBOT_ID": "default scrub_follower",
    "SO101_SIDE_CAMERA": "default camera 0",
    "SO101_WRIST_CAMERA": "default camera 1",
    "PULL_LOAD_DELTA": "default 80",
    "GRIPPER_CLOSED": "default 0.95",
    "CAMERA_INDEX": "vision default camera 0",
    "CLINICIAN": "no saved hand height",
}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
OPTIONAL = {"VOICE_LLM_SECRET", "PHOTON_SUMMARY_TO"}  # .env.example: empty is allowed
SECRET = re.compile(r"(AIza[\w-]{20,}|sk-[\w-]{16,}|hf_[A-Za-z0-9]{16,}|mongodb(\+srv)?://\S+|Bearer\s+\S+|\+\d{10,}|\b[A-Za-z0-9_-]{32,}\b)")


def scrub(text: str) -> str:
    return SECRET.sub("[redacted]", ANSI.sub("", text))


def read_env_file(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"\s*([A-Z][A-Z0-9_]*)=(.*)", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("\"'")
    except OSError:
        pass
    return out


def env_names(example: Path) -> list:
    """[(name, optional)]: a commented `# NAME=` line is optional."""
    names, seen = [], set()
    try:
        lines = example.read_text().splitlines()
    except OSError:
        return []
    for line in lines:
        m = re.match(r"(#\s*)?([A-Z][A-Z0-9_]*)=", line)
        if m and m.group(2) not in seen:
            seen.add(m.group(2))
            names.append((m.group(2), bool(m.group(1)) or m.group(2) in OPTIONAL))
    return names


def check_keys(env: dict, example: Path) -> list:
    rows = []
    for name, optional in env_names(example):
        have = bool(env.get(name) or os.environ.get(name))
        rows.append({"name": name, "set": have, "optional": optional,
                     "disables": None if have else FEATURE.get(name, "see .env.example")})
    return rows


def probe(client: httpx.Client, name: str, url: str, path: str, detail) -> dict:
    t = time.monotonic()
    try:
        r = client.get(url.rstrip("/") + path, timeout=TIMEOUT_S)
        ms = round((time.monotonic() - t) * 1000)
        if r.status_code >= 400:
            return {"service": name, "url": url, "up": False, "ms": ms, "detail": f"HTTP {r.status_code}"}
        try:
            d = detail(r)
        except Exception:  # noqa: BLE001 - detail is best effort
            d = ""
        return {"service": name, "url": url, "up": True, "ms": ms, "detail": d}
    except httpx.HTTPError as e:
        return {"service": name, "url": url, "up": False, "ms": None, "detail": type(e).__name__}


def _controller(r):
    j = r.json()
    bits = [f"step {j.get('step')}", f"setting {j.get('setting')}"]
    if j.get("fake_arm"):
        bits.append("fake arm")
    if j.get("sim"):
        bits.append("sim arm")
    return ", ".join(bits)


def _vision(client, base):
    def f(r):
        j = r.json()
        d = "camera ok" if j.get("camera") else "no camera"
        try:
            t = client.get(base.rstrip("/") + "/vision/tray", timeout=TIMEOUT_S).json()
            d += ", tray stale" if t.get("stale") else ", tray fresh"
        except (httpx.HTTPError, ValueError):
            pass
        return d
    return f


def _recorder(r):
    j = r.json()
    return f"phase {j.get('phase')}" + (f", episode {j['episode']}" if j.get("episode") is not None else "")


def check_services(client: httpx.Client, env: dict) -> list:
    g = lambda k, d: env.get(k) or os.environ.get(k) or d  # noqa: E731
    ctl, vis = g("CONTROLLER_URL", "http://localhost:8000"), g("VISION_URL", "http://localhost:8001")
    host = "http://localhost"
    return [
        probe(client, "controller", ctl, "/state", _controller),
        probe(client, "vision", vis, "/health", _vision(client, vis)),
        probe(client, "voice", f"{host}:{g('VOICE_PORT', '3000')}", "/health",
              lambda r: "gemini key on" if r.json().get("keys", {}).get("gemini") else "gemini key off"),
        probe(client, "ledger", g("LEDGER_URL", f"{host}:8080"), "/api/stats",
              lambda r: f"out {len(r.json().get('out') or [])}"),
        probe(client, "sim", g("SIM_URL", f"{host}:8002"), "/state", lambda r: "up"),
        probe(client, "recorder", g("RECORDER_URL", f"{host}:8090"), "/status", _recorder),
        probe(client, "thermal_web", g("THERMAL_URL", f"{host}:8093"), "/", lambda r: "up"),
    ]


def newest(directory: Path, pattern: str, n: int = 1) -> list:
    try:
        return sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[:n]
    except OSError:
        return []


def tail(path: Path, n: int = 5) -> list:
    try:
        return [scrub(x)[:200] for x in path.read_text(errors="replace").splitlines()[-n:]]
    except OSError:
        return []


def check_logs(log_dir: Path, client: httpx.Client, controller_url: str) -> dict:
    files = []
    for pattern in ("arm-*.log", "*.log", "last-error.txt"):
        for p in newest(log_dir, pattern, 2 if pattern != "last-error.txt" else 1):
            if p not in [f[0] for f in files]:
                files.append((p, tail(p)))
    thermal = [(p, tail(p, 2)) for p in newest(log_dir / "thermal", "*", 1)]
    errors = []
    try:
        ev = client.get(controller_url.rstrip("/") + "/events/recent", params={"n": 200}, timeout=TIMEOUT_S).json()
        errors = [{"t": e.get("t"), "item": e.get("item"), "say": scrub(str(e.get("say") or e.get("step") or ""))}
                  for e in ev if e.get("type") == "error"][-5:]
    except (httpx.HTTPError, ValueError):
        pass
    return {"files": [{"path": str(p), "age_s": round(time.time() - p.stat().st_mtime), "tail": t} for p, t in files + thermal],
            "error_events": errors}


def run(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check_hardware(env: dict) -> dict:
    port = env.get("SO101_PORT") or os.environ.get("SO101_PORT") or ""
    out = {"so101_port": port or None, "port_exists": bool(port) and Path(port).exists(), "owners": [], "cameras": []}
    ps = run(["ps", "-axo", "pid=,command="]).splitlines()
    out["owners"] = [l.split(None, 1)[0] for l in ps if re.search(r"explore/arm_session|lerobot", l)
                     and "doctor" not in l and l.split(None, 1)[0] != str(os.getpid())]
    out["cameras"] = [c.strip() for c in re.findall(r"^\s{4}(.+):\s*$", run(["system_profiler", "SPCameraDataType"]), re.M)]
    return out


def findings(report: dict) -> list:
    f = []
    for s in report["services"]:
        if not s["up"]:
            f.append(f"{s['service']} down at {s['url']} ({s['detail']})")
    f += [f"{k['name']} missing: {k['disables']}" for k in report["keys"] if not k["set"] and not k["optional"]]
    hw = report["hardware"]
    if hw["so101_port"] and not hw["port_exists"]:
        f.append("SO101_PORT is set but the device path does not exist (arm unplugged or unpowered)")
    elif hw["port_exists"] and hw["owners"]:
        f.append("recorder or lerobot process owns the arm port; the controller cannot open it")
    for e in report["logs"]["error_events"]:
        f.append(f"controller error event: {e['say']} (item {e['item']})")
    for fl in report["logs"]["files"][:3]:
        bad = [x for x in fl["tail"] if re.search(r"error|traceback|exception|fail|too hot", x, re.I)]
        if bad:
            f.append(f"{Path(fl['path']).name}: {bad[-1]}")
    return [scrub(x) for x in f]


def ask_gemini(client: httpx.Client, key: str, model: str, items: list):
    """Plain-language fix list from findings text only. Returns text or None."""
    prompt = ("You help run a robot arm demo (controller, vision, voice, ledger, recorder). Below are findings from a "
              "health check. Reply with at most 8 short plain lines: what is wrong and what to do. No markdown, no "
              "preamble.\n\n" + "\n".join(items))
    try:
        r = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        headers={"x-goog-api-key": key},
                        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0}},
                        timeout=15.0)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return "\n".join(text.splitlines()[:8])
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None


def build_report(client, env, log_dir, example) -> dict:
    services = check_services(client, env)
    ctl_url = env.get("CONTROLLER_URL") or os.environ.get("CONTROLLER_URL") or "http://localhost:8000"
    rep = {"services": services, "keys": check_keys(env, example),
           "logs": check_logs(log_dir, client, ctl_url), "hardware": check_hardware(env)}
    rep["findings"] = findings(rep)
    rep["controller_up"] = services[0]["up"]
    return rep


def print_report(rep: dict, advice) -> None:
    print(f"{'service':<12}{'state':<6}{'latency':<9}detail")
    for s in rep["services"]:
        ms = f"{s['ms']} ms" if s["ms"] is not None else "-"
        print(f"{s['service']:<12}{'up' if s['up'] else 'DOWN':<6}{ms:<9}{s['detail']}")
    print("\nkeys (names only)")
    for k in rep["keys"]:
        if k["set"]:
            print(f"  set      {k['name']}")
        else:
            print(f"  {'optional' if k['optional'] else 'MISSING '} {k['name']}: {k['disables']}")
    hw = rep["hardware"]
    print("\nhardware")
    print(f"  SO101_PORT {hw['so101_port'] or '(unset)'}: {'exists' if hw['port_exists'] else 'not found'}"
          f"{', processes ' + ','.join(hw['owners']) if hw['owners'] else ''}")
    print(f"  cameras: {', '.join(hw['cameras']) or 'none listed'}")
    print("\nlogs")
    for f in rep["logs"]["files"]:
        print(f"  {f['path']} ({f['age_s']} s old)")
        for line in f["tail"][-2:]:
            print(f"      {line}")
    for e in rep["logs"]["error_events"]:
        print(f"  controller error event: {e['say']}")
    print("\nwhat to do")
    if advice:
        print(advice)
    else:
        print("\n".join(rep["findings"]) or "nothing wrong found")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-ai", action="store_true", help="skip Gemini")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    env = read_env_file(ROOT / ".env")
    with httpx.Client() as client:
        rep = build_report(client, env, LOG_DIR, ROOT / ".env.example")
        advice, note = None, None
        key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if args.no_ai:
            pass
        elif not key:
            note = "GEMINI_API_KEY missing: showing raw findings"
        elif rep["findings"]:
            model = env.get("GEMINI_MODEL") or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
            advice = ask_gemini(client, key, model, rep["findings"])
            if advice is None:
                note = "Gemini call failed: showing raw findings"
    rep["advice"], rep["ai_note"] = advice, note
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep, advice)
        if note:
            print(f"({note})")
    return 0 if rep["controller_up"] else 1


if __name__ == "__main__":
    sys.exit(main())
