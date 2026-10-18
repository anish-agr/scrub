# Chat D: pull and analyze everything in MongoDB (training data, handoffs, heat, reads)

Say to a new Claude Code chat on the arm Mac: "Pull, then follow team/RUN-DATA.md exactly."

---

I'm Caiden on team Scrub at DubHacks '26: an SO-101 arm that passes surgical instruments by voice. **We're on a hard time crunch**: it's about 2 AM Sunday, the Devpost locks at 10:00 AM (submit by 9:30), judging at 10:30. This chat turns what's in MongoDB into decisions for the other chats and into real numbers for the pitch, the Devpost and the judges (MongoDB Atlas is one of our tracks).

## How to work (read twice)

- **Use subagents in parallel:** one per collection, one for the training-data report, one for the page, one for tests. You orchestrate and review. Sonnet is fine for most of this; Opus for anything that changes `controller/` or `ledger/`.
- Finish it. Don't ask me questions. Re-run the analysis every 30 minutes until 8 AM as new data arrives, and keep the outputs current.
- Other Claude chats run on this Mac (A trains, B the phone call, C the smart pick). Before editing a file run `git log -1 --format=%ar -- <file>`; skip it if someone changed it in the last 10 minutes. Commit small, `git pull --rebase` before every push. Never print or commit keys. `MONGODB_URI` is in `.env` (Anish can DM it if it's missing); read it from there, never write it anywhere else.
- You own new files: `explore/analysis/`, `docs/DATA.md`, `docs/media/data/`, `team/NOTES-DATA.md`, and a read-only data page (`ledger/public/data.html` on `design/scrub.css`, plus a read-only `/api/data` route in `ledger/serve.py` if needed). Read-only on MongoDB: never delete or edit a document.

## What's in MongoDB now (checked 2:05 AM, database `scrub`)

- `episodes` (8): one document per recorded episode from `explore/dataset/to_mongo.py`: `task`, `episode_index`, `length`, `fps`, `duration_s`, `joints`, `state`, `action`, `timestamp`, `video` (side and wrist file and time range), `handoff`, `dataset`. All 8 are `pick the spatula` test episodes.
- `events` (about 63,600): every controller event. Types: `command`, `step`, `picked`, `handed`, `released`, `returned`, `set_down`, `missed`, `stopped`, `count`, `error`, `read`, `caption`. Most are fake-arm or sim runs. Rows tagged `fake_arm` or `sim` are not real. Older rows from before those tags existed are not real either; find the date the tags started and treat earlier rows as test data.
- `thermal` (about 3,800): arm temperatures at 2 Hz: `t`, `kind`, `phase`, `temps`, `motors`, `session`, `seq`, `host`.
- `read` events: OCR results (count sheet, tray tag, pack labels) with method and latency; `team/` or `vision/` has `truth.json` for the printed props.

## Build

1. **`explore/analysis/` with one command, `python -m explore.analysis`,** that pulls everything and writes `docs/DATA.md`, charts in `docs/media/data/`, and machine-readable `data/analysis.json`.
2. **Training data report (for Chat A):** per episode: task, length, duration, camera fps, joint ranges and speed, gripper open and close times, idle time at the start and end, jerky or stalled spans, handoff fields, and a keep/re-record/drop verdict with the reason. Per task: count, lighting mix, how varied the start positions are. Flag anything that would waste a training job. Write the summary and the list of episodes to drop into `team/NOTES-DATA.md` for Chat A.
3. **Handoff report (for Chat C and the pitch):** real-arm rows only, per item, lighting and `skill_source`: tries, successes, success rate with Wilson 95% range, median and p90 request-to-hand time, retries, misses and why, stops. Write the exact queries and the per-item method ranking into `team/NOTES-DATA.md` so Chat C's picker reads the same numbers.
4. **Heat report (for the arm):** per motor: temperature against phase (idle, moving, holding), time to the guard limit while holding, cooling curves, which settings kept it cool. Plain recommendations into `team/NOTES-DATA.md`.
5. **Reading report:** OCR accuracy per kind against `truth.json`, latency, Perceptron against Gemini fallback.
6. **Pitch and Devpost numbers:** a short block in `docs/DATA.md` with every `[measured]` the pitch and `team/DEVPOST.md` need, each with its query and the time it was read. If a number has no real data yet, say "no real data yet" instead of a number.
7. **The data page** for judges, on the shared design system, read-only, phone friendly: live handoff table, heat chart, episode count and hours recorded, reads, and a plain note on what's real and what's simulation.

## Before you stop

Tests for the queries on a small fixture, everything pushed (`git status` clean, nothing ahead of `origin/main`), `docs/DATA.md` and `team/NOTES-DATA.md` current. Add what's left to `team/LEFT.md`. Report the headline numbers and what the other chats should change because of them.
