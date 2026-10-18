"""Teleop or record on this Mac with the SO-101 pair, without the start-up jump.

  .venv/bin/python explore/arm_session.py                                   # teleop, no cameras
  .venv/bin/python explore/arm_session.py --side 1 --wrist 2                # teleop with both cameras
  .venv/bin/python explore/arm_session.py --side 1 --wrist 2 --task "pick the hemostat" --episodes 5

First eases the follower to the leader's pose over --ease-s seconds (torque stays on), so it doesn't
jump when LeRobot starts. Gripper guard: if the claw is told to close but stops moving for
GRIP_STALL_S (something is in the jaws), it holds at the contact point plus a small squeeze instead
of pushing into overload, until the leader opens past that point. The dataset still records the
leader's action (LeRobot's default). Records into one local dataset (--root, appended to with --resume when it
exists), never pushes to the Hub. Ports and ids match the calibration in ~/.cache/huggingface/lerobot.
"""
import argparse
import sys
import time
from pathlib import Path

FOLLOWER = "/dev/tty.usbmodem5C821089781"
LEADER = "/dev/tty.usbmodem5C821067211"
GRIP_STALL_S = 0.3   # closing but not moving this long: something is in the jaws
GRIP_MOVE = 1.0      # gripper units (0 closed .. 100 open) that count as still moving
GRIP_SQUEEZE = 3.0   # how far past the contact point to keep pressing, for a firm grip


def guard_gripper() -> None:
    """Patch SOFollower.send_action so a blocked claw times out to a gentle hold."""
    from lerobot.robots.so_follower.so_follower import SOFollower
    send = SOFollower.send_action
    st = {"hold": None, "ref": None, "since": 0.0}

    def guarded(self, action):
        goal = action.get("gripper.pos")
        if goal is None:
            return send(self, action)
        pos = self.bus.read("Present_Position", "gripper")
        now = time.perf_counter()
        if st["hold"] is not None:
            if goal >= st["hold"] + GRIP_SQUEEZE:  # leader opened past the contact point: let go
                st["hold"], st["ref"] = None, None
                print("gripper guard: released", flush=True)
            else:
                action = {**action, "gripper.pos": max(goal, st["hold"])}
        elif goal < pos - GRIP_SQUEEZE:  # told to close further than it is
            if st["ref"] is None or abs(pos - st["ref"]) > GRIP_MOVE:
                st["ref"], st["since"] = pos, now  # still closing
            elif now - st["since"] > GRIP_STALL_S:
                st["hold"] = max(0.0, pos - GRIP_SQUEEZE)
                action = {**action, "gripper.pos": st["hold"]}
                print(f"gripper guard: blocked at {pos:.0f}, holding at {st['hold']:.0f}", flush=True)
        else:
            st["ref"] = None
        return send(self, action)

    SOFollower.send_action = guarded


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
        # The leader's wrist reaches past the follower's calibrated range. A target past a limit
        # sets the motor's angle error for a few seconds, and LeRobot's start-up ping then
        # counts that motor as missing. Keep every target 1 degree inside the follower's range.
        for m, c in f.calibration.items():
            if m == "gripper":
                goal[m] = min(99.0, max(1.0, goal[m]))
                continue
            mid = (c.range_min + c.range_max) / 2
            lo, hi = ((r - mid) * 360 / 4095 for r in (c.range_min, c.range_max))
            goal[m] = min(hi - 1, max(lo + 1, goal[m]))
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
        end = time.time() + 3  # let every motor finish and settle before LeRobot pings them
        while time.time() < end and any(f.sync_read("Moving", normalize=False).values()):
            time.sleep(0.05)
        time.sleep(0.5)
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
        cmd = ["lerobot-record", *robot, *teleop, f"--dataset.repo_id={a.repo}",
               f"--dataset.root={a.root}", f"--dataset.single_task={a.task}",
               f"--dataset.num_episodes={a.episodes}", "--dataset.fps=30",
               f"--dataset.episode_time_s={a.episode_s}", f"--dataset.reset_time_s={a.reset_s}",
               "--dataset.push_to_hub=false"]
        if (Path(a.root) / "meta" / "info.json").exists():
            cmd.append("--resume=true")
    else:
        cmd = ["lerobot-teleoperate", *robot, *teleop, "--fps=30"]

    ease(a.follower, a.leader, a.ease_s)
    print(" ".join(cmd), flush=True)
    guard_gripper()
    if a.task:
        from lerobot.scripts.lerobot_record import main as run
    else:
        from lerobot.scripts.lerobot_teleoperate import main as run
    sys.argv = cmd  # same arguments as the CLI, run in this process so the guard applies
    run()


if __name__ == "__main__":
    main()
