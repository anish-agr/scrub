"""Full runs against a live controller, for Checkpoint 1 (C5) and the ten-in-a-row check (C8).

  .venv/bin/python -m controller.smoke                     # one run, simulated pull (fake or sim arm)
  .venv/bin/python -m controller.smoke --runs 10 --human   # real arm: a person takes each item
  .venv/bin/python -m controller.smoke --url http://localhost:8000 --items hemostat,scalpel --return

A run hands over every item in the current setting (or --items), then asks for the count.
With --return it also returns each non-sharp item (a person sets it in the return spot first).
A run is clean if every handover ends in `released` or `set_down` with no `missed` or `error`.
"""
import argparse
import time
import uuid

import httpx

def events_for(c: httpx.Client, cid: str) -> list[dict]:
    return [e for e in c.get("/events/recent", params={"n": 200}).json() if e.get("command_id") == cid]


def one(c: httpx.Client, action: str, item: str | None, human: bool, timeout: float) -> tuple[bool, str, float | None]:
    cid = uuid.uuid4().hex
    r = c.post("/command", json={"id": cid, "action": action, "item": item, "source": "keyboard",
                                 "t": time.time()}).json()
    if not r["accepted"]:
        return False, f"rejected: {r['reason']}", None
    want = {"returned"} if action == "return" else {"released", "set_down"}
    end, pulled = time.time() + timeout, False
    while time.time() < end:
        step = c.get("/state").json()["step"]
        started = any(e["type"] != "command" for e in events_for(c, cid))
        if started and step in ("idle", "stopped", "error"):
            break
        if step == "waiting_for_pull" and not human and not pulled:
            c.post("/fake/pull")
            pulled = True
        time.sleep(0.2)
    evs = events_for(c, cid)
    kinds = [e["type"] for e in evs]
    rth = next((e["request_to_hand_s"] for e in evs if e.get("request_to_hand_s")), None)
    ok = any(k in want for k in kinds) and not any(k in ("missed", "error", "stopped") for k in kinds)
    says = [e["say"] for e in evs if e.get("say")]
    return ok, " / ".join(says) or ",".join(k for k in kinds if k != "step"), rth


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m controller.smoke")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--items", help="comma-separated item ids (default: every item in the setting)")
    p.add_argument("--human", action="store_true", help="a person takes each item; no simulated pull")
    p.add_argument("--return", dest="ret", action="store_true", help="also return each non-sharp item")
    p.add_argument("--timeout", type=float, default=90.0)
    a = p.parse_args()

    c = httpx.Client(base_url=a.url, timeout=5)
    setting = c.get("/setting").json()
    items = a.items.split(",") if a.items else [i["id"] for i in setting["items"]]
    sharp = {i["id"] for i in setting["items"] if i.get("sharp")}
    print(f"{a.url}  setting {setting['id']}  items {items}  state {c.get('/state').json()['step']}")
    streak, best, times = 0, 0, []
    for run in range(1, a.runs + 1):
        clean = True
        for item in items:
            ok, said, rth = one(c, "handover", item, a.human, a.timeout)
            clean &= ok
            if rth:
                times.append(rth)
            print(f"  run {run}  {'ok  ' if ok else 'FAIL'}  handover {item:20} {f'{rth:5.1f}s' if rth else '      '}  {said}")
        if a.ret:
            for item in [i for i in items if i not in sharp]:
                if a.human:
                    input(f"  put the {item} in the return spot, then press Enter")
                ok, said, _ = one(c, "return", item, a.human, a.timeout)
                clean &= ok
                print(f"  run {run}  {'ok  ' if ok else 'FAIL'}  return   {item:20}         {said}")
        count = c.post("/command", json={"action": "count", "source": "keyboard"}).json()
        print(f"  run {run}  count: {count['say']}")
        streak = streak + 1 if clean else 0
        best = max(best, streak)
        print(f"run {run}: {'CLEAN' if clean else 'NOT CLEAN'}  (streak {streak})")
        if a.human and run < a.runs:
            input("reset the tray, then press Enter for the next run")
    med = sorted(times)[len(times) // 2] if times else None
    print(f"\n{best} clean in a row (of {a.runs})" + (f", median request-to-hand {med:.1f}s" if med else ""))
    raise SystemExit(0 if best == a.runs else 1)


if __name__ == "__main__":
    main()
