# deploy

## Redeploy the judge page now (Brandon, Oct 18)

Only Brandon's laptop has its SSH key on the server (Caiden's Mac gets `Permission denied (publickey)`). From the repo root on Brandon's laptop, with `MONGODB_URI` in `.env`:

```
git pull origin main; powershell -File deploy/push_public.ps1 -Target root@144.202.95.111
```

Then check `curl -s http://144.202.95.111/ | findstr "safe spot Isaac Tiger Backboard GoDaddy bench"` prints nothing, and the nav shows Count, Cases, Table card. Until this runs, the live page still shows the old text (safe spot, bench tray, fine-tuned Isaac doing the picks, the Photon number, Tiger Data, Backboard, GoDaddy).

Owner: Brandon (handed E6's server from Evan). `deploy/` only.

`check_env.py` reads the repo-root `.env` and prints which keys each laptop needs, then probes each service. It prints PASS or FAIL. It does not print key values.

```
pip install -r deploy/requirements.txt
python -m deploy
```

Same thing: `python deploy/check_env.py` from the repo root.

| Laptop | Service | Keys it needs |
| --- | --- | --- |
| arm | controller | `CONTROLLER_URL` (default `http://localhost:8000`) |
| arm | arm | `PERCEPTRON_TEAM_API_KEY`, `PERCEPTRON_DEPLOYMENT_ID`, `HF_TOKEN`, `SO101_PORT` |
| arm | ledger | `MONGODB_URI` |
| arm | vision | `PERCEPTRON_API_KEY`, `CAMERA_INDEX` (default 0), `VISION_URL` (default `http://localhost:8001`), `SIM_URL` (optional, default `http://127.0.0.1:8002`) |
| voice | voice | `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `PHOTON_API_KEY`, `PHOTON_PROJECT_ID`. Optional: `VOICE_LLM_SECRET`, `PHOTON_SUMMARY_TO`, `SCRUB_PUBLIC_URL`, `VOICE_PORT` (default 3000), `CONTROLLER_URL`. Empty Photon names fall back to `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET` |

Optional `SCRUB_PUBLIC_URL` or `SCRUB_SERVER_IP` (the Vultr page). The stats check reads `/api/stats` from that address. The page check also opens `http://144.202.95.111/` and `SCRUB_PUBLIC_URL` and looks for the word Scrub. A missing public URL is FAIL.

Live probes: Perceptron `GET https://robotics.perceptron.inc/v1/capabilities`, Perceptron `GET /v1/deployments` (the id in `PERCEPTRON_DEPLOYMENT_ID` must be listed), the Vultr page `GET /api/stats`, the same page's HTML on the Vultr IP and on `SCRUB_PUBLIC_URL`, Perceptron `POST https://api.perceptron.inc/v1/detect`, Gemini model list, ElevenLabs `GET /v1/user` (and the agent when `ELEVENLABS_AGENT_ID` is set), Photon `GET /v1/projects/{id}`, MongoDB `ping`, Hugging Face `whoami-v2`, controller `GET /state`, vision `GET /health`, voice `GET /health`.

Offline check of the table formatting: `python -m unittest deploy.test_check_env`

## Public page

The page is `python -m ledger serve` on port 8080. nginx proxies port 80 to it and certbot adds HTTPS. The browser never sees `MONGODB_URI`.

### Vultr (MLH credits)

1. Open https://mlh.link/vultr-discover and register. Company = your school name. Job title = Student. Copy the promo code.
2. Open https://mlh.link/vultr-giftcode (or https://my.vultr.com). Create an account or log in. Apply the promo code under Billing if it is not already there.
3. Products, then Deploy (the blue Deploy + button).
4. Cloud Compute, Shared CPU, the smallest plan (1 vCPU, 1 GB RAM).
5. Location: the closest city to Seattle.
6. Image: Ubuntu 24.04 LTS.
7. SSH keys: add the laptop's public key. On this PC: `Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub`. Name the key scrub.
8. Hostname: scrub. Deploy Now.
9. Wait until the status is Running. Copy the IPv4 address.
10. On the server page, Settings, Firewall: allow TCP 22, 80, and 443. Do not open 8080.

### Copy the page up

From the repo root, after `.env` contains `MONGODB_URI`:

```
bash ledger/push_public.sh root@SERVER_IP
```

On Windows: `powershell -File deploy/push_public.ps1 -Target root@SERVER_IP`.

Either copies `ledger/` (without `buffer.jsonl`) and `deploy/` to `/opt/scrub`, writes a server `.env` that holds only `MONGODB_URI` and `SCRUB_PUBLIC_URL`, and runs `deploy/setup_public.sh`. Shell scripts are sent with Unix line endings. If `ufw` is on, the script opens ports 80 and 443 and leaves 8080 closed. This is the only server path (`ledger/install_public.sh` calls the same script). Open `http://SERVER_IP/`. The count and the two tables should match `python -m ledger serve` on the laptop.

The server at `144.202.95.111` is already serving `http://144.202.95.111/` from MongoDB. There is no domain yet, so the page is HTTP only.

### HTTPS

```
powershell -File deploy/enable_https.ps1 -Target root@SERVER_IP -Domain the-domain.tld -Email you@school.edu
```

That runs certbot for `the-domain.tld` and `www.the-domain.tld` and redirects HTTP to HTTPS. Open `https://the-domain.tld/`.
