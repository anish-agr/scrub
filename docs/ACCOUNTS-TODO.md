# Accounts and keys to-do

Checked Oct 17 on the arm Mac. `.env` was read only for set or empty, never values. Service answers come from `.venv/bin/python -m deploy` (it prints set/MISSING and PASS/FAIL). Never paste a key into chat, a doc or a commit.

## Summary: what is not done

1. Perceptron robotics team key: set but the service answers HTTP 401 (key wrong, expired or for a different team). Blocks run 1.
2. Hugging Face token: `HF_TOKEN` empty.
3. ElevenLabs agent id: `ELEVENLABS_AGENT_ID` empty, and the Custom LLM URL needs the current tunnel URL.
4. Photon: project id and secret are set (as `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET`) but the iMessage line number is not found, SIP inbound for calls is not confirmed. (`python -m deploy` now reads the Spectrum names and shows them as set.)
5. MongoDB Atlas: `MONGODB_URI` empty on this Mac (Brandon ticked E3, so a URI exists on another machine).
6. Vultr, GoDaddy: no evidence done.
7. Devpost: team and draft submitted not confirmed from this Mac.
8. MLH Commit Fellowship form (after submitting).
9. DEV writeup.
10. Tiger Data: `TIGER_DATABASE_URL` empty on this Mac. Series page still runs from the local ledger.
11. Backboard: `BACKBOARD_API_KEY` and `BACKBOARD_ASSISTANT_ID` empty on this Mac. Memory page still answers from the local ledger.

Done and working: Gemini (HTTP 200), ElevenLabs API key (HTTP 200), Perceptron vision key (set; the check says 400, see below).

## deploy results on this Mac

| Service | Result | Meaning |
| --- | --- | --- |
| Perceptron robotics | FAIL HTTP 401 | Team key rejected. `python -m arm.train deployments` prints the same `Perceptron HTTP 401` |
| Perceptron detect | FAIL HTTP 400 | See the note below: the key is probably fine |
| Gemini | PASS HTTP 200 | Works |
| ElevenLabs | PASS HTTP 200 | API key works (agent id not set, so the agent was not checked) |
| Photon | FAIL missing PHOTON_API_KEY | `deploy` only looks for `PHOTON_API_KEY` and `PHOTON_PROJECT_ID`; voice also accepts `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET` (`voice/src/config.ts`), which are set |
| MongoDB Atlas | FAIL missing MONGODB_URI | Not set here |
| Hugging Face | FAIL missing HF_TOKEN | Not set here |
| controller :8000, vision :8001, voice :3000 | PASS | Running (controller is the old fake-arm build; vision is `--fake`) |

Vision probe note: `deploy/check_env.py` sends a 1x1 gray JPEG to `/v1/detect` and its `http_ok` accepts only 200. A bad key gives 401, so a 400 (the image is rejected as too small or invalid) most likely means the key was accepted. Confirm by running real vision (`.venv/bin/python -m vision` with a real camera) and watching it return boxes. Exact change for whoever owns `deploy/` (not edited here): in `check_detect`, treat 400 as `row("Perceptron detect", True, "key ok (HTTP 400 on the test image)")`, and in `check_photon` and the `.env` key list accept `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET` as aliases.

## Accounts and keys

### Perceptron robotics team key (`PERCEPTRON_TEAM_API_KEY`)
- For: training, deployment and inference of the arm model (`arm.train`, `arm/real_arm.py`). Track: Perceptron robotics (the arm).
- Get it: the robotics key is the one staff gave the team at the workshop for https://robotics.perceptron.inc. Ask Perceptron staff at their table for the team key. Do not use the vision key here.
- Needed in: the arm Mac's `.env` only.
- Now: SET, but HTTP 401. Fix: ask staff to confirm the key is the Robotics one for team Scrub and re-issue if needed, paste it in `.env` only, then `.venv/bin/python -m arm.train deployments` must print JSON, not 401. Also check `PERCEPTRON_DEPLOYMENT_ID`, which is set but cannot be verified until the key works (it is written by run 1, so a value now may be a placeholder).

### Perceptron vision key (`PERCEPTRON_API_KEY`)
- For: tray and hand detection in `vision/` through `https://api.perceptron.inc/v1/detect`. Track: Perceptron vision.
- Get it: Perceptron dashboard (the platform account Brandon used). Vision credits: redeem code DUBHACKS26 at checkout (enter $50.00, total $0), per `docs/SETUP.md`.
- Needed in: the machine that runs `python -m vision` (arm Mac or the vision laptop).
- Now: SET. Check says 400 on the 1x1 test image, which most likely means the key works. Confirm with real vision and a real camera. Not proven yet.

### Hugging Face (`HF_TOKEN`, `HF_USER`)
- For: the dataset repo `<HF_USER>/scrub` that Perceptron trains from. Perceptron needs the data on the Hub (the recorder keeps it local until upload). Track: Perceptron robotics.
- Get it: https://huggingface.co/settings/tokens, New token, type Write, name it scrub, copy it. Make or keep the account whose username is `HF_USER`.
- Needed in: the arm Mac's `.env`.
- Now: MISSING (`HF_TOKEN` empty, `HF_USER` absent). Check: `.venv/bin/python -m deploy` shows Hugging Face PASS. Without it `arm.record` cannot name the repo unless you pass `--hf-user`.

### Gemini (`GEMINI_API_KEY`)
- For: turning what was said into one command, and the end-of-case summary. Track: MLH Gemini API.
- Get it: https://aistudio.google.com/apikey, Create API key.
- Needed in: the voice machine's `.env` (the Mac running `voice/`).
- Now: SET and WORKING (HTTP 200).

### ElevenLabs (`ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, Custom LLM URL)
- For: the phone voice. Track: voice (ElevenLabs sponsor prize).
- Key: https://elevenlabs.io, profile, API Keys. SET and WORKING (HTTP 200).
- Agent id: https://elevenlabs.io, Agents, Create agent, Blank. First message `Scrub here. What do you need?`. System prompt `You are Scrub, a robot arm that passes surgical instruments. Caller: {{system__caller_id}}`. LLM: Custom LLM, API type Chat Completions, Model ID `scrub`. Interruptions on. Test in Preview, then Publish. The agent id is on the agent's page (the URL has `agent_...`); put it in `ELEVENLABS_AGENT_ID`. Now: EMPTY. Full steps in `voice/README.md` "Call setup".
- Custom LLM URL: in the voice machine, `cd voice && npm run dev`, then in a second terminal `cd voice && npm run tunnel`, copy the `https://...` address, check `curl https://<tunnel>/health` shows `"controller":true`. In the agent, set Server URL to `https://<tunnel>/v1`. If `VOICE_LLM_SECRET` is set, add the same value as an ElevenLabs secret named `OPENAI_API_KEY` (it is empty now, which is fine). The URL changes every time the tunnel restarts, so update the agent then. Now: NOT DONE here (agent id empty, no tunnel recorded).
- Needed in: the voice machine's `.env`.

### Photon (iMessage, texts and voice)
- For: the texts (end-of-case summary, restock, "what's out") and the phone line. Track: Photon.
- Project id and secret: https://app.photon.codes, your project, project id and secret. SET on this Mac as `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET` (voice reads these; `PHOTON_PROJECT_ID` and `PHOTON_API_KEY` stay empty on purpose, and `deploy` does not know the new names yet, see above). Voice is already live with them on :3000.
- iMessage line number: NOT FOUND. Photon's docs (https://photon.codes/docs and https://photon.codes/docs/spectrum-ts/providers/imessage/connection-and-routing.md) say Free and Pro plans route each user through a number from a shared pool, and only Business plans give one number owned by the project. The SDK finds lines from the project credentials, and the phone handling a chat is `imessage(space).phone` in code. The docs do not say how to see the line in the dashboard or CLI; they point to help@photon.codes. So: in app.photon.codes check the project's Lines page, or the Spectrum CLI (https://photon.codes/docs/cli/spectrum.md, lines commands), or ask Photon in their Discord or at help@photon.codes for the number or email your project's line uses.
- SIP inbound for calls: the voice provider docs (https://photon.codes/docs/spectrum-ts/providers/voice/inbound-calls.md) say you need an iMessage line in the project, then in the dashboard open inbound voice registration, pick the line, and register the SIP URI `sips:sip.rtc.elevenlabs.io:5061` (TLS, no credentials). On the ElevenLabs side import the number: Deploy, Phone Numbers, Import number, From SIP Trunk, Inbound media encryption Allowed, allowed IPs `0.0.0.0/0`, then assign the Scrub agent. Exact steps in `voice/README.md` steps 3 and 4. Now: NOT DONE (no line number, not registered).
- Open question: can a shared-pool iMessage line (Free plan) take voice calls? The inbound doc says "an iMessage line in that project" and does not mention plan limits, but it also does not confirm shared-pool lines work. Ask Photon staff directly: "Can our Free-plan shared-pool line be registered for inbound SIP voice, or do we need a project-owned line?" If not, the call path is out and the demo uses texts plus the text-in voice test (`curl /heard`) as the voice backup.
- Test without an iPhone: Caiden has no iPhone. Text the Photon line from the Mac Messages app signed in with his Apple ID email, to the line number or address once found (iMessage between Apple IDs works from a Mac). Do not text from a second voice server; only the live voice server on :3000 holds the Photon keys.
- Needed in: the voice machine's `.env` (`SPECTRUM_PROJECT_ID`, `SPECTRUM_PROJECT_SECRET`; optional `PHOTON_SUMMARY_TO`).

### MongoDB Atlas (`MONGODB_URI`)
- For: the ledger (every event and measured trial; the success tables). Track: MLH MongoDB Atlas.
- Get it: https://mlh.link/mongodb for the free credit, then https://cloud.mongodb.com, Create cluster (free M0), Database Access, add a user and password, Network Access, add the team IPs (or 0.0.0.0/0 for the weekend), Clusters, Connect, Drivers, copy the `mongodb+srv://...` string.
- Needed in: the controller machine, and every machine that runs trials or the ledger (this Mac if the arm runs here).
- Now: EMPTY on this Mac. Brandon ticked E3 (a fake-arm handover wrote to Atlas), so Evan or Brandon has a URI on another machine. Ask them for it through a private channel, put it in this `.env`, and confirm `.venv/bin/python -m deploy` shows MongoDB Atlas PASS. Until then the ledger buffers locally.

### Vultr
- For: the public judge page on a server. Track: MLH Vultr.
- Get it: https://mlh.link/vultr-discover (register, company = school name, job title Student, copy the promo code), then https://mlh.link/vultr-giftcode or https://my.vultr.com, apply the code under Billing, create a server, then follow `deploy/README.md`.
- Needed in: no `.env` key; Evan or Brandon needs the login and the server IP.
- Now: DONE for the server. Hostname `vultr`, IPv4 `144.202.95.111`. `http://144.202.95.111/` returns the Scrub page (HTTP 200). `GET /api/stats` returns live Atlas data (median request-to-hand 0.44 s, instruments out). Ubuntu `ufw` was allowing only port 22; 80 and 443 are open now. `SCRUB_PUBLIC_URL` is not set until the domain exists. HTTPS is not on yet.

### GoDaddy
- For: the domain on the QR code at the table. Track: MLH GoDaddy Registry.
- Get it: the MLH GoDaddy Registry offer on the DubHacks sponsor page, sign in, buy one short domain. My Products, the domain, Manage DNS, type A, name `@`, value `144.202.95.111`, TTL 600. Type CNAME, name `www`, value `@`, TTL 600. Then `powershell -File deploy/enable_https.ps1 -Target root@144.202.95.111 -Domain the-domain.tld -Email you@school.edu`.
- Now: NOT BOUGHT. No domain name is in the repo. The page is only on the IP above.

## deploy results on Brandon's Windows PC (Oct 17, 11 PM)

`python -m deploy` from this PC. MongoDB on this PC is set. The arm and voice keys are still only on the arm Mac (see the table above).

| Service | Result | Exact fix |
| --- | --- | --- |
| Perceptron robotics | FAIL missing `PERCEPTRON_TEAM_API_KEY` | Paste the robotics team key into this PC's `.env` only if this PC will train. The arm Mac already has a key and it returns HTTP 401. Ask Perceptron staff for the team key, then `.venv/bin/python -m arm.train deployments` on the Mac must print JSON. |
| Perceptron detect | FAIL missing `PERCEPTRON_API_KEY` | Put the vision key in this PC's `.env`. It is set on the arm Mac. Then `python -m vision.lighting --check-api`. |
| Gemini | FAIL missing `GEMINI_API_KEY` | Copy the working key from the voice machine's `.env`. Check: `python -m deploy` shows Gemini PASS. |
| ElevenLabs | FAIL missing `ELEVENLABS_API_KEY` | Copy the working API key from the voice machine. `ELEVENLABS_AGENT_ID` is still empty everywhere: create the agent (steps above) and paste the id. |
| Photon | FAIL missing `PHOTON_API_KEY` | This PC has neither Photon nor Spectrum names. The Mac has `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET`. Copy those, or set `PHOTON_API_KEY` and `PHOTON_PROJECT_ID`. The iMessage line is still not found. |
| MongoDB Atlas | PASS ping ok | Done on this PC. |
| Hugging Face | FAIL missing `HF_TOKEN` | https://huggingface.co/settings/tokens, New token, Write, name it scrub. Put `HF_TOKEN` and `HF_USER` in the arm Mac `.env`. |
| controller :8000 | PASS HTTP 200 | Already running on this PC. |
| vision :8001 | FAIL ConnectError | Nothing is listening. Start `python -m vision` (or `--fake` with no overhead camera). |
| voice :3000 | FAIL ConnectError | Start `cd voice && npm run dev` on the voice machine. The keys above have to be in that `.env` first. |

### Devpost
- For: the submission. Tracks it should have ticked (from `docs/DEVPOST.md`): Perceptron, Photon, MLH Gemini API, MLH MongoDB Atlas, MLH Tiger Data, MLH Backboard, MLH Vultr, MLH GoDaddy Registry, MLH Commit Fellowship, MLH DEV writing, plus the ElevenLabs voice prize if offered.
- Get it: https://devpost.com, the DubHacks '26 project, Edit, Manage team, Edit tracks. Text is in `docs/DEVPOST.md`.
- Now: team done per `docs/SETUP.md`. Tracks ticked and draft submitted: NOT CONFIRMED (STATUS E5 is unticked; the draft is due Sat 10:00 PM internal, 10:30 PM official). A person must open the project and check. Final submit with video by Sun 9:30 AM internal, 10:00 AM official.

### MLH Commit Fellowship form
- For: the fellowship track. Get it: https://mlh.link/commit-fellowship-form. Submit after the Devpost final (Anish). Now: NOT DONE.

### Tiger Data (`TIGER_DATABASE_URL`)
- For: the handoff time series. Track: MLH Tiger Data. Page: http://127.0.0.1:8080/series.html once `python -m ledger serve` is running.
- Get it, in this order:
  1. Open https://console.cloud.timescale.com (Tiger Cloud) and sign up with the team email. Use the MLH Tiger Data offer if it is on the DubHacks sponsor page.
  2. New service. Pick the free or smallest service, region closest to Seattle, Postgres. Create service.
  3. When it is ready, Download the config. That file is the only time the password is shown. Copy the service URL. It looks like `postgresql://USER:PASSWORD@HOST:PORT/tsdb?sslmode=require`.
  4. Put that whole URL in the repo-root `.env` as `TIGER_DATABASE_URL=...` with no quotes and no spaces. Do not commit `.env`.
  5. From the repo root: `.venv/bin/pip install -r ledger/requirements.txt` (needs `psycopg`), then `.venv/bin/python -m deploy`. Tiger Data should say PASS and "connected". The series page then says the minutes are read from the hypertable. The first handoff creates `scrub_handoff`.
- Needed in: the machine that runs the controller and `python -m ledger serve`.
- Now: MISSING on this Mac. The page works without it and says so.

### Backboard (`BACKBOARD_API_KEY`, `BACKBOARD_ASSISTANT_ID`)
- For: notes of what was asked, and answers for what usually comes next. Track: MLH Backboard. Page: http://127.0.0.1:8080/memory.html.
- Get it, in this order:
  1. Open https://app.backboard.io and sign up. Pick the API path (not only the desktop app).
  2. Create an API key. Copy it once into `.env` as `BACKBOARD_API_KEY=...`.
  3. Create an assistant named Scrub. System prompt: "You are Scrub. Answer in one sentence what instrument usually comes next. Use only the memories you have."
  4. Copy the assistant id (a UUID) into `.env` as `BACKBOARD_ASSISTANT_ID=...`.
  5. `.venv/bin/python -m deploy`. Backboard should say PASS and HTTP 200. Ask on the memory page. The answer line should say it came from Backboard.
- Needed in: the machine that runs `python -m ledger serve`.
- Now: MISSING on this Mac. The page answers from the local ledger until both names are set.

### DEV (dev.to)
- For: the MLH DEV writing track. Get it: https://dev.to, sign in, New Post, paste the writeup from `docs/DEVPOST.md` (the last section), add the hackathon tag the MLH page asks for, publish, and put the link in Devpost. Now: NOT DONE (nothing found here).
