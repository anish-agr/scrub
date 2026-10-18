# Perceptron vision API (perception)

Owner: Brandon. Other agents should use this file instead of the docs site.

Training and inference for the arm are a different API: see `docs/PERCEPTRON-ROBOTICS.md`.

## Endpoint and auth

- `POST https://api.perceptron.inc/v1/detect`
- Header `Authorization: Bearer $PERCEPTRON_API_KEY`
- Header `Content-Type: application/json`
- Docs: https://docs.perceptron.inc/capabilities/detect (checked Oct 17, 2026)

The vision process calls this about once a second from `vision/tray.py`. `reasoning_effort` is `none` so the call stays on the fast path. Categories are the current setting's item names (underscores written as spaces), plus `robot arm` and `gripper` for the blocked-path check.

Check a live call with `python -m vision.lighting --check-api`. It prints HTTP status, latency, and how many detections came back. It does not print the key.

Checked Oct 17, 2026 from Evan's laptop: there is no repo-root `.env`, so `PERCEPTRON_API_KEY` is unset and no live call was sent. The shapes below are the ones the docs say work, and the ones `vision/tray.py` sends. Put the key in `.env` and run the command above to fill in the measured latency.

## Request that works

Image bytes go in a data URL. Exemplars in the docs use the same `data:image/...;base64,` form, so the frame uses it too. Coordinates in the response are pixels, not the 0 to 1000 chat grid.

```json
{
  "media": {"type": "image", "image_url": "data:image/jpeg;base64,<jpeg of the overhead frame>"},
  "categories": ["scalpel", "hemostat", "mayo scissors", "robot arm", "gripper"],
  "config": {"output": "box", "reasoning_effort": "none"}
}
```

- `config.output` is `"box"` (not `"bbox"`). `"point"` returns a center instead of `point_box`.
- Category strings must be non-empty and must not contain commas. Up to 256.
- `config.enable_thinking` is an old alias: `true` means `high`. Do not send it. We want `reasoning_effort: "none"`.
- `finish_reason` `"max_tokens"` means the model stopped early. Treat a failed HTTP call, an `error` object, or an empty body the same way: keep the last good TrayState and set `stale` true.

## Response shape

There is no confidence field. `vision/tray.py` writes `confidence: 1.0` on a fresh response.

```json
{
  "detections": [
    {
      "mention": "hemostat",
      "point_box": {
        "top_left": {"x": 130.0, "y": 90.0},
        "bottom_right": {"x": 240.0, "y": 130.0}
      }
    }
  ],
  "finish_reason": "complete"
}
```

`mention` is one of the categories we sent. We match it to an item id by lowercasing and treating spaces, underscores, and hyphens as the same, and we also accept that item's aliases (`kelly` matches hemostat when the setting file lists it).

A slot is present when the detection center lies inside the slot box, or the intersection-over-union with the slot is at least 0.15. The TrayState `box` is the slot box from `settings/<id>.json`, not the detection box. Until those boxes exist, a matching detection anywhere marks the item present and `box` stays null.

The return spot uses the same overlap test against `return_spot`.

## Latency and limits

From the docs, not from a timed call on our key:

| Limit | Value |
| --- | --- |
| Request timeout we use | 2 seconds (`vision/tray.py`). The controller treats a TrayState older than 3 seconds as unknown, so a slow call must still post the last state inside that window. |
| Body size | 20 MiB (docs) |
| Categories | 256 |
| Our tray period | 1 second, so a lift shows up on the next successful call (under about 2 seconds) |
| Confidence | not returned |

When a call fails or exceeds the timeout, the last good TrayState is posted again with `"stale": true`. That field is optional and extra; the rest of the body still matches `docs/CONTRACTS.md`.

Fill in a measured latency here after the first real call with the team key.
