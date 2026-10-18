# Printable props

Made by `.venv/bin/python -m explore.recognition.props`. Rerun it after a change to `settings/*.json`. Test: `python -m unittest explore.recognition.test_props`.

## Files

- `count_sheet_<tray>.html` : count sheet to print. Tray name, QR `scrub:tray:<id>`, Date / Case / Counted by lines, and a table with Item, Expected, Initial count, Closing count. Expected is the item's `qty`, or 1 if the setting has none.
- `tray_tag_<tray>.html` : 4 x 2.5 in tag with a big QR and the words TRAY, the label and the id.
- `pack_labels.html` : four sterile pack labels (scalpel, hemostat, mayo scissors, scalpel).
- `*.png` : the same props drawn at 1600 px wide, as clean test images. Extra variants:
  - `count_sheet_<tray>_filled.png` : simulated handwriting. Initial 1, 1, 1 and closing 1, 0, 1, plus date, case and name.
  - `count_sheet_surgical_angle.png` : the filled surgical sheet turned about 20 degrees, on a table colour.
  - `pack_labels_angle.png` : the pack sheet at the same angle.
- `truth.json` : ground truth for every PNG, for scoring OCR.

## How to print

Open the HTML in a browser, print, set paper to US Letter, scale 100% (not "fit to page"), margins none, background graphics on. The count sheet fits one page. Cut the tray tag out along its border.

## The expired label is on purpose

The mayo scissors label says `Expires 2026-09-30`. With today as 2026-10-18 it is expired, so "read the pack" should warn. The last scalpel label has no expiry line and says "Event related". Both are marked in `truth.json` (`expired`, `event_related`).
