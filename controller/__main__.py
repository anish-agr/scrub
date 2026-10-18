"""python -m controller [--fake-arm | --real-arm | --sim-arm] [--port 8000] [--setting surgical|bench] [--judge] [--skills model|taught|auto|smart]"""
import argparse
import os
import signal
import threading
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
GRACE_S = 2  # on SIGTERM or Ctrl-C, uvicorn waits this long for open WebSockets (voice, the dashboard), then exits

from . import core  # noqa: E402
from .core import Controller  # noqa: E402
from .server import make_app  # noqa: E402


def _interrupt(*_):
    raise KeyboardInterrupt


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m controller")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fake-arm", action="store_true", help="default")
    g.add_argument("--real-arm", action="store_true")
    g.add_argument("--sim-arm", action="store_true", help="MuJoCo SO-101 from sim/ (say got_it to release)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--sim-port", type=int, default=8002, help="--sim-arm: also serve sim viewer/stream/state here")
    p.add_argument("--setting", default="surgical", choices=["surgical", "bench", "dental"], metavar="SETTING",
                   help="surgical (default) or bench; dental is hidden but still loads")
    p.add_argument("--judge", action="store_true",
                   help="judge mode: /command takes only handover, count, stop, got_it (POST /judge toggles it)")
    p.add_argument("--motion-s", type=float, default=1.0, help="fake arm seconds per motion")
    p.add_argument("--pull-s", type=float, default=2.0,
                   help="fake arm: simulated pull after this many seconds at the hand; 0 = wait for got_it")
    p.add_argument("--skills", default="model", choices=["model", "taught", "auto", "smart"],
                   help="model (default): the robot model; taught: recorded skills from arm/skills/ only; "
                        "auto: model for items it passed 3 real tries in a row, else taught if recorded, else model; "
                        "smart: vision locates the item, the method per item comes from real-arm data "
                        "(controller/picker.py), grip checked, one retry with the next method")
    a = p.parse_args()

    if a.real_arm:
        from arm import real_arm  # Anish's; only the controller imports arm/
        arm = (getattr(real_arm, "Arm", None) or getattr(real_arm, "RealArm"))()
    elif a.sim_arm:
        from sim.sim_arm import SimArm
        arm = SimArm()
        arm.set_setting(a.setting)  # --setting must select the physical sim tray at startup too
        arm.pull_delta = 0.5  # sim load is servo force in N; pull() adds 1.0
    else:
        from .fake_arm import FakeArm
        arm = FakeArm(motion_s=a.motion_s, auto_pull_s=a.pull_s or None)
    # SCRUB_STATE_FILE: where the count is saved across a restart; empty turns it off. Default: one file per port
    # under data/ (ignored), so a second stack on another port never picks up this one's count.
    state_file = os.environ.get("SCRUB_STATE_FILE")
    if state_file is None:
        state_file = ROOT / "data" / f"controller-state-{a.port}.json"
    arm.connect()
    # A deployment exists on the real arm only with PERCEPTRON_DEPLOYMENT_ID; fake and sim always count as having one.
    deployment = bool(os.environ.get("PERCEPTRON_DEPLOYMENT_ID")) if a.real_arm else True
    ctl = Controller(arm, fake_arm=not a.real_arm, setting_id=a.setting, judge=a.judge, state_file=state_file or None,
                     skills=a.skills, deployment=deployment,
                     arm_kind="real" if a.real_arm else "sim" if a.sim_arm else "fake")
    print(f"controller: {'real' if a.real_arm else 'sim' if a.sim_arm else 'fake'} arm, setting {a.setting} "
          f"({ctl.setting['_source']}), ledger {'on' if core.ledger else 'off'}, skills {a.skills}"
          f"{', judge mode' if a.judge else ''}", flush=True)
    # SIGTERM acts like Ctrl-C, so the finally below always disconnects the arm (frees the serial port). In the sim
    # the servers run in threads and uvicorn installs no handlers; otherwise uvicorn re-raises the signal once it
    # has shut down, and with the default handler that killed the process before the finally ran.
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        if a.sim_arm:  # MuJoCo GL needs the main thread: controller API in a thread, frame grabber here
            from sim.server import Grabber, create_app
            from .sim_vision import SimVision
            vision = SimVision(arm, ctl)  # TrayState from the sim, Hand when POST /sim/hand {"on": true}
            vision.start()
            grabber = Grabber(arm)
            sim = uvicorn.Server(uvicorn.Config(create_app(arm, grabber), host="127.0.0.1", port=a.sim_port,
                                                log_level="warning", timeout_graceful_shutdown=GRACE_S))
            api = uvicorn.Server(uvicorn.Config(make_app(ctl, vision.routes), host="0.0.0.0", port=a.port,
                                                log_level="warning", timeout_graceful_shutdown=GRACE_S))
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
            uvicorn.run(make_app(ctl), host="0.0.0.0", port=a.port, log_level="warning",
                        timeout_graceful_shutdown=GRACE_S)
    except KeyboardInterrupt:
        pass
    finally:
        arm.disconnect()
        print("controller: arm disconnected", flush=True)


main()
