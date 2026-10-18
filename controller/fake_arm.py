"""Fake arm: same interface as arm/real_arm.py, sleeps instead of moving.

Failures can be forced for testing (POST /fake/force, see controller/README.md).
"""
import threading
import time

MOTION_S = 1.0
LOAD_IDLE = 100.0
LOAD_PULLED = 400.0


class APIError(RuntimeError):
    """Same name and message shape as arm/perceptron.py's ("Perceptron HTTP 503"), without importing arm/."""


class FakeArm:
    def __init__(self, motion_s: float = MOTION_S, auto_pull_s: float | None = 2.0):
        self.scale = motion_s / MOTION_S  # 1.0 = about 1 s per motion
        self.auto_pull_s = auto_pull_s  # simulated clinician pull after this long holding; None = never
        self._frozen = threading.Event()
        self._lock = threading.Lock()
        self._gripper = 0.0
        self._holding_since: float | None = None
        self._no_pull = False
        self._no_load = False
        self.pose = "home"
        # Forced failures, each consumed once:
        # {"miss_grasp": 1, "out_of_region": 1, "skill_fail": 1, "no_pull": 1, "no_load": 1}
        # plus {"api_error": 503}: the next prepare() or run_skill() raises APIError with that status
        self.force: dict[str, int] = {}
        self.prepared: list[str] = []  # instructions the last prepare() opened sessions for

    def _take(self, name: str) -> bool:
        with self._lock:
            if self.force.get(name, 0) > 0:
                self.force[name] -= 1
                return True
            return False

    def _sleep(self, s: float) -> bool:
        """Sleep s seconds; False if frozen. Like arm/real_arm.py, a freeze lasts until resume()."""
        return not self._frozen.wait(s * self.scale)

    def _api_fail(self) -> None:
        with self._lock:
            code = self.force.pop("api_error", 0)
        if code:
            raise APIError(f"Perceptron HTTP {code}")

    def connect(self) -> None:
        pass

    def prepare(self, instructions) -> list:
        """Like arm/real_arm.py: pre-open one session per instruction; blocking; a freeze cancels it."""
        if self._frozen.is_set():
            raise RuntimeError("Arm is frozen; preparation cancelled")
        self._api_fail()
        time.sleep(0.05 * self.scale)
        self.prepared = list(dict.fromkeys(instructions))
        return self.prepared

    def run_skill(self, instruction: str, max_s: float = 20.0) -> bool:
        self._api_fail()  # opening the session comes before any motion
        if not self._sleep(1.0):
            return False
        if self._take("skill_fail"):
            return False
        if instruction.startswith("pick"):
            # closed on nothing reads fully closed (1.0); a real grasp stops short
            self._gripper = 1.0 if self._take("miss_grasp") else 0.6
            self._holding_since = time.time() if self._gripper < 0.95 else None
            self._no_pull = self._take("no_pull")
            self._no_load = self._take("no_load")
        else:
            self._gripper = 0.0
            self._holding_since = None
        self.pose = "skill"
        return True

    def go_home(self) -> None:
        if not self._sleep(1.0):
            raise RuntimeError("Home motion stopped")
        self.pose = "home"

    def go_carry(self) -> None:
        if not self._sleep(1.0):
            raise RuntimeError("Carry motion stopped")
        self.pose = "carry"

    def move_to(self, x: float, y: float, z: float, speed: float = 0.3) -> bool:
        if self._take("out_of_region"):
            return False
        if not self._sleep(1.0):
            return False
        self.pose = f"({x:.2f}, {y:.2f}, {z:.2f})"
        if self._holding_since is not None:
            self._holding_since = time.time()
        return True

    def set_down_safe_spot(self) -> bool:
        if not self._sleep(1.0):
            return False
        self._gripper = 0.0
        self._holding_since = None
        self.pose = "safe_spot"
        return True

    def open_gripper(self) -> None:
        if not self._sleep(0.3):
            raise RuntimeError("Gripper release stopped")
        self._gripper = 0.0
        self._holding_since = None

    def gripper_position(self) -> float:
        return self._gripper

    def gripper_load(self) -> float:
        if self._no_load:
            raise RuntimeError("Gripper load unavailable; use explicit got_it release")
        held = self._holding_since
        if held is None or self.auto_pull_s is None:
            return LOAD_IDLE
        if self._no_pull:
            return LOAD_IDLE
        return LOAD_PULLED if time.time() - held > self.auto_pull_s else LOAD_IDLE

    def rest(self) -> None:
        """Parked at home: torque off so the servos don't heat up while waiting."""
        self.resting = True
        self.rest_count = getattr(self, "rest_count", 0) + 1

    def wake(self) -> None:
        """Torque on, holding the parked pose, before the next command."""
        self.resting = False

    def freeze(self) -> None:
        self._frozen.set()

    def resume(self) -> None:
        """Operator rearm after a freeze (the controller calls it only on reset)."""
        self._frozen.clear()

    def disconnect(self) -> None:
        pass
