"""Smart pick: choose the skill source per item from measured real-arm tries.

Pure ranking (wilson_lower, rank, choose) does no I/O. refresh() and load_rows() do I/O, so the controller
calls them off the event loop. Locator and ask_in_gripper are the small vision/network helpers.
CLI: python -m controller.picker --setting surgical [--rows rows.json] [--deployment]
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = Path(os.environ.get("SKILL_POLICY_FILE") or ROOT / "data" / "skill_policy.json")  # tests point it elsewhere
DEFAULT_ORDER = ("model", "taught_adjusted", "ik")
PICK_OK = ("picked", "handed", "set_down")
LIGHTING_MIN = 5  # rows a lighting group needs before it alone decides
MIN_TRIES = 10    # real tries a method needs on an item before its rate may move it from its default-order place

DETECT_URL = "https://api.perceptron.inc/v1/detect"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ---------- ranking ----------
def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for successes out of n. 0 with no tries."""
    if n <= 0:
        return 0.0
    p = successes / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, (centre - margin) / (1 + z2 / n))


def _is_real(row: dict) -> bool:
    """Only rows the controller tagged arm "real" (untagged rows are not trusted: tests once wrote fake_arm false
    rows from a fake arm), never a test row, a fake or a sim."""
    if row.get("test") or row.get("fake_arm") or row.get("sim"):
        return False
    return row.get("arm") == "real"


def outcomes(rows: list[dict]) -> list[dict]:
    """One outcome per pick command from raw ledger events (real arm only).

    One try per (command_id, skill_source): a retry with the next method makes the first method's miss its own failed try.
    success: a picked/handed/set_down event with that skill_source; failure: only missed events with a
    skill_source (a missed with no skill_source is "not on tray" or "no taught skill", not a try).
    Already-built outcomes ({"ok", "source"}) pass through.
    """
    out: list[dict] = []
    groups: dict = {}
    for r in rows:
        if not isinstance(r, dict) or not _is_real(r):
            continue
        if "ok" in r and "source" in r:
            out.append(r)
            continue
        src = r.get("skill_source")
        if not src or r.get("type") not in PICK_OK + ("missed",):
            continue
        key = (r.get("setting"), r.get("command_id") if r.get("command_id") is not None else ("row", id(r)), src)
        groups.setdefault(key, []).append(r)
    for (setting, _, _), evs in groups.items():
        evs.sort(key=lambda e: e.get("t") or 0)
        won = [e for e in evs if e["type"] in PICK_OK]
        last = (won or evs)[-1]
        rts = next((e["request_to_hand_s"] for e in evs
                    if e["type"] in ("handed", "set_down") and e.get("request_to_hand_s")), None)
        out.append({"setting": setting, "item": last.get("item"), "source": last["skill_source"], "ok": bool(won),
                    "lighting": last.get("lighting"), "rts": rts, "t": last.get("t"), "arm": "real"})
    return out


def _median(vals: list[float]) -> float | None:
    vals = sorted(vals)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _stats(group: list[dict], lighting: str | None) -> dict:
    if lighting:
        same = [o for o in group if o.get("lighting") == lighting]
        if len(same) >= LIGHTING_MIN:
            group = same
    ok = sum(1 for o in group if o["ok"])
    return {"n": len(group), "ok": ok, "lower": wilson_lower(ok, len(group)),
            "median_s": _median([o["rts"] for o in group if o["ok"] and o.get("rts")])}


def rank(rows: list[dict], item_id: str, methods, deployment: bool = True, *,
         lighting: str | None = None, setting: str | None = None, taught: bool = True) -> list[dict]:
    """Methods best first: [{"method","n","ok","lower","median_s"(,"prior")}].

    Lower Wilson bound desc, then median request-to-hand asc, then default order. "model" goes first when its lower
    bound is >= the best other. "model" is dropped without a deployment, "taught_adjusted" without a taught skill.
    Only methods with MIN_TRIES real tries are ranked by data, and only among the places such methods hold in the
    default order; a method with fewer keeps its default-order place.
    With no taught_adjusted tries, plain "taught" tries stand in as its prior (entry carries "prior": "taught").
    """
    outs = [o for o in outcomes(rows) if o.get("item") == item_id and (setting is None or o.get("setting") in (None, setting))]
    avail = [m for m in methods if (m != "model" or deployment) and (m != "taught_adjusted" or taught)]
    entries = []
    for m in avail:
        group = [o for o in outs if o["source"] == m]
        prior = None
        if m == "taught_adjusted" and not group:
            group = [o for o in outs if o["source"] == "taught"]
            prior = "taught" if group else None
        e = {"method": m, **_stats(group, lighting)}
        if prior:
            e["prior"] = prior
        entries.append(e)
    pos = {m: i for i, m in enumerate(DEFAULT_ORDER)}
    entries.sort(key=lambda e: (-round(e["lower"], 6), e["median_s"] if e["median_s"] is not None else math.inf,
                                pos.get(e["method"], 9)))
    for i, e in enumerate(entries):
        if e["method"] == "model":
            others = [x["lower"] for x in entries if x["method"] != "model"]
            if i and (not others or round(e["lower"], 6) >= round(max(others), 6)):
                entries.insert(0, entries.pop(i))
            break
    # Too few tries: back to its default-order place. Trusted methods fill the remaining places in data order.
    by_default = sorted(entries, key=lambda e: pos.get(e["method"], 9))
    trusted = iter([e for e in entries if e["n"] >= MIN_TRIES])
    return [e if e["n"] < MIN_TRIES else next(trusted) for e in by_default]


def _why(entries: list[dict]) -> str:
    if not entries:
        return "no method available"
    top = entries[0]
    if all(e["n"] == 0 for e in entries):
        return "no real tries yet: default order"

    def fmt(e, word="lower "):
        s = f"{e['method']} {e['ok']}/{e['n']} ({word}{e['lower']:.2f})"
        return s + " via taught prior" if e.get("prior") else s

    if top["n"] < MIN_TRIES:
        return f"{top['method']} {top['n']}/{MIN_TRIES} real tries, default order"
    if len(entries) == 1:
        return fmt(top)
    nxt = entries[1]
    if nxt["n"] == 0:
        return f"{fmt(top)}; {nxt['method']} untested"
    if nxt["n"] < MIN_TRIES:
        return f"{fmt(top)}; {nxt['method']} only {nxt['n']}/{MIN_TRIES} real tries"
    if round(top["lower"], 6) == round(nxt["lower"], 6):
        return f"{fmt(top)} ties {fmt(nxt, '')}, faster median"
    return f"{fmt(top)} beats {fmt(nxt, '')}"


def _choice(entries: list[dict]) -> dict:
    top = entries[0] if entries else None
    return {"method": top["method"] if top else "ik", "order": [e["method"] for e in entries],
            "confidence": round(top["lower"], 3) if top else 0.0, "why": _why(entries),
            "n": top["n"] if top else 0, "t": time.time()}


# ---------- policy ----------
class Policy:
    """data/skill_policy.json: {setting: {item: choice}}. Atomic writes; the directory is created on save."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else POLICY_FILE
        self.data: dict = {}

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}
        return self.data

    def get(self, setting_id: str, item_id: str) -> dict | None:
        return (self.data.get(setting_id) or {}).get(item_id)

    def put(self, setting_id: str, choices: dict) -> None:
        self.data[setting_id] = choices

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".skill_policy.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


_CACHE: dict = {}  # setting -> item -> choice; refresh() fills it, choose() only reads it
_lock = threading.Lock()


def choose(item_id: str, setting_id: str | None = None, *, deployment: bool = False, taught=True,
           cache: dict | None = None) -> dict:
    """The best method now. No I/O: reads the in-memory cache that refresh() (or load_cache) filled.

    Methods no longer available (no deployment, no taught skill) are dropped from the cached order.
    Nothing cached: default order, why "no real tries yet: default order".
    """
    cache = _CACHE if cache is None else cache
    with _lock:
        hit = None
        if setting_id is not None:
            hit = (cache.get(setting_id) or {}).get(item_id)
        else:
            for items in cache.values():
                if item_id in items:
                    hit = items[item_id]
                    break
        hit = dict(hit) if hit else None
    if hit:
        order = [m for m in hit.get("order", []) if (m != "model" or deployment) and (m != "taught_adjusted" or taught)]
        if order:
            if order[0] != hit.get("method"):
                hit["why"] = f"{hit.get('method')} unavailable now: {order[0]} instead"
                hit["confidence"] = 0.0
            hit.update(method=order[0], order=order)
            return hit
    order = [m for m in DEFAULT_ORDER if (m != "model" or deployment) and (m != "taught_adjusted" or taught)]
    return {"method": order[0], "order": order, "confidence": 0.0, "why": "no real tries yet: default order", "n": 0}


def load_cache(policy: Policy | None = None) -> None:
    """Fill the in-memory cache from data/skill_policy.json (startup)."""
    data = (policy or Policy()).load()
    with _lock:
        _CACHE.clear()
        _CACHE.update(data)


def refresh(setting_id: str, items, *, deployment: bool = False, taught=(), lighting: str | None = None,
            rows: list[dict] | None = None, policy: Policy | None = None, write: bool = True) -> dict:
    """Compute the choice for every item, update the cache, write the policy, return {item: choice}.

    items: item ids or setting item dicts. taught: set of item ids with a taught pick skill (or True for all).
    Does I/O (rows from load_rows() when not given, the policy file): call it off the event loop.
    """
    rows = load_rows() if rows is None else rows
    ids = [i["id"] if isinstance(i, dict) else i for i in items]
    outs = outcomes(rows)
    choices = {}
    for item_id in ids:
        has_taught = taught is True or item_id in (taught or ())
        entries = rank(outs, item_id, DEFAULT_ORDER, deployment, lighting=lighting, setting=setting_id, taught=has_taught)
        choices[item_id] = _choice(entries)
    with _lock:
        _CACHE[setting_id] = choices
    if write:
        pol = policy or Policy()
        pol.load()
        pol.put(setting_id, choices)
        try:
            pol.save()
        except OSError:
            pass  # a read-only disk must not stop a pick; the cache still holds the choice
    return choices


# ---------- rows ----------
def _mongo_rows() -> list[dict] | None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        return None
    try:
        import pymongo
    except ImportError:
        return None
    client = None
    try:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
        query = {"type": {"$in": list(PICK_OK) + ["missed"]}, "skill_source": {"$exists": True},
                 "arm": "real", "test": {"$ne": True}, "fake_arm": {"$ne": True}, "sim": {"$ne": True}}
        return [r for r in client["scrub"]["events"].find(query, {"_id": 0}) if _is_real(r)]
    except Exception:  # noqa: BLE001 - Atlas down or bad URI: fall back to the local ledger
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


def _local_rows() -> list[dict]:
    path = Path(os.environ.get("LEDGER_BUFFER") or ROOT / "ledger" / "buffer.jsonl")
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            doc = row.get("doc") if isinstance(row, dict) else None
            if isinstance(doc, dict) and row.get("kind") == "event" and _is_real(doc):
                out.append(doc)
    except OSError:
        pass
    return out


def load_rows() -> list[dict]:
    """Real-arm pick events: MongoDB scrub.events first, else ledger/buffer.jsonl, else []."""
    rows = _mongo_rows()
    return rows if rows is not None else _local_rows()


# ---------- vision helpers ----------
class Locator:
    """Client for the vision service /locate and /safe_zone. Any error (down, slow, bad JSON) returns None."""

    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base = (base_url or "").rstrip("/")
        self.client = client

    def _get(self, path: str, params: dict | None, timeout_s: float) -> dict | None:
        if not self.base:
            return None
        try:
            get = self.client.get if self.client is not None else httpx.get
            r = get(self.base + path, params=params, timeout=timeout_s)
            if r.status_code != 200:
                return None
            body = r.json()
            return body if isinstance(body, dict) else None
        except Exception:  # noqa: BLE001 - the pick goes on without a located pose
            return None

    def locate(self, item_id: str, timeout_s: float = 2.0, instance: dict | None = None) -> dict | None:
        return self._get("/locate", {"item": item_id, **(instance or {})}, timeout_s)

    def safe_zone(self, timeout_s: float = 2.0) -> dict | None:
        return self._get("/safe_zone", None, timeout_s)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def ask_in_gripper(jpeg: bytes, item_name: str, timeout_s: float = 3.0, *, client=None) -> bool | None:
    """Is the item in the gripper? Perceptron detect first, Gemini yes/no second. None with no key, no answer or timeout.

    timeout_s is the total budget. Keys come from PERCEPTRON_API_KEY and GEMINI_API_KEY and are never logged.
    """
    if not jpeg or not item_name:
        return None
    deadline = time.monotonic() + timeout_s
    http = client or httpx
    b64 = base64.b64encode(jpeg).decode("ascii")
    seen_false = False

    key = _env("PERCEPTRON_API_KEY")
    if key and deadline - time.monotonic() > 0.05:
        try:
            r = http.post(DETECT_URL, headers={"Authorization": f"Bearer {key}"}, timeout=deadline - time.monotonic(), json={
                "media": {"type": "image", "image_url": "data:image/jpeg;base64," + b64},
                "categories": [item_name], "config": {"output": "box", "reasoning_effort": "none"}})
            if r.status_code == 200 and not (r.json().get("error")):
                if r.json().get("detections"):
                    return True
                seen_false = True
        except Exception:  # noqa: BLE001 - timeout or bad answer: try Gemini
            pass

    key = _env("GEMINI_API_KEY")
    if key and deadline - time.monotonic() > 0.05:
        model = _env("GEMINI_MODEL") or "gemini-3.5-flash-lite"
        body = {"contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    {"text": f"The camera is on a robot gripper. Is a {item_name} held in the gripper? Answer in_gripper true or false."}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0,
                                     "responseSchema": {"type": "OBJECT", "properties": {"in_gripper": {"type": "BOOLEAN"}},
                                                        "required": ["in_gripper"]}}}
        try:
            r = http.post(GEMINI_URL.format(model=model), json=body, headers={"x-goog-api-key": key},
                          timeout=deadline - time.monotonic())
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                val = json.loads(text).get("in_gripper")
                if isinstance(val, bool):
                    return val
        except Exception:  # noqa: BLE001
            pass
    return False if seen_false else None


# ---------- CLI ----------
def _table(setting_id: str, ids: list[str], rows: list[dict], deployment: bool, taught, lighting) -> list[str]:
    outs = outcomes(rows)
    lines = [f"{'item':<16}{'method':<17}{'n':>4}{'ok':>4}{'lower':>7}{'median s':>10}  chosen"]
    for item_id in ids:
        has_taught = taught is True or item_id in (taught or ())
        entries = rank(outs, item_id, DEFAULT_ORDER, deployment, lighting=lighting, setting=setting_id, taught=has_taught)
        for i, e in enumerate(entries):
            med = f"{e['median_s']:.1f}" if e["median_s"] is not None else "-"
            lines.append(f"{item_id if i == 0 else '':<16}{e['method']:<17}{e['n']:>4}{e['ok']:>4}{e['lower']:>7.2f}{med:>10}"
                         f"  {'<-' if i == 0 else ''}")
    return lines


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m controller.picker", description=__doc__)
    ap.add_argument("--setting", default="surgical")
    ap.add_argument("--rows", help="JSON file of ledger events instead of MongoDB/ledger")
    ap.add_argument("--deployment", action="store_true", help="a Perceptron deployment exists (model is a candidate)")
    ap.add_argument("--lighting", help="bright, normal or dim")
    ap.add_argument("--policy", help="policy file (default data/skill_policy.json)")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    setting = json.loads((ROOT / "settings" / f"{args.setting}.json").read_text(encoding="utf-8"))
    ids = [i["id"] for i in setting.get("items", [])]
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8")) if args.rows else load_rows()
    print("\n".join(_table(args.setting, ids, rows, args.deployment, True, args.lighting)))
    refresh(args.setting, ids, deployment=args.deployment, taught=True, lighting=args.lighting, rows=rows,
            policy=Policy(args.policy) if args.policy else None, write=not args.no_write)
    if not args.no_write:
        print(f"wrote {args.policy or POLICY_FILE}")


if __name__ == "__main__":
    main()
