# settings

Owner: Evan.

One JSON file per tray: `surgical.json` (the demo tray), `bench.json` (robotics bench items, used in the sim and tests, not shown on the real arm), plus `dental.json`, a dental tray file that still loads if asked for but isn't demoed, in the format in `docs/CONTRACTS.md`. Slot and return-spot boxes come from Brandon once the camera is mounted. Until then every `slot` and `return_spot` is `null`.

Only the scalpel is `sharp`. Aliases are the extra words clinicians and techs say (kelly for the hemostat, mayo for the scissors, allen key for the hex key). `pick_instruction` and `return_instruction` are the exact lines the arm records.

`<id>.local.json` holds aliases a clinic taught at run time (`{"aliases": {item_id: [words]}}`). The controller and voice merge it over `<id>.json` and the controller writes it; never edit `<id>.json` for that. `bench.local.json` here is one taught alias (pliers for the needle-nose pliers).

## Which one?

Optional `group` is a shared request word. Optional `variant` is a short word that
distinguishes the item. The bench tray includes `flathead_screwdriver` and
`phillips_screwdriver`, both with `"group": "screwdriver"`. Saying "screwdriver"
asks "Which screwdriver: flathead or Phillips?" Saying "Phillips" selects that item.
Names and aliases still work. The surgical training tray is unchanged.

A handover may carry `"instance": {"variant": "phillips"}`, `{"side": "left"}`,
`{"side": "right"}`, `{"side": "closest"}` or `{"slot": 2}`. Slots are one-based
within the candidate list. The controller's overhead view assumes the surgeon is
at image-bottom: image-left is their left, and larger image y is closer. The
station's side camera uses its separately documented opposite-camera view in
`explore/station/README.md`. Confirm the mounted camera and the surgeon's position
before using side words on the real arm. A question never authorizes a pick until answered, and expires
after 15 seconds. Stop still stops immediately.
