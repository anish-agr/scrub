"""Publish one stylesheet through the existing servers' allowed /style.css routes.

python design/sync.py --check   # no writes, useful before committing
python design/sync.py           # regenerate deployment copies
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("dashboard/style.css", "ledger/public/style.css", "sim/web/style.css")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = (ROOT / "design/scrub.css").read_bytes()
    different = []
    for name in TARGETS:
        target = ROOT / name
        if not target.exists() or target.read_bytes() != source:
            different.append(name)
            if not args.check:
                target.write_bytes(source)
    if args.check and different:
        print("Stale design copies: " + ", ".join(different))
        return 1
    print("Shared stylesheet: " + ("verified" if args.check else "published"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
