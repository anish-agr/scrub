# Teaching a taught skill

Taught skills are the controller's labeled way to move the real arm (the one Perceptron fine-tuning job, `job_629682f9575271b687e2c734`, was training at 09:08 with no deployment). Each one is 4 to 6 joint waypoints you set by moving the arm by hand. Every event from a taught skill carries `skill_source: "taught"`, and the dashboard says so.

Budget: under 15 minutes per item (about 5 for the pick, 5 for the return, 3 for the check).

Files land in `arm/skills/<setting>/<item>-<direction>.json`, for example `arm/skills/surgical/hemostat-pick.json`. Item ids come from `settings/<setting>.json`: `scalpel`, `hemostat`, `mayo_scissors` for surgical.

## Before you start

1. `home` is measured in `arm/rig.json`. `carry` is still `null` there, so measure it first.
2. The tray is taped and the instrument sits in its slot.
3. Nothing else has the arm port open: close the controller, teleop and any recording.
4. The follower arm is powered (12 V supply on, LEDs lit).

## Teach the pick

1. Hold the arm by the upper arm with one hand. Torque goes off when the tool starts, and an unsupported arm drops.
2. Run:
   `.venv/bin/python -m arm.teach skill hemostat pick --setting surgical --supported-and-empty`
   (`--port` comes from `SO101_PORT` in `.env`; pass `--port /dev/tty.usbmodem...` if it is not set.)
3. Move the arm to each spot, hold it still, and press a key:
   - **o** at the approach, about 5 cm above the instrument's grip point. This saves it with the gripper open.
   - **Enter** after descending so the open jaws surround the instrument.
   - **g** at the same spot to save it with the gripper closed.
   - **Enter** after lifting straight up about 5 cm.
   - **Enter** at the carry pose.
   - **q** saves the file and quits. Torque stays off. Set the arm down.
4. `u` removes the last waypoint, `p` prints the current joints. Ctrl-C quits without saving.

Waypoints are named in order: approach, descend, grip, lift, carry. Each saves at speed 0.3 (30% of the rig's joint speed limit). Add `--speed 0.2` to teach a slower skill, or edit `speed` per waypoint in the JSON.

## Teach the return

Put the instrument back in the slot by hand first so you can see where it goes, then hold it in the closed jaw.

1. Run `.venv/bin/python -m arm.teach skill hemostat return --setting surgical --supported-and-empty`.
2. **Enter** at carry, **Enter** after descending over the slot, **o** to save the release with gripper open, **Enter** after lifting about 5 cm, **Enter** at home, then **q**.

If `q` prints "Check failed", the file is saved anyway. Fix the problem (usually a missing `g` in a pick or `o` in a return) by teaching again; a new run overwrites the file.

## Check it

1. Without the arm (any time): `.venv/bin/python -m arm.taught --check --setting surgical --fake`. Every item shows `ok`, `FAIL <reason>` or `not taught`, and the command ends with PASS or FAIL. It checks joint names, URDF limits, at least 3 waypoints, a pick that closes the gripper and a return that opens it.
2. On the arm: take every instrument out of the gripper and off the tray, then run `.venv/bin/python -m arm.taught --check --setting surgical` with `SO101_PORT` set. It moves home, then replays each skill at speed 0.15. Keep a hand on the stop. This needs `hardware_verified: true` in `arm/rig.json`.
3. Watch that the jaw closes at the slot and the arm clears the tray when it lifts. If a pose is off by more than about 1 cm, teach that skill again.

## Run it through the controller

`.venv/bin/python -m controller --real-arm --skills taught --setting surgical`

Say "pick the hemostat". The pick event shows `skill_source: taught`. Say "stop" once during a run to confirm it holds.

## Slot offset

If vision is calibrated, the caller can pass `offset` to `arm.taught.play`: a shoulder_pan nudge in degrees (or `{joint: degrees}`) that shifts every waypoint except carry and home. It is off by default, and with a taped tray the skill plays as taught.
