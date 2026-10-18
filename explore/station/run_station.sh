#!/bin/sh
# Keeps the recording station running: starts it again when it asked to restart (a hung camera, or the page's
# Reconnect), which it marks in ~/scrub-logs/station-restart. Ctrl-C stops it for good.
#   explore/station/run_station.sh --task "pick the hemostat"
cd "$(dirname "$0")/../.." || exit 1
PY="${PYTHON:-$(dirname "$0")/../../.venv/bin/python}"
[ -x "$PY" ] || PY=/Users/caide_1/Documents/dubhacks/dubhacks-2026/.venv/bin/python
MARK="$HOME/scrub-logs/station-restart"
trap 'rm -f "$MARK"; exit 130' INT TERM
while :; do
  rm -f "$MARK"
  "$PY" explore/station/station.py --no-browser "$@"
  code=$?
  if [ -f "$MARK" ] || [ "$code" = 75 ]; then
    echo "run_station: restarting the station (exit $code)"; sleep 2; continue
  fi
  echo "run_station: station exited ($code), not restarting"; exit "$code"
done
