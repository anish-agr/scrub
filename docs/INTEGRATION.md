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
| Perceptron OCR: count sheet | Reads the printed count sheet (tray, expected, handwritten initial and closing counts) | `vision/reading.py` `read_count_sheet`, vision `POST /read/count_sheet`, controller `read_sheet` | `python -m vision.reading count_sheet explore/recognition/props/count_sheet_surgical_filled.png --setting surgical` | PASS on rendered props (Oct 18, 2 AM): 5 of 5 sheets correct (blank, handwritten, 20 degrees), 1.8 to 2.3 s. Real photos of the printed sheet not taken yet |
| Perceptron OCR: pack labels | Reads lot and expiry, flags expired packs | `vision/reading.py` `read_pack_label`, controller `read_pack` | `python -m vision.reading pack_label explore/recognition/props/pack_labels_angle.png --setting surgical --today 2026-10-18` | PASS on rendered props: 4 of 4 labels, flat and angled, expired mayo scissors flagged, 2.4 to 2.7 s |
| QR and OCR: tray tag | Names the tray and switches the setting | `vision/reading.py` `read_tray_tag`, controller `read_tray` | `python -m vision.reading tray_tag explore/recognition/props/tray_tag_surgical.png` | PASS. QR 0.03 to 0.05 s; text-only crop by Perceptron 1.0 s. A no-tag frame now answers "I can't read the tray tag." (2 of 2, after a fix for an invented tray) |
| Gemini: OCR fallback | Reads the same paper when Perceptron fails | `vision/reading.py` (Gemini backend) | `pytest -q vision/test_reading.py` | PASS. Forced Perceptron timeout, Gemini answered correctly in 1.2 s; correct on all renders, 1.7 to 2.9 s (one 12.1 s) |
| Voice to reading | "read the count sheet", "what tray is this", "read the pack" | `voice/src/parse.ts`, `voice/src/turn.ts`, `controller/reads.py` | `cd voice && npm test`; live chain voice to controller to vision to Perceptron | PASS (Oct 18, 2 AM). Spoken answer in the same reply, 1.0 to 2.5 s. Camera frames of real paper not tested yet |
| Perceptron captions: event clips | Captions each 3 s clip (5 frames), `agrees` with the controller's event | `vision/clips.py`, controller `POST /vision/caption`, ledger replay | `python -m vision.test_clips`; one fake-arm handover with `VISION_AUTO_CAPTION=1` | PASS. Captions 0.8 to 2.3 s; picked and handed captions written to the ledger as `caption` records. A still-arm clip labeled handed gives `agrees: false` |
| Perceptron: dataset QA | Flags dark, failed-grasp and dropped episodes before upload | `explore/dataset/qa_video.py` | `python -m explore.dataset.qa_video --dataset ~/scrub-dataset --report qa.md` | PASS. 7 episodes, 7 calls, median 2.2 s: grasp failed on 0, 2, 3, 5, 6; dropped on 2, 3; 0 dark |
| Video tool: captions | Ranks takes with captions as a second signal | `video/captions.py`, `video find` | `python -m unittest video.test_video` | PASS (5 new tests). 2 older tests need the SO-101 model and Playwright Chromium |
| Gemini: doctor | Plain-language fix list | `controller/doctor.py` `ask_gemini` | `python -m controller.doctor` | PASS. Printed the "what to do" lines |
| ElevenLabs: key and speech | Arm speaks in the room | `explore/arm_voice.py` `_audio` | `python -c "from explore import arm_voice as v; print(v._audio('check'))"` | PASS. 22 KB mp3 returned |
| ElevenLabs: voice agent on the call | Phone voice, Custom LLM to `voice/` | `voice/scripts/agent.ts`, `voice/src/server.ts` `/v1/chat/completions` | `cd voice && npm run agent -- status`; `VOICE_URL=https://<tunnel> npm run say -- "hemostat"` | PASS (Oct 18, 2:40 AM) for the agent and the Custom LLM path; no real phone call yet (no callable number, Photon row). Agent `Scrub`: Flash v2 voice, interruptions on, no auth or allowlist, no concurrency limit, prompt carries `Caller:` and `Conversation:`. Through a cloudflared tunnel: "hemostat", "got it", "count", "take back the hemostat", "read the count sheet", "what tray is this", "read the pack", "stop" all answered (reads need a controller started after 20f055f). Second conversation at once: "Scrub is busy with another call", its "stop" still stopped the arm. No key: 401. Browser call without a number: `https://elevenlabs.io/app/talk-to?agent_id=<ELEVENLABS_AGENT_ID>` (page loads; not tried with a mic) |
| Photon: texts | End-of-case summary, inbound texts | `voice/src/summary.ts` `getPhoton`, `voice/src/texts.ts` | `cd voice && npm test`; `npm run photon -- status` | PARTIAL, counted FAIL. Spectrum keys work (HTTP 200, `[texts] listening`). 0 users, so no recipient. A shared line only takes texts from its registered user: `npm run photon -- add-user +1<phone>` (Anish), then a text and "end of case" prove it. Replay link falls back to `http://<SCRUB_SERVER_IP>/case.html?id=` when `SCRUB_PUBLIC_URL` is empty |
| Photon: phone number and call | SIP inbound into ElevenLabs | `voice/scripts/photon.ts`, `voice/README.md` Call setup | `cd voice && npm run photon -- status` | FAIL: no number that can take calls. Done by API: voice platform on, inbound route `sips:sip.rtc.elevenlabs.io:5061`. Photon docs: "Shared lines cannot take calls"; we are on the shared plan, so `setup` never gives a callable number. Left (Anish, needs a purchase): buy an SMS number in the Photon dashboard (or a Business dedicated line), then `npm run photon -- use-line +1...` and call (`voice/README.md`, Anish steps) |
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

Path: phone -> Photon SMS or dedicated number (SIP) -> `sips:sip.rtc.elevenlabs.io:5061` -> ElevenLabs agent `Scrub` -> Custom LLM `https://<tunnel>/v1/chat/completions` (Bearer `VOICE_LLM_SECRET`) -> Gemini or the local match -> controller -> arm -> `say` lines streamed back and spoken. "end of case" texts the summary on Photon. `python -m controller.run_all --real` starts the tunnel, re-points the agent at each new URL (retried, then `!!` lines), checks `GET <url>/health` through the public URL, prints `phone (call it)` and `no phone (talk)`. Not yet proven: a real call (no callable number) and a real text (no Photon user).

Turn time, measured Oct 18 2:30 AM through a cloudflared tunnel, fake arm, Gemini on (`[timing]` lines; medians in voice `GET /health` `timing` and on `/ops`). 9 turns Gemini parsed: Gemini median 624 ms (509 to 818), controller 1 ms, first spoken line 772 ms at the server, about 0.9 s at the caller end of the tunnel. Local matches ("stop", "got it", reads): under 25 ms at the server; "stop" 0.07 to 0.11 s through the tunnel. Not included: ElevenLabs speech to text and text to speech, which only a real call measures.

No phone network: `http://localhost:3000/talk` (push to talk in the browser, posts to `/heard` like a call turn) or `cd voice && npm run talk`. Linked on `/ops` and printed by `run_all`.


## Track claims

Supported by evidence now:
- MLH MongoDB Atlas: ledger and thermal telemetry in Atlas.
- MLH Gemini API: voice parse, doctor, bench.
- MLH Vultr: the page is live on the server.
- Perceptron vision: detect runs in `vision/`, with the bench numbers above.
- ElevenLabs: key works and the arm speaks with it in the room. The phone agent (Custom LLM to `voice/` through the tunnel) answers every call phrase through the public URL in about 0.9 s (Gemini) or 0.1 s ("stop"). No phone call yet.

Perceptron perceptive track (their vision models), what Scrub uses now, each with its proof:
- Localization (detect): tray items and the blocked path, `vision/tray.py`. Proof: `python -m vision.lighting --check-api`.
- OCR: count sheet, tray tag text, pack labels, `vision/reading.py`. Proof: `python -m vision.reading count_sheet explore/recognition/props/count_sheet_surgical_filled.png --setting surgical`.
- Captioning and video events: 5-frame clip captions with `agrees`, `vision/clips.py`; episode QA, `explore/dataset/qa_video.py`. Proof: `python -m vision.test_clips` and the qa_video command above.
- Not used: tracking.
Accuracy on real photos is pending (`docs/RECOGNITION.md`, "Real tray"). Anish decides whether to enter the perceptive track as one of our 3 sponsored tracks.

Supported only once someone fixes a missing item:
- Perceptron robotics: the pipeline works offline and the key now returns 200, but there is no deployment. Claim "fine-tuned" and live inference only after run 1 and a model-driven pick are recorded.
- Photon: claim only if a real text or call goes through. Calls need a bought SMS number (shared lines cannot take calls); texts need Anish added as a user (`npm run photon -- add-user`). Steps in `voice/README.md`.
- MLH GoDaddy: needs a bought domain and DNS.

Drop unless the keys land before 10:00 AM:
- MLH Tiger Data and MLH Backboard: no key exists, nothing real runs against either service. The pages work from the local ledger, which is not those products. Remove both from Devpost and `team/DEVPOST.md` (lines 25 and 26, and the built-with list at line 116).
- Hugging Face as a sponsor claim: the token works now, but it is only storage for the dataset. Not a track.
- MediaPipe as a headline claim: it works, but is a supporting detail.
