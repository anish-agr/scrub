# How to train Scrub (one page to share)

This is the plain version. Every command with every flag is in `docs/BRINGUP.md` sections 6 to 8. Run all of this on **the laptop the arm is plugged into**.

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

Split each row across bright (lamp on, close), normal (room lights) and dim (some lights off). Move the item a little in its slot between episodes. Log every batch in `docs/DATA-LOG.md`.

## Two people per session

- **Driver:** moves the leader arm. Smooth and slow, the same way every time.
- **Resetter:** puts the item back, changes the lighting, presses the keys: `n` ends an episode cleanly, `r` re-records a bad one, `q` finishes and saves.

## Steps

1. **Record** the operating room rows (`docs/BRINGUP.md` section 6). About 90 episodes, about 1.5 hours.
2. **Check** (section 7): replay episode 0 on the arm, then `python -m arm.train pipeline <dataset folder> --cadence-report <file> --check-only`. Fix anything it flags.
3. **Run 1** (section 8): `python -m arm.train pipeline ... --idempotency-key scrub-run-1 ...`. It uploads, waits for Perceptron's check, trains, and writes `PERCEPTRON_DEPLOYMENT_ID` into `.env` when the model is ready.
4. **While run 1 trains:** record the bench rows into the same dataset, and practice the pitch.
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
