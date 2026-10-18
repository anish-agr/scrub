## Photos to take

About 15 minutes, one person, about 140 frames. Run every command from the repo root. Use one set name (`tray1` below) so everything lands in one folder.

Setup: overhead camera on its mount, tray in place, the surgical setting items on the tray (scalpel, hemostat, mayo scissors). Print the props first: `print explore/recognition/props/*.html` (count sheet, tray tag, pack label). Find camera indexes with `.venv/bin/python -m arm.check_setup --side C920 --wrist icspring` if the defaults are wrong. Defaults: overhead is `CAMERA_INDEX` if it is set in your shell (else 0), side is `CAPTURE_SIDE_INDEX` (1), wrist is `CAPTURE_WRIST_INDEX` (2). `--camera 3` also works.

Keys (the same list prints when the tool starts and is drawn on the preview):

| Key | Label | Items stored |
| --- | --- | --- |
| 1 | full | all three |
| 2 | no_scalpel | hemostat, mayo_scissors |
| 3 | no_hemostat | scalpel, mayo_scissors |
| 4 | no_mayo_scissors | scalpel, hemostat |
| 5 | alone_scalpel | scalpel |
| 6 | alone_hemostat | hemostat |
| 7 | alone_mayo_scissors | mayo_scissors |
| 8 | grip_scalpel | scalpel |
| 9 | grip_hemostat | hemostat |
| 0 | grip_mayo_scissors | mayo_scissors |
| a | glove_blue | all three, under the hand |
| b | glove_white | all three, under the hand |
| c | count_sheet_clean | none |
| d | count_sheet_written | none |
| e | count_sheet_angle | none |
| f | tray_tag | none |
| g | pack_label | none |
| h | pack_label_angle | none |

A label key selects that label and saves one frame. SPACE saves another with the current label. `[` and `]` change label. `l` cycles the light tag (bright, normal, dim). `q` or Esc quits. Each frame is tagged with the light shown on the preview, so set the real light first. Pass `--light` at start to set the first tag.

### 1. Full tray and one instrument removed (overhead, 39 frames)

Do this three times, once per light. Bright: all lights on. Normal: usual room light. Dim: lights down to about a quarter.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light bright
```

- [ ] Bright: key `1` x 4 (full tray), then remove the scalpel and press `2` x 3, put it back and remove the hemostat, `3` x 3, put it back and remove the mayo scissors, `4` x 3, put it back.
- [ ] Normal: same 13 frames. Rerun with `--light normal` (or press `l` once).
- [ ] Dim: same 13 frames. Rerun with `--light dim` (or press `l` again).

Move each frame a little between presses (nudge the tray or an instrument by a finger width).

### 2. Each instrument alone (normal light, 9 overhead and 15 wrist frames)

Clear the tray, then put one instrument in its slot.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light normal
```

- [ ] Overhead: key `5` x 3 (scalpel alone), `6` x 3 (hemostat alone), `7` x 3 (mayo scissors alone).

Then the same instruments in the gripper. Close the gripper on each one, lift it 10 cm above the tray, and shoot from the wrist camera.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera wrist --light normal
```

- [ ] Wrist: key `8` x 5 (scalpel in gripper), `9` x 5 (hemostat), `0` x 5 (mayo scissors).

### 3. Gloved open hand (overhead, 60 frames)

Full tray in place. Open palm facing down, 15 to 25 cm above the tray, fingers spread. Tilt and move the hand a little between frames. Blue nitrile first, then white, three lights each.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light bright
```

- [ ] Bright: key `a` x 10 (blue), then swap gloves, `b` x 10 (white).
- [ ] Normal: same 20 frames (rerun with `--light normal`).
- [ ] Dim: same 20 frames (rerun with `--light dim`).

### 4. Printed props (overhead, 18 frames, normal light)

Print `explore/recognition/props/*.html`. Fill the count sheet by hand for the "written" shots (initial and closing counts, pen). Lay each prop flat on the table where the tray sits, filling most of the frame. For "angle", tilt it about 30 degrees and turn it a little off square.

```
.venv/bin/python -m explore.recognition.capture --set tray1 --camera overhead --light normal
```

- [ ] Count sheet, blank, flat: key `c` x 3.
- [ ] Count sheet, handwritten, flat: key `d` x 3.
- [ ] Count sheet, handwritten, at an angle: key `e` x 3.
- [ ] Tray tag on the tray, flat: key `f` x 3.
- [ ] Pack label, flat: key `g` x 3.
- [ ] Pack label, at an angle: key `h` x 3. Repeat `g` and `h` with a written lot or date if the label has a blank for it.

There is no angled tray tag label. A phone is fine for any prop, see below.

### Phone photos instead

Name each file `<label>[_anything].jpg`, for example `count_sheet_written_a.jpg` or `no_hemostat_2.jpg`. Put them in one folder (jpg, jpeg or png; HEIC is skipped, export as jpg first), then:

```
.venv/bin/python -m explore.recognition.capture --set tray1 --import ~/Downloads/phone --light normal
```

Files whose name does not start with a label are skipped and listed. Imported frames are tagged camera `phone` and the light you pass.

### Where the files go and what to run next

- Photos: `data/recognition/tray1/<label>_<n>.jpg`.
- Labels: `data/recognition/tray1/labels.json`. Each entry has `items` (what is on the tray), `boxes` (empty), `label`, `camera`, `light` and `t`. `bench.py` reads `items` and `boxes`. Capturing again with the same set name adds files and never overwrites.
- Check counts: `ls data/recognition/tray1 | sed 's/_[0-9]*\.jpg//' | sort | uniq -c`.
- Run the bench: `.venv/bin/python -m explore.recognition.bench --images data/recognition/tray1 --repeat 2`
- Results land in `explore/recognition/out/bench.json` and `bench.md`.
