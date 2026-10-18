# Chat C: a smart pick that works tonight without full training

Say to a new Claude Code chat on the arm Mac: "Pull, then follow team/RUN-SMART-PICK.md exactly."

---

I'm Caiden on team Scrub at DubHacks '26: an SO-101 arm that passes surgical instruments by voice. **We're on a hard time crunch**: it's about 2 AM Sunday, the Devpost locks at 10:00 AM (submit by 9:30), judging at 10:30. We will not have a fully trained model for every item, and the demo has to work anyway. This chat makes the arm pick reliably by using everything we have (vision, OCR, Gemini, kinematics, taught skills, the fine-tuned model where it's good) and choosing the best one per item from measured data.

## How to work (read twice)

- **Go wide with subagents and keep them busy.** You orchestrate. Opus subagents for `controller/`, `arm/` motion and safety; Sonnet subagents for vision helpers, analysis, tests and docs. Each gets a strict file list, done criteria and tests. Run independent parts at the same time.
- Finish everything. Don't ask me questions. Steps only a person can do go to the table as one short instruction with the exact command.
- Other Claude chats are running on this Mac (Chat A trains the model, Chat B the phone call, Chat D the data analysis, plus my main chat). Before editing a file run `git log -1 --format=%ar -- <file>` and skip it if someone changed it in the last 10 minutes. Commit small, `git pull --rebase` before every push. Never print or commit keys.
- You own: new files `controller/picker.py`, `arm/grasp.py`, `vision/locate.py`, their tests, `docs/PICKING.md`, and the skill-selection part of `controller/core.py` (keep the change small and tested). Don't touch `voice/`, `arm/train.py`, `arm/pipeline.py`, `explore/station/` or the dataset tools.

## Read first

`docs/OVERVIEW.md`, `docs/CONTRACTS.md`, `docs/INTEGRATION.md`, `docs/RECOGNITION.md`, `docs/TEACH.md`, `arm/real_arm.py`, `arm/taught.py`, `arm/kinematics.py`, `arm/hardware.py` (or wherever the shared hardware layer lives), `controller/core.py`, `vision/tray.py`, `vision/local_detect.py`, `vision/tray_find.py`, `vision/reading.py`, `vision/calibrate.py`, `team/LEFT.md`, and `team/NOTES-TRAIN.md` and `team/NOTES-DATA.md` when they appear.

## What to build

1. **Find the item before moving (`vision/locate.py`).** From the overhead frame: which slot the item is in and its offset and rotation, using the existing local slot check and Perceptron detect, with Gemini as a second opinion when they disagree or confidence is low. Use the tray tag OCR to confirm the setting. Return a position in the arm's base frame through the camera-to-arm calibration, a confidence, and the method that answered. If calibration isn't done yet, return slot-relative offsets in pixels and mm from the tray size.
2. **Three ways to grasp, one interface (`arm/grasp.py`):**
   - `model`: the fine-tuned Perceptron deployment via `run_skill`, when one exists.
   - `taught_adjusted`: the taught waypoints with the approach shifted by the measured offset and rotation (shoulder_pan for lateral offset, wrist_roll for rotation, IK from `arm/kinematics.py` for the reach), so one taught pick covers small slot errors.
   - `ik`: a top-down grasp computed from the located pose: approach above, descend, close, lift. No teaching needed, for items with a clear pose.
   All three run through the same motion, joint limits, gripper torque, thermal guard and stop as the rest of the arm.
3. **Check the grasp after every pick.** Gripper position and load (fully closed means a miss), plus the wrist camera: Perceptron detect or Gemini "is the <item> in the gripper", with a time limit. On a miss: open, go back above the slot, and retry once with the next-best method. Two misses: say so out loud and log `missed`.
4. **Choose the method per item from data (`controller/picker.py`).** Read the ledger (MongoDB `scrub.events`, real-arm rows only, separated by `skill_source`, item and lighting; Chat D's `team/NOTES-DATA.md` has the queries). Rank methods by the lower bound of the Wilson interval on success, break ties by median request-to-hand time. Prefer `model` when it's at least as good, so the Perceptron model runs wherever it earns it. With no real data yet, use the order model (if deployed) > taught_adjusted > ik. Write the chosen method per item to `data/skill_policy.json` and show it on the ops page through `/state` (`skills.items` already exists; add `method`, `confidence`, `why`).
5. **Sharps go to a known safe zone, never to a hand.** Today `arm/rig.json` has `safe_spot: null`. Make the safe zone real and enforced:
   - Teach it (`python -m arm.teach`, key `s`) as a taped square on the table, at least 15 cm from the handoff box and outside any path the arm takes to the hand. Store it as a pose plus a box in `arm/rig.json`, and draw it in the sim and on the ops page and dashboard.
   - Any item marked sharp in `settings/*.json` (the scalpel; add a `sharp: true` field if missing) can only end at the safe zone. The controller refuses a handoff for it, even if the voice command asks for one, and says "Scalpel to the safe spot".
   - While a sharp is held: a keep-out zone around the tracked hand (no closer than 20 cm), slower speed, the blade pointed away from the handoff side and down when set down, and a straight path from slot to safe zone that never crosses the handoff box.
   - Before setting down, check the zone is clear with the overhead camera (no hand, no other item in the box). If not clear: hold above it, say "Clear the safe spot", wait, and time out to the slot.
   - After set-down, confirm the scalpel is in the box from the overhead frame and log `set_down` with `zone_check`.
   - Tests for every one of these on the fake and sim arms, including a voice command that tries to hand over the scalpel.
6. **Use the trained model wherever it earns it.** As soon as Chat A has a deployment, the picker runs real tries with `model` per item, and the policy switches an item to `model` when its numbers match or beat the other methods. The sharps rules above apply to every method, the model included.
7. **Every event says how the pick happened:** `skill_source` (`model`, `taught_adjusted` or `ik`), `locate_method`, `locate_confidence`, `grasp_check`, `retry`. Optional fields only; write them into `docs/CONTRACTS.md`.

## Prove it

- Tests with the fake and sim arms for each method, the grasp check, the retry, and the policy choice from a fixed set of ledger rows.
- The sim backup (`python -m controller.run_all backup --offline --loop`) stays CLEAN with the picker on.
- On the real arm, as soon as it's free between Chat A's recordings: 10 tries per item per method that's ready, logged. Then the picker chooses from those numbers.
- `docs/PICKING.md`: how a pick is chosen and checked, the per-item table of methods and results, and the one-line honest summary for the pitch ("the fine-tuned model picks the hemostat; the scissors use a taught pick adjusted by vision").

## Before you stop

Every test passes, everything is pushed (`git status` clean, nothing ahead of `origin/main`). Add what's left, with who and exact steps, to `team/LEFT.md`. Report: methods ready per item, real-try results per method, the current policy, and what a person must do next.
