"""python -m sim [--view] [--port 8002]"""
import argparse
import threading

import uvicorn

from sim.server import Grabber, create_app
from sim.sim_arm import SimArm


def main():
    ap = argparse.ArgumentParser(prog="python -m sim")
    ap.add_argument("--view", action="store_true", help="native MuJoCo viewer (macOS: run with mjpython)")
    ap.add_argument("--port", type=int, default=8002)
    args = ap.parse_args()
    arm = SimArm()
    arm.connect()
    grabber = Grabber(arm)
    server = uvicorn.Server(uvicorn.Config(create_app(arm, grabber), host="127.0.0.1", port=args.port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    print(f"sim on http://127.0.0.1:{args.port}  (/stream, /state, /reach, /layout, /web)")
    try:
        if args.view:
            import time
            import mujoco.viewer
            with mujoco.viewer.launch_passive(arm.model, arm.data) as v:
                while v.is_running():
                    with arm.lock:
                        v.sync()
                    time.sleep(1 / 60)
        else:
            grabber.serve(lambda: server.should_exit)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    arm.disconnect()


main()
