# arm

Owner: Anish. Tasks A3, A6, A7 in `docs/TASKS.md`. Steps in `docs/ARM.md`.

`real_arm.py` implements the arm interface in `docs/CONTRACTS.md` with LeRobot and the fine-tuned Isaac 0.5 policy. `rig.json` holds the home, carry and safe-spot poses and the handoff region. Only the controller imports this folder.

Done when: the controller runs a real "pick the hemostat" with `--real-arm`, and `move_to` reaches test points within about 2 cm.
