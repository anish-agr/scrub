# Integration: every tool, proven

Run Oct 18, 1:00 AM on the arm Mac. The arm and cameras were not touched (the recorder holds them). Keys are named, never shown. A row says PASS only when the command below printed success on this run.

`.venv/bin/python -m deploy` is the account check. Add `SCRUB_SERVER_IP=144.202.95.111` to `.env` so it can see the Vultr page.

| Tool | What it does in Scrub | Called from | Proof command | Result |
| --- | --- | --- | --- | --- |
| Perceptron robotics: API and key | Datasets, fine-tune jobs, deployments | `arm/perceptron.py` (`capabilities`, `train`), `arm/train.py` | `python -m arm.train capabilities` | PASS. HTTP 200, `ready_for_training: true` |
| Perceptron robotics: fine-tune pipeline | Upload dataset, register, train, deploy | `arm/pipeline.py`, `arm/upload_dataset.py`, `arm/train.py` | `python -m arm.train self-test`; `pytest -q arm/test_pipeline.py arm/test_perceptron.py` | PASS offline (9 self-tests, 27 unit tests). No job submitted by design |
| Perceptron robotics: live inference | The arm runs the deployed model | `arm/real_arm.py` `Arm.run_skill` | `python -m arm.train deployments` | FAIL. 0 deployments; `PERCEPTRON_DEPLOYMENT_ID` names nothing. Needs run 1 to finish (Caiden). Also `SO101_PORT` empty: set when the follower is plugged in (Caiden) |
| Perceptron vision | Detect tray items and the hand | `vision/service.py`, `vision/tray.py`; `explore/recognition/bench.py` `run_perceptron` | `python -m vision.lighting --check-api`; `python -m explore.recognition.bench --repeat 1` | PASS. detect HTTP 200 in 1.8 s; bench ran (found rate 0.4 on 5 synthetic cases, median 2.7 s). Accuracy is weak, see Track claims |
| Gemini: words to a command | Parses what was said | `voice/src/parse.ts` `geminiParse` | `cd voice && npm test`; `python -m deploy` (Gemini row) | PASS. HTTP 200, voice tests passed |
| Gemini: tray check from an image | Names items in a tray photo | `explore/recognition/bench.py` `run_gemini` only | `python -m explore.recognition.bench` | PASS in the bench (check_tray found 1.0, accuracy 0.5 on 2 cases). Not in the live path: `controller/traycheck.py` uses vision detect, not Gemini |
| Gemini: doctor | Plain-language fix list | `controller/doctor.py` `ask_gemini` | `python -m controller.doctor` | PASS. Printed the "what to do" lines |
| ElevenLabs: key and speech | Arm speaks in the room | `explore/arm_voice.py` `_audio` | `python -c "from explore import arm_voice as v; print(v._audio('check'))"` | PASS. 22 KB mp3 returned |
| ElevenLabs: voice agent on the call | Phone voice, Custom LLM to `voice/` | `voice/scripts/agent.ts`, `voice/src/server.ts` `/v1/chat/completions` | `cd voice && npm run agent -- status`; `npm run agent -- test "hemostat"` | PASS (Oct 18, 1:50 AM). Agent `Scrub` created by API, `ELEVENLABS_AGENT_ID` set, Custom LLM = cloudflared tunnel `/v1` with secret `scrub_voice_llm`. ElevenLabs' simulated call reached our server through the tunnel (`[heard] hemostat`, `[command] handover hemostat`, sim arm moved); the simulate API itself returned HTTP 500 (deprecated endpoint). No real phone call yet |
| Photon: texts | End-of-case summary, inbound texts | `voice/src/summary.ts` `getPhoton`, `voice/src/texts.ts` | `cd voice && npm test`; `curl :3000/health` (`keys.photon`) | PARTIAL, counted FAIL. Keys work (Spectrum API HTTP 200; voice logs `[texts] listening on the Photon line`). No real text: the project is on the shared iMessage plan with 0 users, so there is no line and no recipient until `npm run photon -- setup +1...` (Anish) |
| Photon: phone number and call | SIP inbound into ElevenLabs | `voice/scripts/photon.ts`, `voice/README.md` Call setup | `cd voice && npm run photon -- status` | PARTIAL, counted FAIL. Done by API: voice platform on, inbound route `sips:sip.rtc.elevenlabs.io:5061`. No line yet: shared plan, a line is assigned per user (dedicated lines are Business plan). Left: `npm run photon -- setup +1<Anish's phone>`, then call |
| MongoDB Atlas: ledger | Every event, success tables | `ledger/logbook.py`, `controller/core.py` | `python -m deploy`; `python -m controller.run_all check` | PASS. ping ok, 33,814 event docs in `scrub.events`; check wrote 12 lines for a fake handover |
| MongoDB Atlas: thermal | Arm temperatures | `explore/thermal_log.py` `_insert` | pymongo count on `scrub.thermal` | PASS. 2,148 docs |
| Vultr | Public judge page | `deploy/setup_public.sh`, `ledger/serve.py` | `curl http://144.202.95.111/api/stats`; `python -m deploy` (Vultr row) | PASS. HTTP 200, live Atlas numbers. HTTP only |
| GoDaddy | Domain on the QR code | `deploy/enable_https.ps1` | none | FAIL. No domain bought; `SCRUB_PUBLIC_URL` empty, so the replay link in the text has no host. Evan or Brandon buys it |
| Tiger Data | Handoff time series | `ledger/tiger.py` | `python -m deploy` | FAIL. missing key `TIGER_DATABASE_URL`, Evan or Brandon adds it. The series page runs from the local ledger |
| Backboard | Memory notes and next-item answer | `ledger/memory.py` | `python -m deploy` | FAIL. missing keys `BACKBOARD_API_KEY` and `BACKBOARD_ASSISTANT_ID`. Page answers from the local ledger |
| Hugging Face | Dataset repo Perceptron trains from | `arm/record.py` (repo name), `arm/train.py` `dataset_url`, `arm/pipeline.py` | `python -m deploy` (Hugging Face row); write check: create and delete a private dataset repo with `huggingface_hub.HfApi` | PASS (Oct 18, 1:40 AM). `HF_TOKEN` and `HF_USER=caidenm11` set on the arm Mac from Caiden's Hub login; whoami HTTP 200; a private dataset repo was created and deleted |
| MediaPipe | Hand at the handoff spot | `vision/hand.py` `HandTracker` | load the real landmarker on a blank frame; `pytest -q vision/test_vision.py -k hand` | PASS. Real model downloaded and ran (no hand on a blank frame, as expected); 7 hand tests. `vision/models/` is empty here, so the first `python -m vision` needs internet |
| MuJoCo | Sim backup, joint reconstruction | `sim/`, `video/reconstruction.py` | `python -m controller.run_all backup --offline --no-open`; `python -m unittest video.test_video` | PASS. Sim stack and scripted run start; 25 video tests |
| `video/` | Demo cut from ledger and joints | `video/__main__.py` | `PLAYWRIGHT_BROWSERS_PATH=$PWD/data/video/browser python -m video --root data/video/integration-proof demo-assets --seconds 3` | PASS for `demo-assets` (clip, events, joints written). FAIL for "reads our real ledger and dataset paths": every command takes `--events` and `--input` from the caller, with no default to `ledger/buffer.jsonl` or the recorded dataset, and `demo-assets` is synthetic |
| Stack | One command starts everything | `controller/run_all.py` | `python -m controller.run_all --base-port 8100 --ledger --judge --skills auto --offline` | PASS on fake arm. Controller, vision, voice, ledger and every URL answered; Ctrl-C stopped all |

Also seen: voice on :3000 stopped answering during this run (not stopped by these commands). Restart with `cd voice && npm run dev` or `run_all`.

## Phone call

Path: phone -> Photon line (shared iMessage line, SIP) -> `sips:sip.rtc.elevenlabs.io:5061` -> ElevenLabs agent `Scrub` -> Custom LLM `https://<tunnel>/v1/chat/completions` (Bearer `VOICE_LLM_SECRET`) -> Gemini or the alias match -> controller -> arm -> `say` lines streamed back and spoken. "end of case" texts the summary on the same Photon thread. `python -m controller.run_all --real` starts the tunnel, re-points the agent at each new URL, prints `phone (call it)`, and runs the sim arm when the real one is busy. Proven Oct 18 through a cloudflared tunnel: `/health` 200, a Custom LLM turn with no key 401, "hemostat" moved the sim arm (`run_all --real --offline --base-port 8440`, `SO101_PORT` empty so the sim), ElevenLabs' own simulated call reached the server. Not yet proven: a real phone call and a real text (needs the line: `voice/README.md` Call setup, Anish steps).


## Track claims

Supported by evidence now:
- MLH MongoDB Atlas: ledger and thermal telemetry in Atlas.
- MLH Gemini API: voice parse, doctor, bench.
- MLH Vultr: the page is live on the server.
- Perceptron vision: detect runs in `vision/`, with the bench numbers above.
- ElevenLabs: key works and the arm speaks with it in the room. The phone agent (Custom LLM to `voice/` through the tunnel) is created and answered a "hemostat" turn that moved the sim arm. No phone call yet.

Supported only once someone fixes a missing item:
- Perceptron robotics: the pipeline works offline and the key now returns 200, but there is no deployment. Claim "fine-tuned" and live inference only after run 1 and a model-driven pick are recorded.
- Photon: claim only if a real text or call goes through. Needs a line from the shared pool, which appears once Anish is added as a user (`npm run photon -- setup`, in `voice/README.md`).
- MLH GoDaddy: needs a bought domain and DNS.

Drop unless the keys land before 10:00 AM:
- MLH Tiger Data and MLH Backboard: no key exists, nothing real runs against either service. The pages work from the local ledger, which is not those products. Remove both from Devpost and `team/DEVPOST.md` (lines 25 and 26, and the built-with list at line 116).
- Hugging Face as a sponsor claim: the token works now, but it is only storage for the dataset. Not a track.
- MediaPipe as a headline claim: it works, but is a supporting detail.
