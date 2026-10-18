"""Run the vision process: python -m vision"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn
from dotenv import load_dotenv

from vision.app import create_app
from vision.camera import FakeCapture, lock_controls, open_capture
from vision.hand import synthetic_landmarks
from vision.calibrate import fake_calibration
from vision.service import ROOT, build_runtime, start_loops
from vision.tray import FakeDetector

logger = logging.getLogger("vision")


def _env_float(name: str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    return float(raw)


class _ScriptedDetector:
    """Fake tray: every instrument category is present until the controller is past the pick.

    Once the step is checking or later, the current item drops out of the
    detections so the grasp check sees an empty slot.
    """

    _HIDE_STEPS = {
        "checking",
        "moving_to_hand",
        "waiting_for_pull",
        "releasing",
        "homing",
        "setting_down",
        "returning",
    }

    def __init__(self):
        self.calls = 0
        self.runtime = None

    def detect(self, frame, categories):
        self.calls += 1
        hidden = ""
        runtime = self.runtime
        if runtime is not None:
            state = runtime.poster.get_json("/state") or {}
            if state.get("step") in self._HIDE_STEPS and state.get("item"):
                hidden = str(state["item"]).replace("_", " ")
        detections = []
        x = 40
        for name in categories:
            if name in ("robot arm", "gripper"):
                continue
            if hidden and name.replace("_", " ") == hidden:
                continue
            detections.append(
                {
                    "mention": name,
                    "point_box": {"top_left": {"x": x, "y": 80}, "bottom_right": {"x": x + 100, "y": 140}},
                }
            )
            x += 120
        return detections


def main(argv: list[str] | None = None) -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Scrub overhead vision")
    parser.add_argument("--fake", action="store_true", help="synthetic camera, hand, and tray")
    parser.add_argument("--port", type=int, default=int(os.environ.get("VISION_PORT", "8001")))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # not a line per post to the controller
    fake = args.fake or os.environ.get("VISION_FAKE") == "1"
    if fake:
        capture = FakeCapture()
        controls = lock_controls(capture, exposure=-6, white_balance=4500)
        detector = FakeDetector(repo=ROOT)
        runtime = build_runtime(
            capture,
            controls=controls,
            fake_hands=lambda _frame: [synthetic_landmarks(True)],
            detector=detector,
            fake_calibration=True,
        )
        detector.runtime = runtime
        if runtime.calibration is None:
            runtime.calibration = fake_calibration()
            logger.info("no calibration.json; using a fake handoff target")
        logger.info("fake camera, exposure locked=%s", controls)
    else:
        index = int(os.environ.get("CAMERA_INDEX", "0"))
        capture = open_capture(index)
        if not capture.isOpened():
            raise SystemExit(f"could not open camera {index}. Set CAMERA_INDEX in .env or run with --fake.")
        controls = lock_controls(capture, exposure=_env_float("CAMERA_EXPOSURE"), white_balance=_env_float("CAMERA_WB"))
        logger.info("camera %s controls %s", index, controls)
        runtime = build_runtime(capture, controls=controls)

    start_loops(runtime)
    logger.info("preview at http://localhost:%s/", args.port)
    uvicorn.run(create_app(runtime), host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
