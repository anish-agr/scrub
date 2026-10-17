"""Small hardware adapter and saved-image fake; all motor I/O has one owner."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import time

import numpy as np
from PIL import Image

from .kinematics import FEATURES, JOINTS


def png(image):
    array = np.asarray(image)
    if array.shape != (480, 640, 3) or array.dtype != np.uint8:
        raise ValueError("Inference needs uint8 RGB side/wrist images at 640x480")
    output = BytesIO()
    Image.fromarray(array).save(output, format="PNG")
    return output.getvalue()


class SavedImageBackend:
    def __init__(self, side, wrist, joints=None):
        self.images = {}
        for name, path in (("side", side), ("wrist", wrist)):
            if not path:
                raise ValueError("Dry-run requires saved side and wrist images")
            with Image.open(Path(path)) as image:
                if image.size != (640, 480):
                    raise ValueError("Saved images must be 640x480")
                self.images[name] = png(np.asarray(image.convert("RGB")))
        self.joints = np.asarray(joints if joints is not None else [0, 0, 0, 0, 0, 100], dtype=float)
        self.sent = []
        self.connected = False

    def connect(self):
        self.connected = True

    def read_joints(self):
        return self.joints.copy()

    def read_load(self):
        return 0.0

    def capture(self):
        return self.images.copy()

    def send(self, row):
        if not self.connected:
            raise RuntimeError("Backend disconnected")
        self.joints = np.asarray(row).copy()
        self.sent.append((time.perf_counter(), self.joints.copy()))

    def disconnect(self):
        self.connected = False


class LeRobotBackend:
    """Uses LeRobot's SOFollower API (source verified against v0.4.4).

    No automatic calibration, motor setup, or camera sharing with vision.
    Import is lazy so offline tests need neither torch nor Feetech drivers.
    """
    def __init__(self, port, robot_id, side_index, wrist_index):
        self.config_args = (port, robot_id, side_index, wrist_index)
        self.robot = None

    def connect(self):
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        from lerobot.robots.so_follower.config_so_follower import SO101FollowerConfig
        from lerobot.robots.so_follower.so_follower import SO101Follower

        port, robot_id, side, wrist = self.config_args
        config = SO101FollowerConfig(port=port, id=robot_id, use_degrees=True,
                                    disable_torque_on_disconnect=False,
                                    cameras={name: OpenCVCameraConfig(index_or_path=index,
                                              width=640, height=480, fps=30, color_mode="rgb")
                                             for name, index in (("side", side), ("wrist", wrist))})
        self.robot = SO101Follower(config)
        # Never enter an interactive recalibration from the controller.
        if not self.robot.calibration:
            raise RuntimeError("No saved follower calibration; calibrate manually first")
        self.robot.connect(calibrate=False)
        if not self.robot.is_calibrated:
            raise RuntimeError("Motor calibration does not match the saved follower calibration")

    def read_joints(self):
        values = self.robot.bus.sync_read("Present_Position")
        return np.array([values[n] for n in (*JOINTS, "gripper")], dtype=float)

    def read_load(self):
        # LeRobot decodes STS3215 sign-magnitude bit 10. Not model output and
        # not normalized positions, torque units, or a grasp-success signal.
        return float(self.robot.bus.read("Present_Load", "gripper", normalize=False))

    def capture(self):
        # Camera read threads are separate from the bus owner. No waiting on
        # camera frames in the 30 Hz playback thread; reject stale frames.
        return {name: png(self.robot.cameras[name].read_latest(max_age_ms=100))
                for name in ("side", "wrist")}

    def send(self, row):
        self.robot.send_action(dict(zip(FEATURES, map(float, row))))

    def disconnect(self):
        if self.robot is not None:
            # Do not silently disable torque and drop a held sharp instrument.
            # The operator must support the arm, set down tools and power off.
            if self.robot.bus.is_connected:
                self.robot.bus.disconnect(disable_torque=False)
            for camera in self.robot.cameras.values():
                if camera.is_connected:
                    camera.disconnect()
