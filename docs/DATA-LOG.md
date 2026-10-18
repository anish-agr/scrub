# Data log

Owner: Evan. One row per batch of demos. Targets: operating room, 20 hand-out and 10 put-back per item; robotics bench, 15 hand-out and 10 put-back per item. Split each across bright, normal and dim.

Fill a row when a batch is recorded with Anish. Direction is `hand-out` or `put-back`. Lighting is `bright`, `normal`, or `dim`. Demos is how many clips are in that batch. Dataset name is the Hub name, or `local` if it stayed on the laptop.

From the repo root, after the batch:

```
python -m ledger log --setting surgical --item hemostat --direction hand-out --lighting bright --demos 5 --dataset local --notes "cadence ok"
```

`--item` accepts the id (`mayo_scissors`) or a name people say (`kelly`, `mayo`). `python -m arm.record` appends the same line. Setting is the tray label, item is the name from the settings file:

```
| 2026-10-17 18:05 | Operating room | hemostat | hand-out | bright | 5 | local | cadence ok |
```

| Time | Setting | Item | Direction | Lighting | Demos | Dataset name | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-17 22:21 | unknown | spatula | hand-out | unknown | 8 | local | scrub-dataset ep 0-7; task 'pick the spatula' not in settings; loop 29.43-29.99 Hz; side cam 29.1-30.0 fps; wrist cam 18.7-22.6 fps; stalls ep 5 {'wrist': 2}; 6-105 s |
