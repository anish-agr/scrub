"""The arm talks: an ElevenLabs voice through this Mac's speaker, macOS `say` when offline.

  .venv/bin/python explore/arm_voice.py "Here's the hemostat. Ready to grab."   # say one line
  .venv/bin/python explore/arm_voice.py --controller http://localhost:8000       # speak every controller line
  .venv/bin/python explore/arm_voice.py --warm surgical                          # pre-cache a tray's lines

Each phrase is fetched once and cached in ~/scrub-logs/voice-cache, so repeats play instantly and
cost no credits. ELEVENLABS_API_KEY from .env; ELEVENLABS_VOICE_ID picks the voice (default Sarah).
SCRUB_VOICE=off silences it. The recorder (arm_session.py) uses say() for phases and warnings.
"""
import argparse
import hashlib
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV = {**dotenv_values(ROOT / ".env"), **os.environ}
KEY = ENV.get("ELEVENLABS_API_KEY")
VOICE = ENV.get("ELEVENLABS_VOICE_ID") or "EXAVITQu4vr4xnSDxMaL"  # Sarah: mature, reassuring, confident
MODEL = "eleven_flash_v2_5"  # lowest latency
CACHE = Path.home() / "scrub-logs" / "voice-cache"
ON = ENV.get("SCRUB_VOICE", "on") != "off"

_q: queue.Queue = queue.Queue()
_last: dict = {}
_worker = [None]


def _audio(text: str) -> Path | None:
    """Cached mp3 for this line, fetched from ElevenLabs on first use. None if it can't be had."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(f"{VOICE}|{MODEL}|{text}".encode()).hexdigest() + ".mp3")
    if path.exists():
        return path
    if not KEY:
        return None
    try:
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}",
                       headers={"xi-api-key": KEY, "accept": "audio/mpeg"},
                       json={"text": text, "model_id": MODEL,
                             "voice_settings": {"stability": 0.6, "similarity_boost": 0.8}},
                       timeout=6)
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"voice: ElevenLabs unavailable ({type(e).__name__}), using the Mac voice", flush=True)
        return None
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.rename(path)
    return path


def _play(text: str) -> None:
    path = _audio(text)
    if path:
        subprocess.run(["afplay", str(path)], check=False)
    else:
        subprocess.run(["say", "-v", "Samantha", text], check=False)


def _run() -> None:
    while True:
        text = _q.get()
        try:
            _play(text)
        except Exception as e:  # noqa: BLE001 - talking must never break the arm
            print(f"voice: {e}", flush=True)


def say(text: str, key: str | None = None, every: float = 0.0) -> None:
    """Speak in the background. With key, don't repeat that key within `every` seconds."""
    if not ON or not text:
        return
    now = time.time()
    if key and now - _last.get(key, 0) < every:
        return
    if key:
        _last[key] = now
    if _q.qsize() > 3:  # fall behind -> skip, never queue stale lines
        return
    if _worker[0] is None:
        _worker[0] = threading.Thread(target=_run, daemon=True)
        _worker[0].start()
    _q.put(text)


def warm(texts) -> int:
    """Fetch lines ahead of time so the first handover speaks without a network wait."""
    return sum(1 for t in texts if _audio(t))


def setting_lines(setting_id: str) -> list[str]:
    sys.path.insert(0, str(ROOT))
    from controller import lines, settings
    s = settings.load(setting_id)
    out = [lines.STOPPED, lines.RESET, lines.SHOW_HAND, lines.HAND_LOST, lines.PATH_BLOCKED, lines.NOTHING_OUT]
    for it in s["items"]:
        n = it["name"]
        out += [lines.coming(n), lines.sharp_down(n) if it.get("sharp") else lines.handed(n),
                lines.retry(n), lines.returned(n)]
    return [t for t in out if t]


def follow_controller(url: str) -> None:
    """Speak each controller event's `say` (the same lines the phone voice speaks)."""
    seen = time.time()
    print(f"voice: speaking controller lines from {url}", flush=True)
    while True:
        try:
            evs = httpx.get(f"{url}/events/recent", params={"n": 20}, timeout=2).json()
            for ev in evs:
                if ev.get("t", 0) > seen and ev.get("say"):
                    say(ev["say"])
            if evs:
                seen = max(seen, max(e.get("t", 0) for e in evs))
        except (httpx.HTTPError, ValueError):
            time.sleep(1)  # controller not up yet
        time.sleep(0.15)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("text", nargs="*")
    p.add_argument("--controller", help="speak every line from this controller, e.g. http://localhost:8000")
    p.add_argument("--warm", metavar="SETTING", help="pre-cache the lines for surgical, dental or bench")
    a = p.parse_args()
    if a.warm:
        lines_ = setting_lines(a.warm)
        print(f"cached {warm(lines_)} of {len(lines_)} lines for {a.warm}")
    if a.controller:
        follow_controller(a.controller.rstrip("/"))
    if a.text:
        _play(" ".join(a.text))  # in the foreground: returns when it has been said


if __name__ == "__main__":
    main()
