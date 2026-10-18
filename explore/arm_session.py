"""Teleop or record on this Mac with the SO-101 pair, without the start-up jump.

  .venv/bin/python explore/arm_session.py                                   # teleop, no cameras
  .venv/bin/python explore/arm_session.py --side 1 --wrist 2                # teleop with both cameras
  .venv/bin/python explore/arm_session.py --side 1 --wrist 2 --task "pick the hemostat" --episodes 5

First eases the follower to the leader's pose over --ease-s seconds (torque stays on), so it doesn't
jump when LeRobot starts. Records into one local dataset (--root, appended to with --resume when it
exists), never pushes to the Hub. Ports and ids match the calibration in ~/.cache/huggingface/lerobot.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

FOLLOWER = "/dev/tty.usbmodem5C821089781"
LEADER = "/dev/tty.usbmodem5C821067211"
BIN = Path(sys.executable).parent


def ease(follower_port: str, leader_port: str, seconds: float) -> None:
    from lerobot.robots.so_follower import SOFollower
    from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SOLeader
    from lerobot.teleoperators.so_leader.config_so_leader import SO101LeaderConfig

    f = SOFollower(SO101FollowerConfig(port=follower_port, id="scrub_follower")).bus
    l = SOLeader(SO101LeaderConfig(port=leader_port, id="scrub_leader")).bus
    f.connect()
    l.connect()
    try:
        start, goal = f.sync_read("Present_Position"), l.sync_read("Present_Position")
        worst = max(abs(goal[m] - start[m]) for m in start)
        print(f"easing follower to the leader's pose (largest gap {worst:.0f}) over {seconds:.0f} s", flush=True)
        if not f.sync_read("Torque_Enable", normalize=False)["shoulder_lift"]:
            print("follower torque is off: skipping the ease (LeRobot will enable it)")
            return
        n = max(1, int(seconds * 30))
        for i in range(1, n + 1):
            s = i / n
            s = s * s * (3 - 2 * s)  # smooth start and stop
            f.sync_write("Goal_Position", {m: start[m] + (goal[m] - start[m]) * s for m in start})
            time.sleep(1 / 30)
    finally:
        f.disconnect(disable_torque=False)
        l.disconnect(disable_torque=False)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--side", type=int, help="side camera index (lerobot-find-cameras opencv)")
    p.add_argument("--wrist", type=int, help="wrist camera index")
    p.add_argument("--task", help='record this exact instruction, e.g. "pick the hemostat"; omit to teleop')
    p.add_argument("--episodes", type=int, default=5)
    p.add_argument("--episode-s", type=int, default=25)
    p.add_argument("--reset-s", type=int, default=10)
    p.add_argument("--root", default=str(Path.home() / "scrub-dataset"))
    p.add_argument("--repo", default="local/scrub", help="dataset name; only matters if pushed later")
    p.add_argument("--ease-s", type=float, default=3.0)
    p.add_argument("--follower", default=FOLLOWER)
    p.add_argument("--leader", default=LEADER)
    a = p.parse_args()

    # keep holding on exit: LeRobot's default drops torque and a raised arm falls
    robot = [f"--robot.type=so101_follower", f"--robot.port={a.follower}", "--robot.id=scrub_follower",
             "--robot.disable_torque_on_disconnect=false"]
    teleop = [f"--teleop.type=so101_leader", f"--teleop.port={a.leader}", "--teleop.id=scrub_leader"]
    cams = {k: v for k, v in (("side", a.side), ("wrist", a.wrist)) if v is not None}
    if cams:
        spec = ", ".join(f"{k}: {{type: opencv, index_or_path: {v}, width: 640, height: 480, fps: 30}}"
                         for k, v in cams.items())
        robot.append(f"--robot.cameras={{{spec}}}")
    if a.task:
        if len(cams) != 2:
            sys.exit("recording needs --side and --wrist")
        cmd = [str(BIN / "lerobot-record"), *robot, *teleop, f"--dataset.repo_id={a.repo}",
               f"--dataset.root={a.root}", f"--dataset.single_task={a.task}",
               f"--dataset.num_episodes={a.episodes}", "--dataset.fps=30",
               f"--dataset.episode_time_s={a.episode_s}", f"--dataset.reset_time_s={a.reset_s}",
               "--dataset.push_to_hub=false"]
        if (Path(a.root) / "meta" / "info.json").exists():
            cmd.append("--resume=true")
    else:
        cmd = [str(BIN / "lerobot-teleoperate"), *robot, *teleop, "--fps=30"]

    ease(a.follower, a.leader, a.ease_s)
    print(" ".join(cmd), flush=True)
    os.execv(cmd[0], cmd)


if __name__ == "__main__":
    main()
