#!/bin/bash
# Copy the public page to a Vultr server and start it (nginx on 80, python on 8080).
# Usage: bash ledger/push_public.sh root@1.2.3.4 [domain you@school.edu]
# The server gets only MONGODB_URI and SCRUB_PUBLIC_URL from .env, and no buffer.jsonl.
set -euo pipefail
HOST="${1:-}"
if [[ -z "$HOST" ]]; then
  echo "usage: bash ledger/push_public.sh root@SERVER_IP [domain you@school.edu]" >&2
  exit 1
fi
shift
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$ROOT/.env" ]]; then
  echo "missing $ROOT/.env with MONGODB_URI" >&2
  exit 1
fi
ssh "$HOST" "mkdir -p /opt/scrub/ledger /opt/scrub/deploy"
rsync -a --delete --exclude '__pycache__' --exclude 'buffer.jsonl' "$ROOT/ledger/" "$HOST:/opt/scrub/ledger/"
rsync -a --exclude '__pycache__' "$ROOT/deploy/" "$HOST:/opt/scrub/deploy/"
grep -E '^(MONGODB_URI|SCRUB_PUBLIC_URL)=' "$ROOT/.env" | ssh "$HOST" "umask 077 && cat > /opt/scrub/.env"
ssh "$HOST" "bash /opt/scrub/deploy/setup_public.sh $*"
echo "open http://${HOST#*@}/"
