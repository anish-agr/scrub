"""The station speaks its updates again, with the recorder's lines and voice (arm_voice: ElevenLabs Sarah, Mac voice offline).

  .venv/bin/python explore/station_voice.py                     # watch http://localhost:8090
  .venv/bin/python explore/station_voice.py --station http://localhost:8090

The old recorder (arm_session) spoke through arm_ui.note(); the station has its own silent note(), so this
reads only GET /status and says what changed: recording and saved episodes, re-records, camera lost and back,
hot motors, cool-down, motors off, errors and AI runs. It never sends a command. SCRUB_VOICE=off silences it.
"""
import argparse
import time

import httpx

import arm_voice

TEMP_WARN = 55  # station.py TEMP_WARN


def nice(name: str) -> str:
    return name.replace("_flex", "").replace("_", " ")


def updates(prev: dict | None, cur: dict | None) -> list[tuple]:
    """(text, key, every) for each thing worth saying between two /status reads. key None: always say."""
    if cur is None:
        return []
    if prev is None:
        return [("I'm back.", "up", 20)]
    out = []
    was, now = prev.get("state"), cur.get("state")
    if now != was:
        if now == "recording":
            n = (cur.get("episodes_session") or 0) + 1
            out.append((f"Recording. Episode {n}.", None, 0))
        elif now == "idle" and was in ("parked", "off", "killed", "homing", "cooling"):
            out.append(("Ready. Move the leader arm and I'll follow.", "ready", 20))
        elif now == "killed":
            out.append(("Motors off.", "killed", 10))
        elif now == "error":
            out.append(("Something went wrong. Check the station.", "error", 30))
    if was == "recording" and now != "recording":
        if (cur.get("episodes_session") or 0) > (prev.get("episodes_session") or 0) or cur.get("saving"):
            out.append(("Saved. Reset the tray.", None, 0))
        elif now != "cooling":
            out.append(("Throwing that episode away.", "discard", 10))
    if len(cur.get("rerecord") or []) > len(prev.get("rerecord") or []):
        out.append(("Let's do that one again.", "rerecord", 10))
    pc, cc = prev.get("cameras") or {}, cur.get("cameras") or {}
    for k, c in cc.items():
        down, was_down = bool(c.get("down")), bool((pc.get(k) or {}).get("down"))
        if down and not was_down:
            out.append((f"I lost the {k} camera. Reconnecting.", "cam-down-" + k, 20))
        elif was_down and not down:
            out.append((f"{k.capitalize()} camera is back.", "cam-back-" + k, 20))
    if cur.get("cooling") and not prev.get("cooling"):
        out.append(("My motors are hot. I'm folding up to cool down.", "cool", 60))
    elif prev.get("cooling") and not cur.get("cooling"):
        out.append(("Cooled down. Press motors on to continue.", "cooled", 60))
    elif not cur.get("cooling"):
        for m, t in (cur.get("temps") or {}).items():
            old = (prev.get("temps") or {}).get(m)
            if isinstance(t, (int, float)) and t >= TEMP_WARN and not (isinstance(old, (int, float)) and old >= TEMP_WARN):
                out.append((f"My {nice(m)} is getting hot. Holding still to cool down.", "hot-" + m, 60))
    pr, cr = prev.get("run") or {}, cur.get("run") or {}
    if now == "running" and was != "running":
        out.append(("Picking it up." if cr.get("driver") == "autopick" else "Running.", None, 0))
    if cr.get("result") and cr.get("started") and (cr.get("started"), cr.get("result")) != (pr.get("started"), pr.get("result")):
        res = str(cr["result"])
        out.append(("Done." if res == "done" else "Stopped." if res.startswith(("stop", "abort")) else "That run failed.", None, 0))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--station", default="http://localhost:8090")
    a = p.parse_args()
    base = a.station.rstrip("/")
    print(f"voice: speaking station updates from {base}", flush=True)
    prev, first = None, True
    with httpx.Client(timeout=1.5) as c:
        while True:
            try:
                cur = c.get(f"{base}/status").json()
            except (httpx.HTTPError, ValueError):
                cur = None
            if first and cur is not None:
                prev, first = cur, False  # don't announce what was already true when we started
            for text, key, every in updates(prev, cur):
                print(f"say: {text}", flush=True)
                arm_voice.say(text, key=key, every=every)
            if cur is not None or prev is not None:
                prev = cur
            time.sleep(0.3)


if __name__ == "__main__":
    main()
