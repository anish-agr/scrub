# How to train Scrub (one page to share)

This is the plain version. Every command with every flag is in `docs/BRINGUP.md` sections 6 to 8. Run all of this on **the laptop the arm is plugged into**.

For a detailed operator-agent walkthrough, give the helper
[`docs/TRAINING-HANDOFF-PROMPT.md`](TRAINING-HANDOFF-PROMPT.md). It requires one-step
confirmation, discovers actual Windows ports/cameras/HF repo, tracks per-light
counts, logs each batch, and gates both training submissions on real evidence.

## The idea in four lines

1. A person moves the **leader** arm by hand. The **follower** arm copies it. That's teleoperation.
2. While that happens, LeRobot saves both cameras (`side`, `wrist`) and the six joint angles, 30 times a second. One try is one **episode**.
3. We upload the episodes to Hugging Face, and Perceptron fine-tunes its Isaac 0.5 model on them. One training run takes about an hour.
4. The trained model gets a **deployment id**. `arm/real_arm.py` sends it camera images and joint angles, and it sends back moves.

## Rules that matter

- **Only 2 training runs, ever.** Run 1 is the operating room tray. Run 2 is everything. Don't start a run until the dataset check passes.
- **One dataset for everything.** Same repo, same calibration, cameras never moved. Later batches add to it with `--resume=true`.
- **Use the exact instruction text** from `settings/surgical.json` and `settings/bench.json`: `pick the hemostat`, `return the hemostat`, and so on. The model is told the same words later.
- **Each episode is about 10 to 20 seconds.** "Pick" ends with the arm holding the item still at the carry pose. "Return" ends with the item in its slot and the arm back home.
- **Check the cadence line after each episode.** It must say about 30 Hz. If the laptop is slow, close other apps and re-record.
- Keys stay in `.env`. Never paste them anywhere.

## What to record

| Tray | Item | "pick the X" | "return the X" |
| --- | --- | --- | --- |
| Operating room | scalpel | 20 (to the safe spot) | 10 |
| Operating room | hemostat | 20 | 10 |
| Operating room | Mayo scissors | 20 | 10 |
| Bench | needle-nose pliers | 15 | 10 |
| Bench | wire cutters | 15 | 10 |
| Bench | hex key | 15 | 10 |

Split each row across bright (lamp on, close), normal (room lights) and dim (some lights off). Move the item a little in its slot between episodes. Every batch gets a row in `docs/DATA-LOG.md` (`python -m arm.record` writes it).

## Two people per session

- **Driver:** moves the leader arm. Smooth and slow, the same way every time.
- **Resetter:** puts the item back, changes the lighting, presses the keys: `n` ends an episode cleanly, `r` re-records a bad one, `q` finishes and saves.

## Steps

0. **Check the setup:** `python -m arm.check_setup --side C920 --wrist icspring` (Windows: `--side 0 --wrist 1`). Both arm ports, both cameras at 640x480 and about 30 fps, then a PASS line. Look at the saved test frames.
1. **Record** the operating room rows, one batch per instruction and lighting (`docs/BRINGUP.md` section 6). About 90 episodes, about 1.5 hours:
   `python -m arm.record --setting surgical --item hemostat --direction hand-out --lighting bright --episodes 5`
   (or `--task "return the hemostat"`; add `--print-only` to see the exact command first, and `--lerobot --follower <port> --leader <port> --side 0 --wrist 1` on the Windows laptop). It keeps one dataset (`<HF_USER>/scrub`, `~/scrub-dataset`, resumed automatically) and writes the batch's row in `docs/DATA-LOG.md`.
2. **Check** (section 7): replay episode 0 on the arm, then `python -m arm.train pipeline <dataset folder> --cadence-report <file> --check-only`. Fix anything it flags.
3. **Run 1** (section 8): `python -m arm.train pipeline ... --idempotency-key scrub-run-1 ...`. It uploads, waits for Perceptron's check, trains, and writes `PERCEPTRON_DEPLOYMENT_ID` into `.env` when the model is ready.
4. **While run 1 trains:** record the bench rows into the same dataset (`python -m arm.record --setting bench --item hex_key --direction hand-out --lighting normal --episodes 5`, and so on), and practice the pitch.
5. **Test run 1:** `python -m controller --real-arm`, then ask for the hemostat. Any item that fails a lot gets 10 more episodes.
6. **Run 2:** same pipeline command with `--idempotency-key scrub-run-2`, on the whole dataset.
7. **Success tests:** `python -m controller.trials` logs every try to the tables.

## If something goes wrong

| You see | Do |
| --- | --- |
| `401` | The Robotics team key is missing or wrong in `.env` |
| Cadence under 29 Hz | Close apps, re-record those episodes |
| Validation failed | Read `python -m arm.train validation <id>`, fix, make a new dataset |
| No deployment after training | Wait (export takes a while), check `python -m arm.train status`, then ask Perceptron staff |
| The arm jerks or stutters | Network is slow: get closer to the router or use a wired connection |
