# settings

Owner: Evan. Task E1 in `docs/TASKS.md`.

One JSON file per tray: `surgical.json` and `bench.json` (the demo settings), plus `dental.json`, a dental tray file that still loads if asked for but isn't demoed, in the format in `docs/CONTRACTS.md`. Slot and return-spot boxes come from Brandon once the camera is mounted. Until then every `slot` and `return_spot` is `null`.

Only the scalpel is `sharp`. Aliases are the extra words clinicians and techs say (kelly for the hemostat, mayo for the scissors, allen key for the hex key). `pick_instruction` and `return_instruction` are the exact lines the arm records.
