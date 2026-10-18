# Recognition bench

Compares ways to recognize the surgical tray items (scalpel, hemostat, mayo scissors) on saved images. Code is `explore/recognition/bench.py`, scoring tests are `explore/recognition/test_bench.py`.

```
.venv/bin/python -m explore.recognition.bench --repeat 2
.venv/bin/python -m unittest explore.recognition.test_bench
```

It reads keys from `.env` and never prints them. It writes `explore/recognition/out/bench.json` (one block per method) and `bench.md`. Use `--images DIR` for other photos: `DIR/<item_id>/*.jpg` for single-item crops, and `DIR/labels.json` for whole-tray photos (`{"tray.jpg": {"items": [...], "boxes": {"scalpel": [x1, y1, x2, y2]}}}`).

## What data exists

The repo holds three real crops, one per item, in `explore/bench/refs/` (80x23, 172x121 and 96x35 px, from the real tray). The six images under `vision/clips/` are 640x480 and completely black (fake-camera clips). There is no whole-tray photo, no image with printed text and no image of a gloved hand. So the numbers below come from 3 real crops plus 2 synthetic trays composed from those crops on a dark 640x480 background (boxes known by construction). The crops are loose: the hemostat crop also shows a scalpel-like rod, so a "scalpel" hit on it is not clearly wrong. Treat every number as a smoke test, not accuracy on a real tray.

## Methods and results (this run: 5 images, 2 repeats each)

| Method | Calls | Found rate | Accuracy | Median latency |
| --- | --- | --- | --- | --- |
| Perceptron `/v1/detect`, the same call `vision/tray.py` makes | 10 | 0.4 | 0.2 | 2.5 s |
| Gemini `gemini-3.5-flash-lite`, name the instruments in a crop | 6 | 0.33 | 0.0 | 0.97 s |
| Gemini `gemini-3.5-flash-lite`, check a tray against the expected list | 4 | 0.5 | 0.5 | 1.56 s |

No call failed in the final run. An earlier run hit HTTP 429 from Gemini when calls came back to back, so the bench now waits 3 s between Gemini calls and retries once after 20 s. About 80 API calls were made across three runs in total while fixing the synthetic tray layout.

Perceptron detect, per image (found = all expected items returned a box):

- Crops: scalpel found, hemostat found, mayo scissors not found in either repeat. Scalpel was also returned for the hemostat and mayo crops.
- Synthetic tray with all three: scalpel and hemostat found, mayo scissors not found. The scalpel box had IoU 0.0 against the pasted crop and the hemostat box IoU 0.34, so those boxes landed on the wrong part of the image (probably on the scalpel-like rod inside the hemostat crop).
- Synthetic tray without the scalpel: hemostat found with IoU 0.996, mayo scissors not found, and a scalpel was still returned (the rod in the hemostat crop).
- Latency per call: 1.8 to 2.5 s on crops, 3.8 to 4.7 s on the 640x480 trays. These runs used the old limits (a 4.0 s timeout and a 3 s stale cutoff), so the larger frames sat on both. `vision/` now uses a 6 s timeout, uploads frames 640 px wide and treats a read as stale after 8 s. The first call in an earlier run took 9.6 s (cold connection).

Gemini naming a crop (open names matched to item ids with the same alias list as vision): scalpel crop named `retractor` once and nothing once. Hemostat crop named `scalpel handle`, `hemostat` and `forceps`. Mayo crop named `surgical retractor` and `surgical blade`. It never produced "mayo scissors" and used generic names (forceps, retractor). Open naming needs a constrained list.

Gemini checking a tray (the prompt lists the three names, structured JSON with an enum): all-three tray correct 2 of 2. Tray without the scalpel wrong 2 of 2: it said the scalpel was present and the mayo scissors missing. The mayo crop was 52 px tall at 1.5x, so this case is as much about image quality as about Gemini.

## Skipped

- OCR: no image with printed text (tray label or QR tag). The tray items carry no printed text, so OCR would add nothing for instruments. Photo needed: the tray with its label and the QR tag visible, from the overhead camera.
- MediaPipe hand landmarker on gloved hands: no such image exists, so there is no measurement. `vision/README.md` already says the landmarker has no glove model. Photos needed: overhead camera, a blue or white nitrile glove, an open palm held 15 to 25 cm above the tray, in bright, normal and dim light, 10 frames each, saved as `DIR/glove_*.jpg`. A person also needs to say where the palm is in each, or the bench can only count whether a hand was found.

## Recommendation

Keep `vision/` as it is. Nothing here beats the current Perceptron path on evidence strong enough to change it, and the data is too thin to judge either way. Two things to check on the real overhead frames before the demo:

1. Latency against the limits. On 640x480 tray images, detect took 3.8 to 4.7 s here, over the old 4.0 s timeout and 3 s stale cutoff. The limits are now 6 s and 8 s, set by `VISION_DETECT_TIMEOUT_S` and `VISION_TRAY_STALE_S`. Check `detect_p50_ms` on vision `/health` with the live camera.
2. Missing instruments. Perceptron did not return mayo scissors in any tray image. Take one real overhead photo of the full tray and one with each instrument removed, put them in a folder with `labels.json`, and rerun the bench. If Perceptron still misses, Gemini tray check (about 1.1 to 2 s, structured output, enum of item names) is the candidate second opinion for `controller/traycheck.py`. In this run it got the full tray right and the missing-scalpel case wrong, so it is not ready to replace anything.
