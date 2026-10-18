"""Arm thermal telemetry: every row to a local JSONL file, and to MongoDB when MONGODB_URI is set.

The recorder (arm_session.py) logs a sample twice a second while it drives the arm: per motor
temperature, load, position, goal, current and voltage, plus guard state and loop rate. It also
logs events (cool-down, holds, overload, exits) and, while cooling, the temperatures every 10 s.
Uploads run on a background thread, so a slow network never slows the 30 Hz loop; rows that
did not reach MongoDB stay in the local file and `upload` sends them later (no duplicates).

  .venv/bin/python explore/thermal_log.py snapshot   # every heat-related register on both arms (port must be free)
  .venv/bin/python explore/thermal_log.py watch      # live view of the latest temperatures, from MongoDB
  .venv/bin/python explore/thermal_log.py upload     # send local rows MongoDB hasn't got yet
  .venv/bin/python explore/thermal_log.py idle 30    # log temperatures every 30 s while nothing uses the arm

MongoDB: database from the URI (default "scrub"), collection "thermal". Schema: explore/research/overheating/README.md.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = Path.home() / "scrub-logs" / "thermal"
COLLECTION = "thermal"
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
PORTS = {"follower": "/dev/tty.usbmodem5C821089781", "leader": "/dev/tty.usbmodem5C821067211"}
# STS3215 registers worth a snapshot: (address, bytes)
REGISTERS = {
    "firmware_major": (0, 1), "firmware_minor": (1, 1), "model": (3, 2), "max_temperature_limit": (13, 1),
    "max_voltage_limit": (14, 1), "min_voltage_limit": (15, 1), "max_torque_limit": (16, 2), "p_coefficient": (21, 1),
    "d_coefficient": (22, 1), "i_coefficient": (23, 1), "cw_dead_zone": (26, 1), "ccw_dead_zone": (27, 1),
    "protection_current": (28, 2), "protection_time": (35, 1), "overload_torque": (36, 1),
    "over_current_protection_time": (38, 1), "torque_enable": (40, 1), "acceleration": (41, 1),
    "goal_velocity": (46, 2), "torque_limit": (48, 2), "present_position": (56, 2), "present_load": (60, 2),
    "present_voltage": (62, 1), "present_temperature": (63, 1), "status": (65, 1), "present_current": (69, 2),
}


def _uri():
    try:
        from dotenv import dotenv_values
        return dotenv_values(ROOT / ".env").get("MONGODB_URI") or os.environ.get("MONGODB_URI")
    except Exception:  # noqa: BLE001
        return os.environ.get("MONGODB_URI")


def _collection():
    import pymongo
    client = pymongo.MongoClient(_uri(), serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    coll = client.get_default_database(default="scrub")[COLLECTION]
    coll.create_index([("session", 1), ("seq", 1)], unique=True)
    coll.create_index([("t", -1)])
    return coll


class ThermalLog:
    def __init__(self, meta: dict | None = None):
        DIR.mkdir(parents=True, exist_ok=True)
        self.session = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.path = DIR / f"{self.session}.jsonl"
        self.host = socket.gethostname()
        self.seq = 0
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue(maxsize=50000)
        self.mongo = bool(_uri())
        if self.mongo:
            threading.Thread(target=self._uploader, daemon=True).start()
        self.write({"kind": "session", **(meta or {})})

    def write(self, row: dict) -> None:
        with self.lock:
            self.seq += 1
            row = {"t": time.time(), **row, "session": self.session, "seq": self.seq, "host": self.host}
            with self.path.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        if self.mongo:
            try:
                self.q.put_nowait(row)
            except queue.Full:
                pass  # still in the local file; `upload` sends it later

    def _uploader(self) -> None:
        coll, backoff = None, 5
        while True:
            batch = [self.q.get()]
            time.sleep(2)
            while not self.q.empty() and len(batch) < 1000:
                batch.append(self.q.get_nowait())
            while True:
                try:
                    coll = coll or _collection()
                    _insert(coll, batch)
                    backoff = 5
                    break
                except Exception:  # noqa: BLE001 - offline: retry; the local file keeps everything
                    coll = None
                    time.sleep(backoff)
                    backoff = min(120, backoff * 2)


def _insert(coll, rows: list) -> int:
    import pymongo
    try:
        return len(coll.insert_many([dict(r) for r in rows], ordered=False).inserted_ids)
    except pymongo.errors.BulkWriteError as e:  # duplicates from a re-upload are fine
        return e.details.get("nInserted", 0)


_LOG: ThermalLog | None = None


def get(meta: dict | None = None) -> ThermalLog:
    global _LOG
    if _LOG is None:
        _LOG = ThermalLog(meta)
    return _LOG


def read_registers(port: str) -> dict:
    import scservo_sdk as scs
    ph = scs.PortHandler(port)
    if not ph.openPort():
        raise RuntimeError(f"can't open {port} (in use?)")
    ph.setBaudRate(1_000_000)
    pk = scs.PacketHandler(0)
    out = {}
    try:
        for i, name in enumerate(NAMES, 1):
            r = {}
            for k, (addr, n) in REGISTERS.items():
                v, comm, _ = (pk.read1ByteTxRx if n == 1 else pk.read2ByteTxRx)(ph, i, addr)
                r[k] = v if comm == scs.COMM_SUCCESS else None
            out[name] = r
    finally:
        ph.closePort()
    return out


def snapshot() -> None:
    log = get({"source": "snapshot"})
    for arm, port in PORTS.items():
        regs = read_registers(port)
        log.write({"kind": "snapshot", "arm": arm, "motors": regs})
        print(f"\n{arm}")
        keys = ["max_temperature_limit", "max_torque_limit", "torque_limit", "p_coefficient", "protection_current",
                "overload_torque", "acceleration", "goal_velocity", "torque_enable", "present_voltage",
                "present_temperature", "present_current"]
        print(f"{'motor':14s}" + "".join(f"{k.replace('present_', '')[:10]:>11s}" for k in keys))
        for m, r in regs.items():
            print(f"{m:14s}" + "".join(f"{str(r[k]):>11s}" for k in keys))
    time.sleep(4 if log.mongo else 0)  # let the uploader send it
    print(f"\nsaved to {log.path}" + (" and MongoDB" if log.mongo else " (no MONGODB_URI: local only)"))


def upload() -> None:
    coll = _collection()
    total = 0
    for path in sorted(DIR.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        for i in range(0, len(rows), 1000):
            total += _insert(coll, rows[i:i + 1000])
    print(f"uploaded {total} new rows from {DIR}")


def watch() -> None:
    coll = _collection()
    print("latest arm temperatures from MongoDB (Ctrl-C to stop)")
    while True:
        row = coll.find_one({"kind": {"$in": ["sample", "cooling", "idle"]}}, sort=[("t", -1)])
        if row:
            age = time.time() - row["t"]
            temps = row.get("temps") or {m: v.get("temp") for m, v in (row.get("motors") or {}).items()}
            line = "  ".join(f"{str(k)[:8]}:{v}C" for k, v in temps.items())
            hot = max([v for v in temps.values() if isinstance(v, (int, float))] or [0])
            flag = " HOT" if hot >= 55 else ""
            print(f"{time.strftime('%H:%M:%S')}  {row['kind']:8s} {row.get('phase') or '':10s} {line}  "
                  f"({age:.0f} s ago, {row['host']}){flag}", flush=True)
        time.sleep(5)


def idle(every: float = 30.0) -> None:
    log = get({"source": "idle-monitor"})
    print(f"logging follower temperatures every {every:.0f} s while the port is free (Ctrl-C to stop)")
    while True:
        try:
            regs = read_registers(PORTS["follower"])
            temps = {m: r["present_temperature"] for m, r in regs.items()}
            log.write({"kind": "idle", "temps": temps,
                       "torque": {m: r["torque_enable"] for m, r in regs.items()},
                       "voltage": {m: r["present_voltage"] for m, r in regs.items()}})
            print(time.strftime("%H:%M:%S"), temps, flush=True)
        except Exception as e:  # noqa: BLE001 - the recorder owns the port: it logs instead
            print(time.strftime("%H:%M:%S"), f"skipped ({e})", flush=True)
        time.sleep(every)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    {"snapshot": snapshot, "upload": upload, "watch": watch,
     "idle": lambda: idle(float(sys.argv[2]) if len(sys.argv) > 2 else 30.0)}[cmd]()
