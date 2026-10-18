"""Run-mode driver: play back one recorded episode's actions on the follower.

The station calls start(st), then tick(st, obs) every loop (30 Hz) until it returns None, and abort() on
KILL / Home / cool-down / error. Actions go through the station's processors and the arm guards, so
max_relative_target and the joint/gripper guards still apply.

First it eases from where the arm is to the episode's first frame (at most APPROACH_DEG_S), then plays
the frames at `speed` (0.1 to 1.0 of the recorded rate). It only works when the object sits where it
sat in that demo.
"""
from __future__ import annotations

from pathlib import Path

APPROACH_DEG_S = 30.0
MIN_APPROACH_S = 1.5


def _parquets(root: Path, sub: str):
    for f in sorted((root / sub).glob("chunk-*/*.parquet")):
        yield f


def episodes(root) -> list[dict]:
    """[{episode, task, length}] for every episode whose meta is readable (the file LeRobot is still
    writing is skipped until the station closes and finalizes it)."""
    import pandas as pd
    root, out = Path(root).expanduser(), []
    for f in _parquets(root, "meta/episodes"):
        try:
            d = pd.read_parquet(f, columns=["episode_index", "tasks", "length"])
        except Exception:  # noqa: BLE001 - open or partial file
            continue
        for r in d.itertuples():
            tasks = list(r.tasks) if r.tasks is not None else []
            out.append({"episode": int(r.episode_index), "task": tasks[0] if tasks else "", "length": int(r.length)})
    return sorted(out, key=lambda e: e["episode"])


def load_actions(root, episode: int):
    """The episode's action rows (N x motors) from the dataset's data parquet files."""
    import numpy as np
    import pandas as pd
    for f in _parquets(Path(root).expanduser(), "data"):
        try:
            d = pd.read_parquet(f, columns=["episode_index", "frame_index", "action"])
        except Exception:  # noqa: BLE001
            continue
        d = d[d.episode_index == episode]
        if len(d):
            return np.stack(d.sort_values("frame_index").action.to_numpy()).astype(float)
    raise ValueError(f"episode {episode} not readable yet (still in the open file? restart the station)")


class Replay:
    name = "replay"

    def __init__(self, args: dict | None = None):
        args = args or {}
        if args.get("episode") in (None, ""):
            raise ValueError("replay: pick an episode")
        self.episode = int(args["episode"])
        self.speed = min(1.0, max(0.1, float(args.get("speed") or 0.5)))
        self.phase, self.i, self.t = "loading", 0.0, 0
        self.rows = None
        self.names: list[str] = []
        self.start_pose = None
        self.approach_n = 1
        self.aborted = False

    def start(self, st) -> None:
        import numpy as np
        self.names = list(st.ds.features["action"]["names"])
        self.rows = load_actions(st.root, self.episode)
        if self.rows.shape[1] != len(self.names):
            raise ValueError(f"episode {self.episode} has {self.rows.shape[1]} joints, the arm has {len(self.names)}")
        cur = {**{f"{k}.pos": v for k, v in st.joints.items()}, "gripper.pos": st.gripper}
        self.start_pose = np.array([float(cur.get(n) if cur.get(n) is not None else self.rows[0][j])
                                    for j, n in enumerate(self.names)])
        gap = float(np.max(np.abs(self.rows[0] - self.start_pose)))
        self.approach_n = max(1, int(st.fps * max(MIN_APPROACH_S, gap / APPROACH_DEG_S)))
        self.phase = "approach"

    def tick(self, st, obs) -> dict | None:
        if self.aborted:
            return None
        if self.phase == "approach":
            self.t += 1
            a = min(1.0, self.t / self.approach_n)
            a = a * a * (3 - 2 * a)                      # smoothstep: no jerk at either end
            row = self.start_pose + (self.rows[0] - self.start_pose) * a
            if self.t >= self.approach_n:
                self.phase = "play"
        else:
            if int(self.i) >= len(self.rows):
                self.phase = "done"
                return None
            row = self.rows[int(self.i)]
            self.i += self.speed
        return {n: float(v) for n, v in zip(self.names, row)}

    def abort(self) -> None:
        self.aborted = True

    def status(self) -> dict:
        n = len(self.rows) if self.rows is not None else 0
        if self.phase == "approach":
            prog, detail = 0.0, f"moving to the start of episode {self.episode}"
        else:
            prog = min(1.0, self.i / n) if n else 0.0
            detail = f"episode {self.episode} at {self.speed:g}x, frame {min(int(self.i), n)}/{n}"
        return {"phase": self.phase, "detail": detail, "progress": round(prog, 3)}
