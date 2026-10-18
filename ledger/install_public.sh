#!/bin/bash
# Install the read-only Scrub count page on an Ubuntu Vultr server.
# Run this on the server, from the repo root (/opt/scrub), after .env has MONGODB_URI.
#
# Vultr clicks (Evan, in the browser):
# 1. Open https://mlh.link/vultr-discover and register. Company = your school name. Job title = Student. Copy the promo code.
# 2. Open https://mlh.link/vultr-giftcode (or https://my.vultr.com) and create an account, or log in. Apply the promo code under Billing if it is not already on the account.
# 3. Click Products, then Deploy (or the blue Deploy + button).
# 4. Choose Cloud Compute, Shared CPU, the smallest plan (1 vCPU, 1 GB RAM is enough).
# 5. Location: the closest city to Seattle.
# 6. Image: Ubuntu 24.04 LTS.
# 7. SSH keys: add the public key printed by `cat ~/.ssh/id_ed25519.pub` on the laptop. Name it scrub.
# 8. Server hostname: scrub. Leave the rest. Click Deploy Now.
# 9. Wait until the status is Running. Copy the IPv4 address.
# 10. On the laptop: bash ledger/push_public.sh root@THAT_IP
# 11. In the Vultr server page, Settings, Firewall: if a firewall group is attached, add a rule that accepts TCP port 80. A new server with no firewall group already accepts port 80.
#
# GoDaddy clicks, after the server answers on port 80:
# 1. Open the MLH GoDaddy Registry offer from the DubHacks sponsor page and sign in (or create the account). Buy one cheap domain, for example scrub.example style, something the team can say out loud.
# 2. Go to My Products, the domain, then DNS (Manage DNS).
# 3. Add a record: Type A, Name @, Value THE_SERVER_IP, TTL 600. Save.
# 4. Add a record: Type CNAME, Name www, Value @, TTL 600. Save. If GoDaddy already has an A record for @ that parks the domain, edit that record instead of adding a second one.
# 5. Wait a few minutes, then open http://the-domain/ . The count and the two tables should match http://127.0.0.1:8080/ on the laptop (same Mongo database). HTTPS is not set up; use http for the weekend.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "missing .env with MONGODB_URI at $(pwd)/.env" >&2
  exit 1
fi
if ! grep -q '^MONGODB_URI=.\+' .env; then
  echo "MONGODB_URI is empty in .env" >&2
  exit 1
fi
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip
fi
python3 -m venv .venv
.venv/bin/pip install -r ledger/requirements.txt
sudo cp ledger/scrub-public.service /etc/systemd/system/scrub-public.service
sudo systemctl daemon-reload
sudo systemctl enable scrub-public
sudo systemctl restart scrub-public
sudo systemctl --no-pager --full status scrub-public || true
echo "public page should answer on port 80"
