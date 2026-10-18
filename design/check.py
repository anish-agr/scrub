"""Run the requested regression suites after a page change, with bounded output."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SUITES = (
    ("controller", ["-m", "controller.test_flows"]),
    ("sim", ["-m", "pytest", "-q", "sim/test_sim.py"]),
    ("ledger", ["-m", "pytest", "-q", "ledger/test_ledger.py"]),
)


def main():
    failed = False
    for name, command in SUITES:
        result = subprocess.run([sys.executable, *command], cwd=ROOT, capture_output=True, text=True)
        log = Path(tempfile.gettempdir()) / "opencode" / f"scrub-ui-{name}.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        lines = [line for line in result.stdout.splitlines() if "passed" in line or "failed" in line]
        print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'} " + (lines[-1] if lines else ""))
        if result.returncode:
            print(f"Details: {log}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
