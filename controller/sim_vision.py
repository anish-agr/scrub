"""Fake vision for the MuJoCo sim: reads the SimArm's true state and feeds the Controller in-process."""
import threading
import time

from sim import scene

SLOT_TOL_M = 0.02
RETURN_TOL_M = 0.03


class SimVision:
    def __init__(self, arm, ctl):
        self.arm, self.ctl = arm, ctl
        self.hand_on = False  # off by default, so the saved-spot path still works
        self.hand_seen = True
        self.path_clear = True
        self.hand_target = list(arm.layout["hand_zone"])
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        self._stop.clear()
        self._threads = [threading.Thread(target=self._loop, args=(self.post_tray, 1.0), daemon=True),
                         threading.Thread(target=self._loop, args=(self.post_hand, 0.1), daemon=True)]
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)

    def _loop(self, fn, period):
        while not self._stop.wait(period):
            try:
                fn()
            except Exception as e:  # keep the fake source alive
                print("sim_vision:", e)

    def _positions(self):
        """Item id -> (x, y, z, held), copied under the lock."""
        L = self.arm.layout
        with self.arm.lock:
            return {i: (*map(float, self.arm.data.mocap_pos[self.arm._mocap[i]]), i == self.arm.holding)
                    for i in L["setting_items"][L["setting"]]}

    def post_tray(self):
        L, pos = self.arm.layout, self._positions()
        slots, spot = [], None
        for item, (x, y, z, held) in pos.items():
            sx, sy = scene.slot_position(L, item)
            near = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 <= SLOT_TOL_M
            slots.append({"item": item, "present": bool(near and z > 0 and not held),
                          "confidence": 0.95, "box": None})
            rx, ry = L["return_spot"]
            if not held and z > 0 and ((x - rx) ** 2 + (y - ry) ** 2) ** 0.5 <= RETURN_TOL_M:
                spot = item
        self.ctl.post_tray({"setting": self.ctl.setting["id"], "slots": slots,
                            "return_spot": {"item": spot, "confidence": 0.95 if spot else 0.0, "box": None},
                            "t": time.time()})

    def post_hand(self):
        if not self.hand_on:
            return
        seen = self.hand_seen
        self.ctl.post_hand({"seen": seen, "open": seen, "palm_px": [320, 240] if seen else None,
                            "target": list(self.hand_target) if seen else None,
                            "path_clear": self.path_clear, "t": time.time()})

    def place_in_return_spot(self, item):
        """Test hook: a clinician sets an item in the return spot."""
        rx, ry = self.arm.layout["return_spot"]
        with self.arm.lock:
            if item not in self.arm._mocap or self.arm.holding == item:
                return False
            self.arm.data.mocap_pos[self.arm._mocap[item]] = (rx, ry, 0.01)
        return True

    def status(self):
        return {"on": self.hand_on, "seen": self.hand_seen, "path_clear": self.path_clear,
                "target": list(self.hand_target)}

    def routes(self, app):
        from fastapi import Body

        @app.post("/sim/hand")
        def sim_hand(body: dict = Body(default={})):
            for key, attr in (("on", "hand_on"), ("seen", "hand_seen"), ("path_clear", "path_clear")):
                if key in body:
                    setattr(self, attr, bool(body[key]))
            if body.get("on") is False:
                self.ctl.hand_at = 0.0  # tracking off now, not 5 s later: back to the saved spot
            if body.get("target"):
                self.hand_target = [float(v) for v in body["target"]]
            return self.status()

        @app.post("/sim/return_spot")
        def sim_return_spot(body: dict = Body(...)):
            return {"ok": self.place_in_return_spot(body.get("item"))}

        @app.get("/sim/vision")
        def sim_vision():
            return self.status()
