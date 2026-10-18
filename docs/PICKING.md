# Picking: how Scrub chooses and checks a pick

> **Demo scope (Oct 18 morning):** this page describes the controller's `--skills smart` path, which runs on the sim and the fake arm. The real arm in the demo runs through the station (`explore/station/README.md`): each pick replays the average of our recorded demonstrations for that item (autopick average mode), and the arm goes home after each handoff. Return on the real arm is manual. 0 Perceptron training jobs and 0 deployments exist, so `model` never runs.

`--skills smart` picks each instrument with the method that has the best measured record for that item, checks every grasp, and retries once with the next method. In the controller, sharps never go to a hand (see Sharps below).

Code: `controller/picker.py` (choice), `controller/core.py` (`_pick_smart` and the sharp flow), `arm/grasp.py` (the grasp methods and the safe-zone rules), `vision/locate.py` (`GET /locate` on vision). Contract fields: `docs/CONTRACTS.md`.

## The methods

| `skill_source` | What moves the arm | Needs |
| --- | --- | --- |
| `model` | A Perceptron deployment through `run_skill` (none exists as of 07:10 Oct 18) | `PERCEPTRON_DEPLOYMENT_ID` with a live deployment |
| `taught_adjusted` | The item's taught waypoints, with the at-slot waypoints shifted by the located offset: IK on the measured shift in the arm frame, or a shoulder_pan nudge from the mm offset; item rotation goes to wrist_roll. Shifts over 4 cm or a located confidence under 0.3 are ignored and it plays as taught | `arm/skills/<setting>/<item>-pick.json` (`docs/TEACH.md`) |
| `ik` | A top-down grasp computed from the located pose: approach 6 cm above, descend, close, lift, carry | `vision/calibration.json` (the located pose in the arm frame) and a verified rig |
| `taught` | The taught waypoints as recorded (kept for `--skills taught` and as a prior) | a taught skill |

All of them run through the same 30 Hz playback, joint limits, gripper torque, thermal guard and stop as every other arm move (`arm/real_arm.py` `taught_controls`).

## A pick, step by step

1. **Locate** (vision `/locate`, 2.5 s limit). The local slot check finds the item's centre and rotation in its slot. The Perceptron detection is a second reading. Gemini is asked only when the two disagree by more than 15 mm, one says absent, or confidence is under 0.5. The tray tag OCR (read in the background, at most once a minute) confirms the setting. The answer is the offset from the slot in pixels and mm, the rotation, the position in the arm frame when calibrated, a confidence, and the method that answered. If vision says "not found" with confidence 0.6 or more, Scrub says it isn't on the tray. If vision doesn't answer, the pick goes ahead without a located pose.
2. **Grasp** with the first method in the item's order.
3. **Check the grasp.** The jaw: fully closed (94% or more) means it closed on nothing. Then the wrist camera: Perceptron detect, then Gemini "is the <item> in the gripper", 3 s total. A closed jaw is a miss. An uncertain jaw plus "no" from the camera is a miss. A jaw that holds something while the camera says no stays a pick and is logged `wrist_disagrees: true`. The tray check on the lift (the slot is empty now) still applies.
4. **On a miss:** open, go back (home), locate again and retry once with the next method. After two misses Scrub says "I couldn't pick the <item>" and logs `missed`.
5. Every `picked`, `missed`, `handed` and `set_down` event carries `skill_source`, `locate_method`, `locate_confidence`, `grasp_check` (`gripper`, `gripper+wrist` or `none`), `retry`, and `arm` (`real`, `sim` or `fake`).

## How the method is chosen

`controller/picker.py` reads the ledger (MongoDB `scrub.events`, else the local ledger buffer) and keeps only rows with `arm: "real"` and no `test` tag. Rows from before Oct 18, 3 AM have no `arm` field, so none count. That includes the fake "real" rows that `controller/test_flows.py` wrote to Atlas. Each command is one try per method used. For each item it ranks the available methods:

- by the lower bound of the 95% Wilson interval on the success rate, then by median request-to-hand time;
- `model` goes first when its lower bound is at least the best other's, so a deployed model would run wherever it earns it;
- a method needs **10 real tries** on an item before its rate can move it. Until then the default order holds: `model` (only with a deployment) > `taught_adjusted` (only with a taught skill) > `ik`;
- rows under the current lighting decide alone once there are at least 5 of them.

The choice is written to `data/skill_policy.json` and shown on the ops page (`/state` `skills.policy`: method, confidence, why, order). It refreshes at start, on a setting change, and after each real-arm pick. Print the table and refresh it by hand with `.venv/bin/python -m controller.picker --setting surgical`.

## Sharps (controller only, cut from the demo)

Any item with `sharp: true` in `settings/*.json` (the scalpel) is never handed over by the controller: it goes to a taught set-down zone instead (`arm/grasp.py` `safe_zone_problems`, `arm/real_arm.py`, `controller/core.py`). That zone was cut from the demo and is not taught (`arm/rig.json` has `"safe_zone": null`), so the controller refuses to pick the scalpel on the real arm. The real-arm demo runs through the station (`explore/station/README.md`), which replays our recorded scalpel demonstrations and offers the scalpel handle to the hand.

## Per item, measured

Oct 18, 3:15 AM. **No method has a real try yet.** The arm is busy with run 1 recordings (Chat A), so every rate below is empty.

| Item | `model` | `taught_adjusted` | `ik` | Policy now |
| --- | --- | --- | --- | --- |
| hemostat | no deployment (run 1 not trained) | no taught skill | needs `vision/calibration.json` | default order, no real tries |
| mayo scissors | no deployment | no taught skill | needs calibration | default order, no real tries |
| scalpel (never handed by the controller) | no deployment | no taught skill | needs calibration | refused on the real arm (no taught set-down zone) |

On the sim (`run_all backup`, `--skills smart`), every run is CLEAN: picks, the handoffs and the scalpel set down in the sim's zone (`zone_check: no_camera`, since the backup runs no vision). The sim tests also show the point of `taught_adjusted` and `ik`. With an item 3 cm off its slot, the plain taught pick closes on nothing, while `taught_adjusted` with the measured offset and `ik` both pick it (`sim/test_sim.py`).

Fill this table from `python -m controller.picker --setting surgical` after real controller tries. None exist: the real-arm runs went through the station.

## For the pitch (honest, today)

"On the real arm each pick replays our own recorded demonstrations of that item." The station's replay path has no grasp check, so claim the grasp check only for the controller and sim. Don't claim a per-item method or a model pick until the table above has real numbers and a deployment exists.
