#!/bin/bash
# Copy the public page to a Vultr server and start it.
# Usage: bash ledger/push_public.sh root@1.2.3.4
set -euo pipefail
HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "usage: bash ledger/push_public.sh root@SERVER_IP" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$ROOT/.env" ]]; then
  echo "missing $ROOT/.env with MONGODB_URI" >&2
  exit 1
fi
ssh "$HOST" "mkdir -p /opt/scrub/ledger"
rsync -av --exclude '__pycache__' --exclude 'buffer.jsonl' "$ROOT/ledger/" "$HOST:/opt/scrub/ledger/"
rsync -av "$ROOT/.env" "$HOST:/opt/scrub/.env"
ssh "$HOST" "bash /opt/scrub/ledger/install_public.sh"
echo "open http://${HOST#*@}/"
