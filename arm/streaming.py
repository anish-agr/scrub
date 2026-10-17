"""Deterministic 30 Hz chunk timeline, independent of hardware and HTTP."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

HZ = 30
STRIDE = 15
DELAY = 12


@dataclass
class Chunk:
    chunk_id: str
    start: int
    execute_from: int
    actions: np.ndarray

    def row(self, tick):
        index = tick - self.start
        if self.execute_from <= index < len(self.actions):
            return self.actions[index]
        return None


class Timeline:
    def __init__(self, kinematics):
        self.kin = kinematics
        self.chunks = []
        self.committed = {}
        self.limits = np.r_[self.kin.joint_speed_deg_s, self.kin.rig["max_gripper_speed_per_s"]] / HZ

    def clear(self):
        self.chunks.clear()
        self.committed.clear()

    def active(self, tick):
        for chunk in reversed(self.chunks):
            if chunk.row(tick) is not None:
                return chunk
        return None

    def desired(self, tick, hold):
        chunk = self.active(tick)
        return chunk.row(tick) if chunk else np.asarray(hold)

    def command(self, tick, previous, hold):
        # Committed rows take precedence even if a new reply arrives early.
        if tick in self.committed:
            return self.committed[tick].copy()
        desired = self.desired(tick, hold)
        delta = np.clip(desired - previous, -self.limits, self.limits)
        initial_point = self.kin.forward(previous[:5])
        while np.linalg.norm(self.kin.forward((previous + delta)[:5]) - initial_point) > self.kin.rig["max_cartesian_speed_m_s"] / HZ:
            delta *= .5
        return np.asarray(previous) + delta

    def rtc(self, tick, previous, hold):
        prior = self.active(tick)
        if prior is None:
            return None
        # Pin precisely what playback will execute, including rate limiting or
        # holds, instead of claiming unmodified model rows were executed.
        rows = [np.asarray(previous).copy()]
        self.committed[tick] = rows[0]
        for future in range(tick + 1, tick + DELAY):
            row = self.command(future, rows[-1], hold)
            self.committed[future] = row.copy()
            rows.append(row)
        return {"prior_chunk_id": prior.chunk_id,
                "prior_start_index": tick - prior.start, "delay": DELAY,
                "committed_actions": np.asarray(rows).tolist()}

    def accept(self, reply, capture_tick, arrival_seconds, capture_seconds, sequence, rtc):
        if arrival_seconds >= capture_seconds + DELAY / HZ:
            return False
        if reply.get("sequence") != sequence or not isinstance(reply.get("chunk_id"), str):
            raise ValueError("Chunk identity/sequence mismatch")
        actions = np.asarray(reply.get("actions"), dtype=float)
        index = reply.get("execute_from_index")
        if actions.shape != (30, 6) or not np.isfinite(actions).all():
            raise ValueError("Expected 30 finite six-value absolute joint targets")
        if type(index) is not int or not 0 <= index < 30:
            raise ValueError("Invalid execution prefix")
        if rtc is not None:
            if not reply.get("rtc_applied") or reply.get("prefix_length") != DELAY or index != DELAY:
                raise ValueError("RTC response does not honor committed prefix")
            if not np.allclose(actions[:DELAY], rtc["committed_actions"], atol=1e-4):
                raise ValueError("RTC reply changed committed actions")
        elif index != 0:
            raise ValueError("First chunk must begin at row zero")
        if not all(self.kin.valid(row[:5]) and 0 <= row[5] <= 100 for row in actions):
            raise ValueError("Policy target exceeds configured joint limits")
        self.chunks = [c for c in self.chunks if c.start + len(c.actions) > capture_tick]
        self.chunks.append(Chunk(reply["chunk_id"], capture_tick, index, actions))
        self.committed = {t: row for t, row in self.committed.items() if t >= capture_tick}
        return True
