"""python -m video --help. All derivatives stay under data/video/."""
from __future__ import annotations

import argparse
import json
import sys

from .common import BASE, Workspace


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=str(BASE), help="workspace inside data/video/ (before command)")
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo-assets", help="generate labeled synthetic footage/photos/events/joints; never real results")
    demo.add_argument("--seconds", type=float, default=6)
    c = sub.add_parser("corners", help="detect markerless tray and drag corners to fix")
    c.add_argument("--input", required=True)
    c.add_argument("--camera", required=True)
    c.add_argument("--width-mm", type=float, required=True, help="actually measured left-to-right tray extent")
    c.add_argument("--height-mm", type=float, required=True, help="actually measured top-to-bottom tray extent")
    c.add_argument("--points", help="JSON [[TLx,TLy],[TRx,TRy],[BRx,BRy],[BLx,BLy]]")
    c.add_argument("--headless", action="store_true")
    c.add_argument("--accept-auto", action="store_true", help="explicitly accept unattended calibration (fixtures only recommended)")
    ingest = sub.add_parser("ingest", help="index raw clips/photos, contact sheets and explicit clock sync")
    ingest.add_argument("--sync", help="JSON keyed by asset basename: {start_time: epoch, kind: real|simulation}")
    ingest.add_argument("--kind", choices=["real", "simulation", "reconstructed"])
    ingest.add_argument("--clap-clip")
    ingest.add_argument("--clap-ledger-time", type=float)
    ingest.add_argument("--clap-second", type=float, help="omit for isolated audio-peak detection in first minute")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    ws = Workspace(args.root)
    try:
        if args.command == "demo-assets":
            from .common import finite
            from .synthetic import demo_assets
            if not 2 <= finite(args.seconds) <= 60:
                raise ValueError("Demo seconds must be between 2 and 60")
            result = demo_assets(ws, args.seconds)
        elif args.command == "corners":
            from .geometry import corners
            result = corners(ws, args.input, args.camera, args.width_mm, args.height_mm,
                json.loads(args.points) if args.points else None, args.headless, args.accept_auto)
        elif args.command == "ingest":
            from .ingest import ingest
            result = ingest(ws, args.sync, args.kind, args.clap_clip, args.clap_ledger_time, args.clap_second)
        else:
            raise ValueError("Unknown command")
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, ImportError) as error:
        # No keys are read. Avoid printing external SDK/network exception bodies.
        print(f"video: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
