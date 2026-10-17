"""python -m controller [--fake-arm | --real-arm] [--port 8000] [--setting surgical]"""
import argparse
import threading
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import core  # noqa: E402
from .core import Controller  # noqa: E402
from .server import make_app  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m controller")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fake-arm", action="store_true", help="default")
    g.add_argument("--real-arm", action="store_true")
    g.add_argument("--sim-arm", action="store_true", help="MuJoCo SO-101 from sim/ (say got_it to release)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--sim-port", type=int, default=8002, help="--sim-arm: also serve sim viewer/stream/state here")
    p.add_argument("--setting", default="surgical", choices=["surgical", "dental", "bench"])
    p.add_argument("--motion-s", type=float, default=1.0, help="fake arm seconds per motion")
    p.add_argument("--pull-s", type=float, default=2.0,
                   help="fake arm: simulated pull after this many seconds at the hand; 0 = wait for got_it")
    a = p.parse_args()

    if a.real_arm:
        from arm import real_arm  # Anish's; only the controller imports arm/
        arm = (getattr(real_arm, "Arm", None) or getattr(real_arm, "RealArm"))()
    elif a.sim_arm:
        from sim.sim_arm import SimArm
        arm = SimArm()
        arm.pull_delta = 0.5  # sim load is servo force in N; pull() adds 1.0
    else:
        from .fake_arm import FakeArm
        arm = FakeArm(motion_s=a.motion_s, auto_pull_s=a.pull_s or None)
    arm.connect()
    ctl = Controller(arm, fake_arm=not a.real_arm, setting_id=a.setting)
    print(f"controller: {'real' if a.real_arm else 'sim' if a.sim_arm else 'fake'} arm, setting {a.setting} "
          f"({ctl.setting['_source']}), ledger {'on' if core.ledger else 'off'}", flush=True)
    try:
        if a.sim_arm:  # MuJoCo GL needs the main thread: controller API in a thread, frame grabber here
            from sim.server import Grabber, create_app
            from .sim_vision import SimVision
            vision = SimVision(arm, ctl)  # TrayState from the sim, Hand when POST /sim/hand {"on": true}
            vision.start()
            grabber = Grabber(arm)
            sim = uvicorn.Server(uvicorn.Config(create_app(arm, grabber), host="127.0.0.1", port=a.sim_port, log_level="warning"))
            api = uvicorn.Server(uvicorn.Config(make_app(ctl, vision.routes), host="0.0.0.0", port=a.port, log_level="warning"))
            for srv in (sim, api):
                threading.Thread(target=srv.run, daemon=True).start()
            print(f"sim viewer: http://localhost:{a.sim_port}/web/viewer.html", flush=True)
            try:
                grabber.serve(lambda: api.should_exit or sim.should_exit)
            except KeyboardInterrupt:
                pass
            finally:
                api.should_exit = sim.should_exit = True
        else:
            uvicorn.run(make_app(ctl), host="0.0.0.0", port=a.port, log_level="warning")
    finally:
        arm.disconnect()


main()
