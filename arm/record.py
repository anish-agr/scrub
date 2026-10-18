"""Record one batch of demos into the one Scrub dataset, then log it in docs/DATA-LOG.md.

  python -m arm.record --setting surgical --item hemostat --direction hand-out --lighting bright --episodes 5
  python -m arm.record --task "return the hemostat" --lighting dim --episodes 5
  python -m arm.record --task "pick the hemostat" --lighting normal --print-only     # no hardware
  python -m arm.record --lerobot --follower COM5 --leader COM6 --side 0 --wrist 1 --task "pick the hex key" --lighting normal

Fixed for every batch: use_degrees=true, 30 fps, 25 s episodes, 10 s reset, one repo
<HF_USER>/scrub (HF_USER from --hf-user, the HF_USER env var, or the HF token's account) and one
root (~/scrub-dataset). A root that already holds a dataset is appended to with --resume=true.
The task must be an exact pick_instruction or return_instruction from settings/surgical.json or
settings/bench.json (dental is not recorded).

Backends:
- default: explore/arm_session.py, the recorder that works on the Mac (supervisor, cameras by
  name, ease-in, gripper and joint guards, per-episode cadence report <root>-cadence.json).
- --lerobot: the plain `lerobot-record` command from docs/BRINGUP.md section 6 (Windows laptop).

After the batch, one row goes to docs/DATA-LOG.md in the `python -m ledger log` format, with the
number of episodes actually saved (read from <root>/meta/info.json).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARM_SESSION = ROOT / "explore" / "arm_session.py"
SETTINGS_DIR = ROOT / "settings"
DATA_LOG = ROOT / "docs" / "DATA-LOG.md"
RECORDED_SETTINGS = ("surgical", "bench")  # demo scope; dental is hidden and not recorded
FPS, EPISODE_S, RESET_S = 30, 25, 10
LIGHTS = ("bright", "normal", "dim")
DIRECTIONS = {"hand-out": "pick_instruction", "put-back": "return_instruction"}
WIN = sys.platform.startswith("win")


# ---------- task strings ----------

def instructions(settings_dir: Path = SETTINGS_DIR, settings=RECORDED_SETTINGS) -> list[dict]:
    """Every recordable instruction: {task, setting, item, direction}."""
    out = []
    for sid in settings:
        data = json.loads((settings_dir / f"{sid}.json").read_text(encoding="utf-8"))
        for item in data.get("items") or []:
            for direction, key in DIRECTIONS.items():
                if item.get(key):
                    out.append({"task": item[key], "setting": data["id"], "item": item["id"], "direction": direction})
    return out


def resolve_task(task=None, setting=None, item=None, direction=None, settings_dir: Path = SETTINGS_DIR) -> dict:
    """The exact instruction string and its setting/item/direction. Raises SystemExit if not exact."""
    if setting is not None and setting not in RECORDED_SETTINGS:
        raise SystemExit(f"setting {setting!r} is not recorded; use one of {', '.join(RECORDED_SETTINGS)}")
    pool = instructions(settings_dir, (setting,) if setting else RECORDED_SETTINGS)
    if task is not None:
        hits = [x for x in pool if x["task"] == task]
        if not hits:
            near = [x["task"] for x in pool if x["task"].lower() == task.strip().lower()]
            hint = f" Did you mean {near[0]!r}?" if near else ""
            raise SystemExit(f"{task!r} is not an exact instruction in settings.{hint} Valid: "
                             + "; ".join(x["task"] for x in pool))
        if item is not None and hits[0]["item"] != item or direction is not None and hits[0]["direction"] != direction:
            raise SystemExit(f"--task {task!r} disagrees with --item/--direction")
        return hits[0]
    if not (setting and item and direction):
        raise SystemExit("give --task \"pick the hemostat\", or --setting, --item and --direction")
    if direction not in DIRECTIONS:
        raise SystemExit("direction must be hand-out or put-back")
    want = item.replace("-", " ").replace("_", " ").strip().lower()
    data = json.loads((settings_dir / f"{setting}.json").read_text(encoding="utf-8"))
    for it in data.get("items") or []:
        names = [it.get("id", ""), it.get("name", ""), *(it.get("aliases") or [])]
        if want in [n.replace("-", " ").replace("_", " ").strip().lower() for n in names]:
            hit = [x for x in pool if x["item"] == it["id"] and x["direction"] == direction]
            if hit:
                return hit[0]
    raise SystemExit(f"{item!r} is not in settings/{setting}.json. Items: "
                     + ", ".join(it["id"] for it in data.get("items") or []))


# ---------- repo and root ----------

def load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def hf_user(flag: str | None = None, whoami=None) -> str | None:
    """--hf-user, else HF_USER, else the account of HF_TOKEN (never printed)."""
    if flag:
        return flag
    if os.environ.get("HF_USER"):
        return os.environ["HF_USER"]
    try:
        if whoami is None:
            from huggingface_hub import whoami
        token = os.environ.get("HF_TOKEN") or None
        return whoami(token=token).get("name")
    except Exception:  # noqa: BLE001 - offline, no token, or no huggingface_hub
        return None


def dataset_state(root: Path) -> str:
    """"new" (no folder), "resume" (a dataset), or "bad" (a folder that is not a dataset)."""
    if (root / "meta" / "info.json").exists():
        return "resume"
    return "bad" if root.exists() else "new"


def episode_count(root: Path) -> int:
    try:
        return int(json.loads((root / "meta" / "info.json").read_text())["total_episodes"])
    except Exception:  # noqa: BLE001 - no dataset yet
        return 0


def cadence_note(root: Path, first_index: int) -> str:
    """'loop 29.8-30.0 Hz' for episodes recorded in this batch, from arm_session's cadence report."""
    try:
        eps = json.loads(Path(f"{root}-cadence.json").read_text())["episodes"]
        fps = [e["measured_fps"] for e in eps if e.get("episode_index", -1) >= first_index]
    except Exception:  # noqa: BLE001 - no report (the --lerobot backend writes none)
        return ""
    return f"loop {min(fps):g}-{max(fps):g} Hz" if fps else ""


# ---------- commands ----------

def use_degrees_default() -> bool | None:
    """LeRobot's SO-101 follower and leader default for use_degrees, None if LeRobot is missing."""
    try:
        import dataclasses
        from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
        from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig
        vals = [f.default for c in (SO101FollowerConfig, SO101LeaderConfig)
                for f in dataclasses.fields(c) if f.name == "use_degrees"]
        return bool(vals) and all(v is True for v in vals)
    except Exception:  # noqa: BLE001
        return None


def arm_session_cmd(a, task: str, repo: str, python: str = sys.executable) -> list[str]:
    """explore/arm_session.py with our settings. It always records at 30 fps and appends
    --resume=true itself when <root>/meta/info.json exists."""
    cmd = [python, str(ARM_SESSION), "--side", a.side, "--wrist", a.wrist, "--task", task,
           "--episodes", str(a.episodes), "--episode-s", str(a.episode_s), "--reset-s", str(a.reset_s),
           "--root", str(a.root), "--repo", repo]
    for flag, val in (("--follower", a.follower), ("--leader", a.leader), ("--ease-s", a.ease_s)):
        if val is not None:
            cmd += [flag, str(val)]
    if a.no_ui:
        cmd.append("--no-ui")
    return cmd


def lerobot_cmd(a, task: str, repo: str, side_index, wrist_index, resume: bool) -> list[str]:
    """The lerobot-record command from docs/BRINGUP.md section 6."""
    cams = (f"{{side: {{type: opencv, index_or_path: {side_index}, width: 640, height: 480, fps: {FPS}}}, "
            f"wrist: {{type: opencv, index_or_path: {wrist_index}, width: 640, height: 480, fps: {FPS}}}}}")
    cmd = ["lerobot-record", "--robot.type=so101_follower", f"--robot.port={a.follower}",
           "--robot.id=scrub_follower", "--robot.use_degrees=true", f"--robot.cameras={cams}",
           "--teleop.type=so101_leader", f"--teleop.port={a.leader}", "--teleop.id=scrub_leader",
           "--teleop.use_degrees=true",
           f"--dataset.repo_id={repo}", f"--dataset.root={a.root}", f"--dataset.single_task={task}",
           f"--dataset.num_episodes={a.episodes}", f"--dataset.fps={FPS}",
           f"--dataset.episode_time_s={a.episode_s}", f"--dataset.reset_time_s={a.reset_s}",
           f"--dataset.push_to_hub={'true' if a.push else 'false'}"]
    if resume:
        cmd.append("--resume=true")
    return cmd


def show(cmd: list[str]) -> str:
    if WIN:
        # PowerShell: quote anything with spaces, braces or commas
        return " ".join(f'"{x}"' if any(c in x for c in ' {},;') else x for x in cmd)
    return shlex.join(cmd)


def camera_index(spec: str):
    """OpenCV index for --lerobot: digits as given, a name part through arm.check_setup."""
    if str(spec).isdigit():
        return int(spec)
    from arm.check_setup import camera_names, resolve_camera
    idx, why = resolve_camera(spec, camera_names())
    if idx is None:
        raise SystemExit(f"camera {spec!r}: {why}. Run python -m arm.check_setup")
    return idx


# ---------- DATA-LOG ----------

def log_row(info: dict, lighting: str, demos: int, dataset: str, notes: str, path: Path = DATA_LOG,
            when: str | None = None) -> str:
    """Append one row exactly as `python -m ledger log` writes it."""
    try:
        from ledger.logbook import log_batch
        return log_batch(setting=info["setting"], item=info["item"], direction=info["direction"],
                         lighting=lighting, demos=demos, dataset=dataset, notes=notes, when=when,
                         path=path, repo=SETTINGS_DIR.parent)
    except ImportError:
        pass
    data = json.loads((SETTINGS_DIR / f"{info['setting']}.json").read_text(encoding="utf-8"))
    item = next(it for it in data["items"] if it["id"] == info["item"])
    cells = [when or datetime.now().strftime("%Y-%m-%d %H:%M"), data.get("label") or data["id"],
             item.get("name") or item["id"], info["direction"], lighting, str(int(demos)), dataset or "local", notes]
    row = "| " + " | ".join(str(c).replace("|", "/").replace("\n", " ").strip() for c in cells) + " |"
    header = "| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |"
    text = path.read_text(encoding="utf-8") if path.exists() else "# Data log\n\n"
    if header not in text:
        text = text.rstrip() + "\n\n" + header + "\n| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + row + "\n", encoding="utf-8")
    return row


# ---------- main ----------

def parse(argv=None):
    p = argparse.ArgumentParser(prog="python -m arm.record", description="Record one batch into <HF_USER>/scrub and log it in docs/DATA-LOG.md")
    p.add_argument("--task", help='exact instruction, e.g. "pick the hemostat"')
    p.add_argument("--setting", choices=RECORDED_SETTINGS)
    p.add_argument("--item", help="item id or name, e.g. hemostat, kelly, hex_key")
    p.add_argument("--direction", choices=tuple(DIRECTIONS))
    p.add_argument("--lighting", required=True, choices=LIGHTS)
    p.add_argument("--episodes", type=int, default=5, help="episodes to add in this batch")
    p.add_argument("--episode-s", type=int, default=EPISODE_S)
    p.add_argument("--reset-s", type=int, default=RESET_S)
    p.add_argument("--hf-user", help="Hugging Face user for the repo <HF_USER>/scrub")
    p.add_argument("--root", type=Path, default=Path.home() / "scrub-dataset")
    p.add_argument("--side", help='side camera: name part or OpenCV index (default "C920" on macOS, 0 elsewhere)')
    p.add_argument("--wrist", help='wrist camera: name part or OpenCV index (default "icspring" on macOS, 1 elsewhere)')
    p.add_argument("--follower", default=os.environ.get("SCRUB_FOLLOWER_PORT") or None, help="follower port")
    p.add_argument("--leader", default=os.environ.get("SCRUB_LEADER_PORT") or None, help="leader port")
    p.add_argument("--lerobot", action="store_true", help="run plain lerobot-record instead of explore/arm_session.py")
    p.add_argument("--push", action="store_true", help="--lerobot only: push to the Hub (publishes the data)")
    p.add_argument("--ease-s", type=float, help="arm_session: seconds to ease the follower to the leader")
    p.add_argument("--no-ui", action="store_true", help="arm_session: no recorder page")
    p.add_argument("--notes", default="", help="DATA-LOG notes")
    p.add_argument("--log", type=Path, default=DATA_LOG, help="DATA-LOG file (default docs/DATA-LOG.md)")
    p.add_argument("--no-log", action="store_true", help="do not append to the DATA-LOG")
    p.add_argument("--print-only", action="store_true", help="print the config and command, touch nothing")
    a = p.parse_args(argv)
    if a.episodes < 1:
        p.error("--episodes must be at least 1")
    mac = sys.platform == "darwin"
    a.side = a.side or os.environ.get("SCRUB_SIDE_CAMERA") or ("C920" if mac else "0")
    a.wrist = a.wrist or os.environ.get("SCRUB_WRIST_CAMERA") or ("icspring" if mac else "1")
    if a.lerobot:
        a.follower = a.follower or os.environ.get("SO101_PORT") or None
    a.root = a.root.expanduser()
    return a


def plan(a, whoami=None) -> dict:
    info = resolve_task(a.task, a.setting, a.item, a.direction)
    user = hf_user(a.hf_user, whoami)
    repo = f"{user}/scrub" if user else "<HF_USER>/scrub"
    state = dataset_state(a.root)
    resume = state == "resume"
    if a.lerobot:
        side = a.side if a.print_only and not str(a.side).isdigit() else camera_index(a.side)
        wrist = a.wrist if a.print_only and not str(a.wrist).isdigit() else camera_index(a.wrist)
        cmd = lerobot_cmd(a, info["task"], repo, side, wrist, resume)
        backend = "lerobot-record"
    else:
        cmd = arm_session_cmd(a, info["task"], repo)
        backend = "explore/arm_session.py"
    return {"info": info, "user": user, "repo": repo, "state": state, "resume": resume, "cmd": cmd,
            "backend": backend, "before": episode_count(a.root)}


def describe(a, pl: dict) -> None:
    i = pl["info"]
    deg = use_degrees_default()
    deg_txt = ("passed as --robot.use_degrees=true --teleop.use_degrees=true" if a.lerobot else
               "LeRobot default " + {True: "true", False: "FALSE", None: "unknown (LeRobot not importable)"}[deg]
               + " (arm_session has no flag for it)")
    print(f"task        {i['task']!r}  ({i['setting']} / {i['item']} / {i['direction']}, {a.lighting} light)")
    print(f"repo        {pl['repo']}" + ("" if pl["user"] else "  (set HF_USER, --hf-user, or HF_TOKEN in .env)"))
    print(f"root        {a.root}  ({pl['state']}: "
          + {"new": "will be created", "resume": f"{pl['before']} episodes, --resume=true",
             "bad": "exists but has no meta/info.json"}[pl["state"]] + ")")
    print(f"episodes    {a.episodes} more, {a.episode_s} s each, {a.reset_s} s reset, {FPS} fps")
    print(f"use_degrees {deg_txt}")
    print(f"cameras     side={a.side} wrist={a.wrist} at 640x480 at {FPS} fps")
    print(f"backend     {pl['backend']}" + ("" if a.lerobot else
                                            f"  (follower {a.follower or 'arm_session default'}, "
                                            f"leader {a.leader or 'arm_session default'})"))
    if a.lerobot:
        print(f"push        {'to the Hub' if a.push else 'no (local only)'}")
    print(f"data log    {'off' if a.no_log else a.log}")
    print()
    print(show(pl["cmd"]))


def busy_ports(a, holders=None) -> dict:
    """{port: [pid, ...]} for the follower and leader ports some other process has open."""
    from arm.backends import port_holders
    from arm.check_setup import known_ports
    holders = holders or port_holders
    ports = [p for p in (a.follower, a.leader) if p] or list(known_ports())
    return {p: pids for p in ports if (pids := holders(p))}


def main(argv=None) -> int:
    load_env()
    a = parse(argv)
    pl = plan(a)
    describe(a, pl)
    if a.print_only:
        return 0
    if not pl["user"]:
        raise SystemExit("no Hugging Face user: set HF_USER or pass --hf-user (one repo <HF_USER>/scrub)")
    if pl["state"] == "bad":
        raise SystemExit(f"{a.root} exists but is not a LeRobot dataset; move it aside or pass another --root")
    if a.lerobot and not (a.follower and a.leader):
        raise SystemExit("--lerobot needs --follower and --leader (see python -m arm.check_setup)")
    if not a.lerobot and use_degrees_default() is False:
        raise SystemExit("this LeRobot defaults to use_degrees=false and arm_session cannot set it: use --lerobot")
    busy = busy_ports(a)
    if busy:  # two programs on one motor bus fight; the controller may be holding a raised arm
        raise SystemExit("arm port in use: " + "; ".join(f"{p} (pid {', '.join(map(str, pids))})" for p, pids in busy.items())
                         + ". Stop the controller (--real-arm), teleop or arm.teach first")
    cmd = list(pl["cmd"])
    if a.lerobot and not shutil.which("lerobot-record"):
        cmd[0:1] = [sys.executable, "-m", "lerobot.scripts.lerobot_record"]
    before = pl["before"]
    print(f"\nrecording {a.episodes} episodes; n ends an episode, r re-records, q finishes\n", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(ROOT))
    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        rc = proc.wait()
    saved = episode_count(a.root) - before
    print(f"\n{saved} episode(s) saved this batch ({episode_count(a.root)} in {a.root}), exit {rc}")
    if a.no_log or saved < 1:
        if saved < 1:
            print("nothing saved: no DATA-LOG row")
        return rc
    dataset = pl["repo"] if a.lerobot and a.push else "local"
    notes = "; ".join(x for x in (cadence_note(a.root, before), a.notes) if x)
    row = log_row(pl["info"], a.lighting, saved, dataset, notes, a.log)
    print(row)
    print(f"appended to {a.log}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
