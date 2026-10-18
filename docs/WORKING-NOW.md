# Working now (Sat 10:10 PM)

Who is editing what right now, so nobody collides. Caiden's comb pass (`docs/COMB-PROMPT.md`) is running with several agents. Its commits land on `main` one item at a time over the next hour or so. When it finishes, this file is deleted and `docs/STATE.md`, `docs/HARDWARE-TODO.md` and `docs/ACCOUNTS-TODO.md` take over.

## Deadline first

**Evan: the Devpost draft is due 10:30 PM.** `docs/DEVPOST.md` on `main` is the final rewrite: it matches the new pitch, every statistic has a source, dental is gone, and it names you as the submitter. Paste it into Devpost and submit the draft now. Fill the `[measured]` numbers on Sunday before 9:30 AM.

## In flight: don't edit these until the comb commits them

| Area | Files being edited | By |
| --- | --- | --- |
| Controller and arm safety, real-arm readiness | `controller/core.py`, `controller/test_flows.py`, `arm/backends.py`, `arm/perceptron.py`, `arm/real_arm.py`, `arm/streaming.py` | comb A |
| Voice, vision, contracts | `voice/src/*`, `voice/scripts/*`, `voice/README.md`, `vision/*.py`, `docs/CONTRACTS.md` | comb B |
| Full stack on the sim arm, docs commands | `README.md` "Running it", `docs/BRINGUP.md`, `docs/TRAINING.md`, folder READMEs (only where a command is wrong) | comb D |
| Final pass | `docs/AUDIT.md` (new), `docs/STATUS.md`, `docs/LEFT.md` | Caiden, at the end |

## Already pushed by the comb (Evan, your folders changed)

- `ledger.stats()` leaves rows tagged `fake_arm` or `sim` out of the rates and medians. The count (`out`) still reads every event. `GET /api/stats?sim=1` includes them. The controller starts sending `fake_arm` with comb A's commit, so fake-arm runs stop moving the tables.
- `ledger/serve.py`: CORS on the read-only `/api/*`, `HOST` env (the server binds 127.0.0.1 behind nginx), `/favicon.ico` 204.
- One server install path: `deploy/setup_public.sh` (nginx on 80, python on 127.0.0.1:8080). `ledger/scrub-public.service` is deleted. `ledger/install_public.sh` calls the deploy one. `bash ledger/push_public.sh root@SERVER_IP [domain you@school.edu]` sends only `MONGODB_URI` and `SCRUB_PUBLIC_URL` and never `buffer.jsonl`.
- 3 s timeouts on every polling fetch in `dashboard/app.js`, `dashboard/tablet.js`, `ledger/public/app.js` and `ledger/public/cases.js`. Phone table spacing in `ledger/public/style.css`.
- `python -m deploy` reads the Photon keys under their Spectrum names, and passes the vision key on HTTP 400 (the 1x1 test image).

## Done: the pitch and one story (pushed)

`docs/PITCH.md` (four speakers; Evan has the lighting test and the tables at 1:40 and runs the lamp and the trays), `docs/DEMO.md`, `docs/QNA.md` (51 questions), `docs/SLIDES.md`, `docs/NEXT.md` (ROI math fixed: break-even is 22 OR minutes a month per room), `docs/DEVPOST.md`, `docs/DEV-POST.md`, `docs/README-PUBLIC.md`, and the visible text in `ledger/public/index.html` and `card.html`. Every number links to its source; unconfirmed numbers were dropped. Read your lines in PITCH.md.

## Free for Evan now (your folders, nobody else on them)

In order:

1. **E5:** submit the Devpost draft (above).
2. **`MONGODB_URI`** into this Mac's `.env` (you have it from E3). Check with `.venv/bin/python -m deploy`: MongoDB Atlas should say PASS. The buffered events upload on the next connection.
3. **E6 with Brandon:** the Vultr box and the GoDaddy domain (steps in `deploy/README.md` and `docs/ACCOUNTS-TODO.md`). Then `bash ledger/push_public.sh root@SERVER_IP your-domain you@school.edu` and open `https://your-domain/`.
4. **`docs/DATA-LOG.md` targets:** they say 15 hand-out / 10 put-back per item, but `docs/TRAINING.md` says 20/10 for surgical and 15/10 for bench. Make DATA-LOG match TRAINING.
5. **Empty tables on purpose:** once fake-arm rows drop out, the success tables on the dashboard and public page are empty until the first real-arm tries. Give them a clear empty state ("No real-arm tries yet") in `dashboard/app.js` and `ledger/public/app.js`, not a blank table or NaN.
6. **E4 during recording:** log each batch as Anish records (`docs/HARDWARE-TODO.md` step 6): `python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "..."`.
7. **E7 prep:** the backup video. `python -m controller.run_all backup` plays a full run on the sim arm. Screen-record it with the dashboard open, so we have a video if the arm fails at judging (Q4 in `docs/LEFT.md`).

Anish is also running an integration pass (commit `c4fffd9`: sim, vision/tray.py, voice test, `docs/QA.md`). Check `git log -5` before starting.
