#!/bin/bash
# On the Ubuntu server, from /opt/scrub, after .env has MONGODB_URI.
# HTTP only:  sudo bash deploy/setup_public.sh
# With HTTPS: sudo bash deploy/setup_public.sh the-domain.tld you@school.edu
set -euo pipefail
cd "$(dirname "$0")/.."
DOMAIN="${1:-_}"
EMAIL="${2:-}"
if [[ ! -f .env ]]; then
  echo "missing .env with MONGODB_URI at $(pwd)/.env" >&2
  exit 1
fi
if ! grep -q '^MONGODB_URI=.\+' .env; then
  echo "MONGODB_URI is empty in .env" >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx
python3 -m venv .venv
.venv/bin/pip install -r ledger/requirements.txt
cp deploy/scrub-public.service /etc/systemd/system/scrub-public.service
systemctl daemon-reload
systemctl enable scrub-public
systemctl restart scrub-public
CONF=/etc/nginx/sites-available/scrub
sed "s/DOMAIN_NAME/${DOMAIN}/g" deploy/nginx-scrub.conf > "$CONF"
ln -sfn "$CONF" /etc/nginx/sites-enabled/scrub
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
if [[ "$DOMAIN" != "_" && -n "$EMAIL" ]]; then
  certbot --nginx --non-interactive --agree-tos --redirect -m "$EMAIL" -d "$DOMAIN" -d "www.${DOMAIN}"
  echo "https://${DOMAIN}/ should show the count and the tables"
else
  echo "page is on port 80. Run certbot after the domain points here."
fi
