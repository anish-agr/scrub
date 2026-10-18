# Reading and recognition pass: OCR, real-frame recognition, video understanding (prompt for Caiden's Claude, Opus 5.5)

Start this after the full pass (`NEXT-PASS-PROMPT.md`) gives its final report. Say to Claude Code on the arm Mac: "Pull, then follow team/OCR-PROMPT.md exactly. Use as many subagents as it needs and take as long as it needs."

---

I'm Caiden on team Scrub at DubHacks '26. The full pass is done. This pass makes Scrub read and understand everything the cameras see, and turns it into data the product uses. Pull first. Read `docs/OVERVIEW.md`, `docs/RECOGNITION.md`, `docs/PERCEPTRON-ROBOTICS.md` (the vision API: detect, OCR, captions, video and event clipping through `/v1/chat/completions`), `docs/INTEGRATION.md`, `docs/CONTRACTS.md`, and `vision/README.md`.

## How to work

Same rules as the full pass: you orchestrate subagents in parallel with strict file scopes (Opus for `controller/`, `vision/`, `voice/`; Sonnet for scripts, docs, pages, props), they don't commit, you review, test and commit one item at a time, `git pull --rebase` before each push. Never print or commit keys. Don't touch the arm motion code or the training run in progress. Finish everything without asking me; anything a person must do (take photos, print a sheet, write on it) goes on a short list with exact steps, and you keep working while it waits. Write new docs and UI text plainly (the writing rules in `NEXT-PASS-PROMPT.md`).

## Why this matters

`docs/RECOGNITION.md` was a smoke test: 3 tiny crops and 2 synthetic trays, no real tray photo, no printed text, no gloved hand. Nothing there is evidence yet. This pass gets real data, measures again, and adds the reading features that make the story stronger: Scrub reads the same paper the OR team already uses.

## Phase 1: real data (do this first; it unblocks everything)

1. `explore/recognition/capture.py`: grabs labeled frames from the overhead, side and wrist cameras (and accepts phone photos dropped in a folder). One key per label. Writes `data/recognition/<set>/` with `labels.json` in the format the bench already reads.
2. The capture list for a person, in `docs/RECOGNITION.md` ("Photos to take", about 15 minutes):
   - the full surgical tray from the overhead camera; then one photo with each instrument removed; bright, normal and dim light
   - each instrument alone in its slot, and in the gripper (wrist camera)
   - a gloved open hand 15 to 25 cm over the tray, blue or white nitrile, three lights, 10 frames each
   - the printed props from Phase 3 (count sheet, tray tag, a pack label), flat and at an angle, clean and with handwriting
3. Rerun the bench (`python -m explore.recognition.bench --images data/recognition/<set>`) on the real set. Replace the smoke-test tables in `docs/RECOGNITION.md` with the real numbers and keep the old ones in a short "smoke test" note.

## Phase 2: finish recognition and apply it

- Per method and per item: found rate, box IoU, accuracy for "what's missing", latency, at each light level. Methods: Perceptron detect (as `vision/tray.py` calls it), Perceptron detect on a smaller or cropped frame, Gemini tray check with the enum of item names, Gemini with a reference crop of each item in the prompt, MediaPipe on the gloved hand.
- Fix the latency limits from evidence: `PerceptronDetector` timeout, the 3 s stale cutoff in `GET /tray_check`, frame size sent.
- If one method or a combination is clearly better on real frames, wire it in: `vision/tray.py` and `controller/traycheck.py` (for example Perceptron first, Gemini as the second opinion when Perceptron misses an item). Show which method answered in the event and on the ops page.
- Write the recommendation from the real numbers.

## Phase 3: reading (OCR), each one useful to the product

Build each with Perceptron OCR first and Gemini as the fallback, return structured JSON, store it in the ledger, and show it on the dashboard and ops page. Each one gets a test with a saved photo.

1. **The count sheet.** OR teams count instruments on a printed sheet. Make a printable count sheet from `settings/<tray>.json` (`ledger/` already prints a table card; reuse that style), with columns for the initial count and the closing count that a person fills in by hand. Scrub reads a photo of it: tray name, items, expected quantities, and the handwritten counts. That sets the expected list and the baseline count for the case. At "end of case", Scrub compares its own count to the sheet's and says where they disagree. Voice: "read the count sheet".
2. **The tray tag.** Read the printed tray label or the QR tag on the tray (QR first, OCR fallback) and switch the setting automatically (surgical or bench), with a spoken confirmation. Voice: "what tray is this".
3. **Pack labels.** Read a printed sterile pack label (item, lot, expiry date, the sterilization indicator's printed text). Log it with the case, and warn when a date has passed. Make a sample label to print. Voice: "read the pack".
4. **Anything else on the table with text** that the bench finds in the real photos and is useful. Write what you found and skip what isn't.

Add the new commands to `voice/` (the Gemini command schema, with the same "fixed list, never invent" rule) and to `docs/CONTRACTS.md` as optional fields. Add the words to the voice tests.

## Phase 4: video understanding (captions and events)

Use Perceptron's video and caption endpoints:
1. **Event clips:** for each controller event (`picked`, `handed`, `released`, `returned`, `stopped`, `missed`), `vision/` already saves a 3 s clip. Caption it, and store the caption in the ledger so the case replay reads like a log ("hemostat handed to the surgeon's right hand, 6.4 s"). Check that `POST /clips/label` works with the real API, not only the fallback.
2. **Dataset QA for training:** caption or event-clip each recorded episode and flag ones where the grasp failed, the item dropped, or the camera was dark, before anything uploads. Add it to `explore/dataset/qa` as an optional check with its own report. This protects our 2 training jobs.
3. **The video tool:** give `python -m video find` the captions as a second signal for picking the best takes, next to the ledger events.

## Phase 5: tracks, integration and claims

- Perceptron has two tracks: robotics (ours) and perceptive (their vision models: localization, OCR, captioning, tracking, video events). Write in `docs/INTEGRATION.md` exactly which perceptive capabilities Scrub now uses, with the proof command for each, so Anish can decide whether to also enter the perceptive track (we can enter at most 3 sponsored tracks).
- Add rows to `docs/INTEGRATION.md` for each new feature, with PASS or FAIL from running it now.
- Update `docs/OVERVIEW.md` (what Scrub does), `team/DEMO.md` (a 20-second "Scrub reads the count sheet" beat, only if it works on the real sheet), and `docs/RECOGNITION.md`. List Devpost and pitch lines that can now be added, with the measured numbers, in the final report.

## Before you stop

Run every test. Push everything (`git status` clean, nothing ahead of `origin/main`). Update `team/LEFT.md` (or `team/LEFT.md` if it hasn't moved): add what's left from this pass, remove what's done.

## Final report

1. The real data set: what was captured, how many images per label.
2. The real recognition table and what changed in `vision/` and `controller/`.
3. Each reading feature: works or not on the real props, accuracy, latency, the voice command.
4. Video captions and dataset QA: results on our real episodes.
5. New `docs/INTEGRATION.md` rows and the perceptive-track answer.
6. New pitch and Devpost lines with numbers.
7. What a person has to do next, in order, with who.
