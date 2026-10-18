#!/bin/bash
# Kept so old notes still work. The official server setup is deploy/setup_public.sh
# (python on 127.0.0.1:8080 behind nginx on port 80, optional HTTPS).
# The Vultr and GoDaddy clicks are in deploy/README.md.
# Run on the server, from /opt/scrub:  sudo bash ledger/install_public.sh [domain you@school.edu]
set -euo pipefail
exec bash "$(dirname "$0")/../deploy/setup_public.sh" "$@"
