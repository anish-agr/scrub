"""Teleop or record on this Mac with the SO-101 pair, without the start-up jump.

  .venv/bin/python explore/arm_session.py                                   # teleop, no cameras
  .venv/bin/python explore/arm_session.py --side C920 --wrist icspring      # teleop with both cameras
  .venv/bin/python explore/arm_session.py --side C920 --wrist icspring --task "pick the hemostat" --episodes 5

Cameras are picked by name (OpenCV's numbers change when a camera is replugged).

Keeps going through disconnects: a supervisor runs each session as a child process and waits for
missing arms/cameras (the page says what it is waiting for). If a session dies from a disconnect it
restarts when the devices are back; a recording resumes the same dataset (only the episode in
progress is lost). Teleop runs without an unplugged camera; recording waits for both. A camera
that stops mid-session is reconnected by name while teleop keeps running, and any episode recorded
while it is down is discarded and re-recorded.

  .venv/bin/python explore/arm_session.py --check           # no hardware: is ~/scrub-dataset ready to train?

Team watch API: http://<this Mac's IP>:8090/status (JSON), /api lists the endpoints. Buttons work
only on this Mac (or with header X-Scrub-Token: $SCRUB_UI_TOKEN). Drill: SCRUB_DROP_CAMERA=8 closes
the wrist camera 8 s into a session.

Opens a live recorder page at http://localhost:8090 (cameras, phase and countdown, joints, claw guard,
warnings, Next / Re-record / Stop buttons that work like the arrow keys, and a saved setup photo
to ghost over the side camera so the tray goes back in the same place).

First eases the follower to the leader's pose over --ease-s seconds (torque stays on), so it doesn't
jump when LeRobot starts. Gripper guard: if the claw is told to close but stops moving for
GRIP_STALL_S (something is in the jaws), it holds at the contact point plus a small squeeze instead
of pushing into overload, until the leader opens past that point. The dataset still records the
leader's action (LeRobot's default). Records into one local dataset (--root, appended to with --resume when it
exists), never pushes to the Hub. Each saved episode's wall-clock loop rate and camera fps go to
<root>-cadence.json, the --cadence-report that `python -m arm.train pipeline` checks. Ports and ids match the calibration in ~/.cache/huggingface/lerobot.
"""
import argparse
import faulthandler
import json
import os
import sys
import threading
import time
from pathlib import Path

FOLLOWER = "/dev/tty.usbmodem5C821089781"
LEADER = "/dev/tty.usbmodem5C821067211"
CAM_STALL_MS = 2000  # LeRobot stops the whole session if a camera frame is over 500 ms old;
                     # we accept up to this, then mark the camera down and keep reconnecting
GRIP_STALL_S = 0.3   # closing but not moving this long: something is in the jaws
GRIP_MOVE = 1.0      # gripper units (0 closed .. 100 open) that count as still moving
GRIP_SQUEEZE = 1.5   # how far past the contact point to keep pressing. 3.0 kept the claw stalled
                     # against LeRobot's 50% current limit until it tripped overload (Oct 17 crash)
GRIP_LOAD_MAX = 300  # raw |Present_Load| (LeRobot caps the gripper near 500): above this the claw is straining
GRIP_LOAD_S = 1.0    # straining this long eases the claw open a unit per loop, before overload trips
GRIP_TEMP_WARN = 55  # deg C: warn on the page
GRIP_TEMP_EASE = 62  # deg C: open the claw until it cools (STS3215 shuts itself off near 70)
GRIP_BACKOFF = 4.0   # on an overload reply, open this much per loop until the servo stops reporting it


DROP_TARGET = [None, False]  # camera index for the SCRUB_DROP_CAMERA drill, done flag
LAST_ERROR = Path.home() / "scrub-logs" / "last-error.txt"  # a crashed session's reason, for the page
CAM_SPECS: dict = {}         # starting OpenCV index -> (role, name spec), to find a camera again after a replug


def tolerate_camera_stalls() -> None:
    """A camera problem never ends the session.

    - frame up to CAM_STALL_MS old: use it, count a stall (the page says to re-record)
    - older: the camera is marked down; a background thread keeps reopening it every 2 s
    - while down: reads return the last good frame (black if none), teleop keeps working, and in a
      recording any episode is thrown away and re-recorded (arm_ui.camera_down), so no bad data is saved
    """
    import numpy as np
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    read_latest, disconnect = OpenCVCamera.read_latest, OpenCVCamera.disconnect

    def ui(fn, *args):
        try:
            import arm_ui
            getattr(arm_ui, fn)(*args)
        except ImportError:
            pass

    def placeholder(cam):
        last = getattr(cam, "_scrub_last", None)
        if last is not None:
            return last
        c = cam.config
        return np.zeros((c.height or 480, c.width or 640, 3), dtype=np.uint8)

    def reconnect_loop(cam):
        role, spec = getattr(cam, "_scrub_spec", (None, None))
        while getattr(cam, "_scrub_down", False):
            time.sleep(2)
            if spec and not spec.isdigit():  # its index can change when it is plugged back in
                idx = find_camera(spec)
                if idx is None:
                    print(f"{role} camera ({spec}) not plugged in", flush=True)
                    continue
                if idx != cam.config.index_or_path:
                    cam.config.index_or_path = cam.index_or_path = idx
                    ui("map_camera", idx, role)
            try:
                try:
                    disconnect(cam)
                except Exception:  # noqa: BLE001 - already closed
                    pass
                cam.connect(warmup=True)
                read_latest(cam, CAM_STALL_MS)
            except Exception as e:  # noqa: BLE001 - still gone, try again
                print(f"camera {cam.config.index_or_path} still down: {type(e).__name__}", flush=True)
                continue
            cam._scrub_down = False
            print(f"camera {cam.config.index_or_path} back", flush=True)
            ui("camera_down", cam.config.index_or_path, False)

    def tolerant(self, max_age_ms: int = 500):
        if not hasattr(self, "_scrub_spec"):
            self._scrub_spec = CAM_SPECS.get(self.config.index_or_path, (None, None))
        if getattr(self, "_scrub_down", False):
            ui("camera_down", self.config.index_or_path, True)  # keeps discarding episodes while down
            return placeholder(self)
        try:
            frame = read_latest(self, max_age_ms)
        except Exception:  # noqa: BLE001 - stale frame, read error or a vanished device
            try:
                frame = read_latest(self, CAM_STALL_MS)
                print(f"camera {self.config.index_or_path} stalled (frame over {max_age_ms} ms old)", flush=True)
                ui("camera_stall", self.config.index_or_path)
            except Exception:  # noqa: BLE001 - silent too long, or the device errored
                self._scrub_down = True
                print(f"camera {self.config.index_or_path} stopped sending frames: down, reconnecting", flush=True)
                ui("camera_down", self.config.index_or_path, True)
                threading.Thread(target=reconnect_loop, args=(self,), daemon=True).start()
                return placeholder(self)
        self._scrub_last = frame
        return frame

    def quiet_disconnect(self):
        self._scrub_down = False  # stop the reconnect thread
        try:
            disconnect(self)
        except Exception:  # noqa: BLE001 - a dead camera must not block shutdown
            pass

    OpenCVCamera.read_latest = tolerant
    OpenCVCamera.disconnect = quiet_disconnect

    # LeRobot calls the robot disconnected if any camera is closed, and then refuses to read the
    # arm. Cameras are handled above, so the robot is connected while its motor bus is.
    from lerobot.robots.so_follower.so_follower import SOFollower
    SOFollower.is_connected = property(lambda self: self.bus.is_connected)

    drop = os.environ.get("SCRUB_DROP_CAMERA")  # drill: close the wrist camera N s into the session
    if drop:
        connect = OpenCVCamera.connect

        def connect_and_arm(self, *a, **kw):
            connect(self, *a, **kw)
            if self.config.index_or_path == DROP_TARGET[0] and not DROP_TARGET[1]:
                DROP_TARGET[1] = True
                threading.Timer(float(drop), lambda: (print("drill: closing camera", flush=True),
                                                      disconnect(self))).start()
        OpenCVCamera.connect = connect_and_arm


def lenient_motor_check() -> None:
    """LeRobot's start-up check pings each motor once and counts a reply carrying an error flag
    (angle out of range, overload) as a missing motor. A motor that answers is there: retry a
    missed reply twice and ignore the flag."""
    from lerobot.motors.motors_bus import MotorsBus

    def ping(self, motor, num_retry: int = 0, raise_on_error: bool = False):
        id_ = self._get_motor_id(motor)
        for _ in range(1 + max(num_retry, 2)):
            model, comm, _error = self.packet_handler.ping(self.port_handler, id_)
            if self._is_comm_success(comm):
                return model
        if raise_on_error:
            raise ConnectionError(f"motor {id_} did not answer")
        return None
    MotorsBus.ping = ping


def joint_limits(bus) -> dict:
    """Each follower joint's calibrated range in LeRobot's units, 1 inside the ends."""
    out = {}
    for m, c in bus.calibration.items():
        if m == "gripper":
            out[m] = (1.0, 99.0)
            continue
        mid = (c.range_min + c.range_max) / 2
        lo, hi = ((r - mid) * 360 / 4095 for r in (c.range_min, c.range_max))
        out[m] = (lo + 1, hi - 1)
    return out


def clamp_follower() -> None:
    """The leader's wrist reaches past the follower's range; a goal past a limit sets the motor's
    angle error, which later fails LeRobot's start-up check. Keep every goal inside the range."""
    from lerobot.robots.so_follower.so_follower import SOFollower
    send = SOFollower.send_action

    def clamped(self, action):
        lim = getattr(self, "_scrub_limits", None) or joint_limits(self.bus)
        self._scrub_limits = lim
        action = dict(action)
        for k, v in action.items():
            m = k[:-4] if k.endswith(".pos") else None
            if m in lim:
                action[k] = min(lim[m][1], max(lim[m][0], v))
        return send(self, action)
    SOFollower.send_action = clamped


JOINT_LOAD_MAX = 250  # |Present_Load| (0.1% of max torque) a joint may push without moving
JOINT_STALL_S = 1.0   # pushing this long while stuck: hold where it is instead of pushing
TEMP_WARN, TEMP_RELAX = 55, 62  # deg C: warn on the page; stop pushing with that motor
ARM_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")


def guard_joints() -> None:
    """A blocked joint (the folded rest pose against the base or table, an object in the way) keeps
    its motor stalled at the current limit until it overheats and trips overload, one motor after
    another (Oct 17: all six at 54-61 C, wrist_flex flagged overload). If a joint pushes hard without
    moving for JOINT_STALL_S, or its motor is too hot, command its present position until the leader
    moves it back the other way."""
    from lerobot.robots.so_follower.so_follower import SOFollower
    send = SOFollower.send_action
    st = {"since": {}, "hold": {}, "dir": {}, "temp": {}, "temp_t": 0.0}

    def guarded(self, action):
        now = time.perf_counter()
        try:
            loads = self.bus.sync_read("Present_Load", normalize=False)
            pos = self.bus.sync_read("Present_Position")
        except Exception:  # noqa: BLE001 - no fresh reading: send as is
            return send(self, action)
        if now - st["temp_t"] > 2.0:
            st["temp_t"] = now
            try:
                st["temp"] = {k: int(v) for k, v in self.bus.sync_read("Present_Temperature", normalize=False).items()}
            except Exception:  # noqa: BLE001
                pass
        action = dict(action)
        for m in ARM_JOINTS:
            k = m + ".pos"
            if k not in action or m not in pos:
                continue
            goal, here, load = action[k], pos[m], abs(int(loads.get(m, 0)))
            push = goal - here
            if m in st["hold"]:
                # Released when the leader comes back to where the follower is or moves the other way.
                if abs(goal - st["hold"][m]) < 2.0 or push * st["dir"][m] < 0:
                    st["hold"].pop(m)
                    st["since"].pop(m, None)
                    print(f"joint guard: {m} released", flush=True)
                else:
                    action[k] = st["hold"][m]
                    continue
            hot = st["temp"].get(m, 0) >= TEMP_RELAX
            if (load > JOINT_LOAD_MAX and abs(push) > 3.0) or (hot and abs(push) > 1.0):
                st["since"].setdefault(m, now)
                if hot or now - st["since"][m] > JOINT_STALL_S:
                    st["hold"][m], st["dir"][m] = here, (1 if push > 0 else -1)
                    action[k] = here
                    print(f"joint guard: {m} {'hot ' + str(st['temp'][m]) + ' C' if hot else 'blocked (load ' + str(load) + ')'}, "
                          f"holding at {here:.0f} instead of pushing to {goal:.0f}", flush=True)
            else:
                st["since"].pop(m, None)
        try:
            import arm_ui
            arm_ui.S["motors"] = {m: {"temp_c": st["temp"].get(m), "load": int(loads.get(m, 0)),
                                      "held": m in st["hold"]} for m in (*ARM_JOINTS, "gripper")}
        except ImportError:
            pass
        return send(self, action)
    SOFollower.send_action = guarded

    disconnect = SOFollower.disconnect

    def safe_disconnect(self, *a, **kw):
        """Keeping torque on stops a raised arm falling, but at rest it only keeps the motors
        pushing into the base. Folded at rest: torque off. Raised: hold where it is, no push."""
        try:
            p = self.bus.sync_read("Present_Position")
            if p["shoulder_lift"] <= -90 and p["elbow_flex"] >= 85:
                self.bus.disable_torque()
                print("exit: arm folded at rest, torque off so the motors cool", flush=True)
            else:
                raw = self.bus.sync_read("Present_Position", normalize=False)
                self.bus.sync_write("Goal_Position", raw, normalize=False)
                print("exit: arm raised, holding where it is", flush=True)
        except Exception:  # noqa: BLE001 - the original disconnect still runs
            pass
        return disconnect(self, *a, **kw)
    SOFollower.disconnect = safe_disconnect


def _guard_ui(holding: bool, at) -> None:
    try:
        import arm_ui
        arm_ui.S["guard"] = {"holding": holding, "at": at}
        arm_ui.note("claw guard: " + (f"holding at {at}" if holding else "released"))
    except ImportError:
        pass


def _grip_health(bus, st: dict, now: float):
    """Gripper load every loop and temperature every 2 s; None when a read fails. Shown on the page."""
    load = temp = None
    try:
        load = abs(int(bus.read("Present_Load", "gripper", normalize=False)))
    except Exception:  # noqa: BLE001 - an error flag or a busy bus is not a reason to stop teleop
        pass
    temp = st.get("temp")
    if now - st.get("temp_t", 0.0) > 2.0:
        st["temp_t"] = now
        try:
            temp = st["temp"] = int(bus.read("Present_Temperature", "gripper", normalize=False))
        except Exception:  # noqa: BLE001
            temp = st["temp"] = None
    try:
        import arm_ui
        arm_ui.S["grip_health"] = {"load": load, "temp_c": temp}
    except ImportError:
        pass
    return load, temp


def guard_gripper() -> None:
    """Patch SOFollower.send_action so a blocked claw times out to a gentle hold."""
    from lerobot.robots.so_follower.so_follower import SOFollower
    send = SOFollower.send_action
    st = {"hold": None, "ref": None, "since": 0.0}

    def guarded(self, action):
        goal = action.get("gripper.pos")
        if goal is None:
            return send(self, action)
        try:
            pos = self.bus.read("Present_Position", "gripper")
        except RuntimeError as e:
            if "Overload" not in str(e):
                raise
            # The servo tripped overload protection: it flags every reply until the load drops.
            # Open a little each loop instead of letting LeRobot's exception end the session.
            base = st["hold"] if st["hold"] is not None else st.get("pos", goal)
            st["hold"], st["ref"] = min(100.0, base + GRIP_BACKOFF), None
            print(f"gripper guard: overload, easing to {st['hold']:.0f}", flush=True)
            _guard_ui(True, round(st["hold"]))
            return send(self, {**action, "gripper.pos": max(goal, st["hold"])})
        st["pos"] = pos
        now = time.perf_counter()
        load, temp = _grip_health(self.bus, st, now)
        if (load is not None and load > GRIP_LOAD_MAX) or (temp is not None and temp >= GRIP_TEMP_EASE):
            st["strain"] = st.get("strain") or now
            if now - st["strain"] > GRIP_LOAD_S or (temp is not None and temp >= GRIP_TEMP_EASE):
                # Ease off before the servo trips overload or overheats; the leader opening still releases.
                st["hold"], st["ref"] = min(100.0, max(st["hold"] or 0.0, pos) + 1.0), None
                if not st.get("eased"):
                    print(f"gripper guard: straining (load {load}, {temp} C), easing open", flush=True)
                st["eased"] = True
                _guard_ui(True, round(st["hold"]))
                return send(self, {**action, "gripper.pos": max(goal, st["hold"])})
        else:
            st["strain"], st["eased"] = None, False
        if st["hold"] is not None:
            if goal >= st["hold"] + GRIP_SQUEEZE:  # leader opened past the contact point: let go
                st["hold"], st["ref"] = None, None
                print("gripper guard: released", flush=True)
                _guard_ui(False, None)
            else:
                action = {**action, "gripper.pos": max(goal, st["hold"])}
        elif goal < pos - GRIP_SQUEEZE:  # told to close further than it is
            if st["ref"] is None or abs(pos - st["ref"]) > GRIP_MOVE:
                st["ref"], st["since"] = pos, now  # still closing
            elif now - st["since"] > GRIP_STALL_S:
                st["hold"] = max(0.0, pos - GRIP_SQUEEZE)
                action = {**action, "gripper.pos": st["hold"]}
                print(f"gripper guard: blocked at {pos:.0f}, holding at {st['hold']:.0f}", flush=True)
                _guard_ui(True, round(st["hold"]))
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


class Tee:
    """Everything printed (and any crash traceback) also goes to a log file."""
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, s):
        self.stream.write(s)
        self.log.write(s)
        self.log.flush()

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start_log() -> Path:
    logs = Path.home() / "scrub-logs"
    logs.mkdir(exist_ok=True)
    path = logs / time.strftime("arm-%Y%m%d-%H%M%S.log")
    log = open(path, "a", buffering=1)
    sys.stdout, sys.stderr = Tee(sys.stdout, log), Tee(sys.stderr, log)
    faulthandler.enable(log)  # hard crashes too
    print(f"log: {path}", flush=True)
    return path


def camera_names() -> list[str]:
    """Camera names in OpenCV's index order. OpenCV's macOS backend sorts devices by uniqueID,
    which includes the USB location, so indexes change when a camera is replugged elsewhere."""
    import AVFoundation as AVF
    devs = AVF.AVCaptureDevice.devicesWithMediaType_(AVF.AVMediaTypeVideo)
    return [str(d.localizedName()) for d in sorted(devs, key=lambda d: str(d.uniqueID()))]


def find_camera(spec: str) -> int | None:
    if spec.isdigit():
        return int(spec)
    hits = [i for i, n in enumerate(camera_names()) if spec.lower() in n.lower()]
    return hits[0] if len(hits) == 1 else None


def bus_ok(port: str) -> bool:
    return not silent_motors(port)


def silent_motors(port: str) -> list[int]:
    """Motor ids 1-6 that don't answer a ping, [0] if the port won't open (only while no session owns it)."""
    import scservo_sdk as scs
    ph = scs.PortHandler(port)
    try:
        if not ph.openPort():
            return [0]
        ph.setBaudRate(1_000_000)
        pk = scs.PacketHandler(0)
        return [i for i in range(1, 7) if pk.ping(ph, i)[1] != scs.COMM_SUCCESS]
    except Exception:  # noqa: BLE001 - unplugged mid-check
        return [0]
    finally:
        try:
            ph.closePort()
        except Exception:  # noqa: BLE001
            pass


def missing_devices(a) -> list[str]:
    out = []
    for name, port in (("follower arm", a.follower), ("leader arm", a.leader)):
        if not os.path.exists(port):
            out.append(f"{name} USB ({Path(port).name})")
        elif silent := silent_motors(port):
            if silent == [0] or len(silent) == 6:
                out.append(f"{name} motors (power or cable)")
            else:
                hint = "; check the gripper cable" if 6 in silent else ""
                out.append(f"{name} motor {', '.join(map(str, silent))} not answering: power-cycle the arm{hint}")
    for role in ("side", "wrist"):
        spec = getattr(a, role)
        if spec and find_camera(spec) is None:
            out.append(f"{role} camera ({spec})")
    return out


def dataset_episodes(root) -> int:
    try:
        return json.loads((Path(root) / "meta" / "info.json").read_text())["total_episodes"]
    except Exception:  # noqa: BLE001 - no dataset yet
        return 0


def _with(argv: list, flag: str, value) -> list:
    """argv with `flag value` replaced, or removed when value is None."""
    out, skip = [], False
    for i, x in enumerate(argv):
        if skip:
            skip = False
            continue
        if x == flag:
            skip = True
            continue
        if x.startswith(flag + "="):
            continue
        out.append(x)
    return out + ([flag, str(value)] if value is not None else [])


def check_dataset(root: Path) -> None:
    """Everything training needs, offline: the dataset passes arm.train's local check with this
    folder's cadence report, and every file is one the upload accepts."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from arm.dataset_check import local_check
    from arm.upload_dataset import manifest
    for junk in root.rglob(".DS_Store"):  # Finder leaves these; the upload rejects them
        junk.unlink()
        print(f"removed {junk}")
    cadence = Path(f"{root}-cadence.json")
    try:
        report = local_check(root, cadence)
        files = manifest(root)
    except (ValueError, OSError) as e:
        sys.exit(f"NOT READY: {e}")
    size = sum(f["size_bytes"] for f in files) / 1024**2
    print(f"READY: {report['episodes']} episodes, {report['frames']} frames, loop "
          f"{report['measured_fps_min']}-{report['measured_fps_max']} Hz, {len(files)} files, {size:.0f} MB")
    print(f"upload: python -m arm.train upload {root} --name scrub --idempotency-key scrub-upload-<n>")


def supervise(a, argv: list) -> None:
    """Run sessions as child processes. Missing devices: wait (the page says what for). A session
    that dies from a disconnect: wait for the devices, then start again; a recording resumes the
    same dataset (only the episode in progress is lost). Ends when a session exits cleanly."""
    import subprocess
    import arm_ui
    record = bool(a.task)
    arm_ui.S.update(mode="record" if record else "teleop", task=a.task)
    arm_ui.cfg["root"] = a.root if record else None
    start_eps = dataset_episodes(a.root) if record else 0
    restarts, opened, serving, shown = 0, False, False, None
    try:
        while True:
            missing = missing_devices(a)
            blocking = [m for m in missing if record or "camera" not in m]  # teleop runs without cameras
            if blocking:
                if not serving and not a.no_ui:
                    arm_ui.S["phase"] = "waiting"
                    arm_ui.start_server()
                    serving = True
                    if not opened:
                        import webbrowser
                        webbrowser.open(f"http://localhost:{arm_ui.PORT}")
                        opened = True
                arm_ui.S["waiting"] = blocking
                if blocking != shown:
                    print("waiting for: " + ", ".join(blocking), flush=True)
                    shown = blocking
                time.sleep(1)
                continue
            shown = None
            child = list(argv)
            if record:
                remaining = a.episodes - (dataset_episodes(a.root) - start_eps)
                if remaining <= 0:
                    print("all episodes recorded", flush=True)
                    return
                child = _with(child, "--episodes", remaining)
            for m in missing:  # teleop: leave out an unplugged camera
                child = _with(child, "--" + m.split()[0], None)
                print(f"running without the {m}", flush=True)
            if serving:
                arm_ui.stop_server()
                serving = False
            env = {**os.environ, "SCRUB_CHILD": "1", "SCRUB_RESTARTS": str(restarts)}
            if opened:
                env["BROWSER"] = "true"  # the tab is already open; don't open another
            LAST_ERROR.unlink(missing_ok=True)
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *child], env=env)
            opened = opened or not a.no_ui
            try:
                rc = proc.wait()
            except KeyboardInterrupt:
                proc.wait(timeout=15)
                return
            if rc == 0:
                print("session finished", flush=True)
                return
            restarts += 1
            err = LAST_ERROR.read_text().strip() if LAST_ERROR.exists() else f"exit {rc}"
            delay = min(15, 2 * 2 ** min(restarts - 1, 3))  # 2, 4, 8, 15 s: don't spin on a startup error
            print(f"session ended ({err}): restarting in {delay} s ({restarts}x)", flush=True)
            if not a.no_ui:
                arm_ui.S["phase"] = "waiting"
                arm_ui.S["waiting"] = [f"restart in {delay} s (session ended: {err})"]
                arm_ui.start_server()
                serving = True
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        if serving:
            arm_ui.stop_server()


def camera_index(spec: str) -> int:
    if spec.isdigit():
        return int(spec)
    names = camera_names()
    hits = [i for i, n in enumerate(names) if spec.lower() in n.lower()]
    if len(hits) != 1:
        sys.exit(f"camera {spec!r} matches {len(hits)} of {names}")
    return hits[0]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--side", help='side camera: name part like "C920", or an OpenCV index')
    p.add_argument("--wrist", help='wrist camera: name part like "icspring", or an OpenCV index')
    p.add_argument("--task", help='record this exact instruction, e.g. "pick the hemostat"; omit to teleop')
    p.add_argument("--episodes", type=int, default=5)
    p.add_argument("--episode-s", type=int, default=25)
    p.add_argument("--reset-s", type=int, default=10)
    p.add_argument("--root", default=str(Path.home() / "scrub-dataset"))
    p.add_argument("--repo", default="local/scrub", help="dataset name; only matters if pushed later")
    p.add_argument("--ease-s", type=float, default=3.0)
    p.add_argument("--no-ui", action="store_true", help="skip the recorder page on http://localhost:8090")
    p.add_argument("--check", action="store_true",
                   help="no hardware: is --root complete and ready to upload/train? (arm.train's check + upload list)")
    p.add_argument("--follower", default=FOLLOWER)
    p.add_argument("--leader", default=LEADER)
    a = p.parse_args()
    if a.check:
        return check_dataset(Path(a.root))
    start_log()
    if not os.environ.get("SCRUB_CHILD"):
        return supervise(a, sys.argv[1:])

    # keep holding on exit: LeRobot's default drops torque and a raised arm falls
    robot = [f"--robot.type=so101_follower", f"--robot.port={a.follower}", "--robot.id=scrub_follower",
             "--robot.disable_torque_on_disconnect=false"]
    teleop = [f"--teleop.type=so101_leader", f"--teleop.port={a.leader}", "--teleop.id=scrub_leader"]
    cams = {k: camera_index(v) for k, v in (("side", a.side), ("wrist", a.wrist)) if v is not None}
    CAM_SPECS.update({idx: (role, getattr(a, role)) for role, idx in cams.items()})
    for k, v in cams.items():
        print(f"{k} camera: index {v} ({camera_names()[v] if v < len(camera_names()) else '?'})", flush=True)
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
               "--dataset.push_to_hub=false",
               # encode video while recording: ~11 s between episodes instead of ~18, loop stays 30 Hz
               "--dataset.streaming_encoding=true", "--dataset.encoder_threads=2"]
        if (Path(a.root) / "meta" / "info.json").exists():
            cmd.append("--resume=true")
    else:
        cmd = ["lerobot-teleoperate", *robot, *teleop, "--fps=30"]

    lenient_motor_check()
    ease(a.follower, a.leader, a.ease_s)
    print(" ".join(cmd), flush=True)
    clamp_follower()  # innermost: the gripper guard below sees and sends clamped goals
    guard_gripper()
    guard_joints()  # outermost: sees the leader's goals before the claw guard and the clamp
    DROP_TARGET[0] = cams.get("wrist")
    tolerate_camera_stalls()
    if not a.no_ui:
        import webbrowser
        import arm_ui
        arm_ui.install("record" if a.task else "teleop", a.task, a.episodes, a.episode_s, a.reset_s,
                       a.root if a.task else None, cams)
        webbrowser.open(f"http://localhost:{arm_ui.PORT}")
    if a.task:
        from lerobot.scripts.lerobot_record import main as run
    else:
        from lerobot.scripts.lerobot_teleoperate import main as run
    sys.argv = cmd  # same arguments as the CLI, run in this process so the guard applies
    try:
        run()
    except BaseException as e:
        if not isinstance(e, (KeyboardInterrupt, SystemExit)):
            LAST_ERROR.write_text(f"{type(e).__name__}: {str(e).strip().splitlines()[0][:160] if str(e).strip() else ''}")
        raise


if __name__ == "__main__":
    main()
