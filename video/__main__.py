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
