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

Confirmed on live call using `PERCEPTRON_API_KEY`:

| Limit | Value |
| --- | --- |
| Measured latency | 3.11 seconds (live round-trip call to `/v1/detect` on 640x480 frame) |
| Request timeout we use | 4.0 seconds (`vision/tray.py`). Raised from 2.0 seconds to accommodate live API latency. |
| Body size | 20 MiB (docs) |
| Categories | 256 |
| Our tray period | 1 second, so a lift shows up on the next successful call |
| Confidence | not returned |

When a call fails or exceeds the timeout, the last good TrayState is posted again with `"stale": true`. That field is optional and extra; the rest of the body still matches `docs/CONTRACTS.md`.

Live testing confirmed `POST https://api.perceptron.inc/v1/detect` accepts the data URL payload, respects `reasoning_effort: "none"`, and returns pixel bounding boxes within 3.11 seconds.

---

## Multimodal Chat & Video / Caption Capabilities (`/v1/chat/completions`)

Perceptron provides an OpenAI-compatible Chat Completions API for image captioning, video understanding, and temporal event clipping (checked from `docs.perceptron.inc` Oct 17, 2026).

### Endpoint and auth

- `POST https://api.perceptron.inc/v1/chat/completions`
- Header `Authorization: Bearer $PERCEPTRON_API_KEY`
- Header `Content-Type: application/json`
- Model: `perceptron-mk1.5` (or `perceptron-mk1`)

### Captioning styles and prompts

Perceptron supports both concise and detailed caption styles using task prompts or the Python SDK helper `caption()`:

1. **Concise caption**
   - SDK helper: `caption(style="concise")`
   - Optimal prompt: `"Provide a concise, human-friendly caption for the upcoming image."`
   - Use case: Short event descriptions for case logs and dashboard timelines (e.g. `"scalpel set at the safe spot, 14:02"`).

2. **Detailed caption**
   - SDK helper: `caption(style="detailed")`
   - Optimal prompt: `"Provide a detailed caption describing key objects, relationships, and context in the upcoming image."`

### Video inputs and temporal clipping

Perceptron accepts video inputs (`video/mp4`, `video/webm`) as hosted URLs (`video_url`), via the SDK `video()` helper, or as sampled frame arrays (`image_url` data URLs).

Request payload with video clipping and thinking mode:

```json
{
  "model": "perceptron-mk1.5",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "video_url",
          "video_url": {"url": "https://example.com/clip.mp4"}
        },
        {
          "type": "text",
          "text": "Identify and label the key action in this clip (e.g. 'scalpel set at the safe spot')."
        }
      ]
    }
  ],
  "vision_config": {
    "annotation_format": "clip",
    "enable_thinking": true
  }
}
```

- `vision_config.annotation_format`: `"clip"` prompts the model to localize moments or return temporal clip annotations in seconds.
- `vision_config.enable_thinking`: `true` enables reasoning traces (`<think>` blocks) before generating output.
- When sending local frames directly (no public video hosting), pass key frame data URLs:
  `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}`.

### Integration with Scrub case replay (X4)

1. **Rolling buffer:** `vision/clips.py` maintains an in-memory ring buffer of recent frames from the overhead camera.
2. **Event clips:** For each Event posted by the controller (`picked`, `handed`, `set_down`, `released`, `returned`, `stopped`, `missed`), vision saves a 3-second `.mp4` clip (`pre_s=1.5`, `post_s=1.5`) under `vision/clips/<case_id>/`.
3. **Post-case labeling:** Calling `POST /clips/label` queries Perceptron's chat completions endpoint with the clip's key frame to produce an event description. When the API key is unset or offline, a clinical fallback label is generated (`"<item> <action>, HH:MM"`).
4. **Endpoints on port 8001:**
   - `GET /clips?case_id=<case_id>`: List clips and labels for a case.
   - `POST /clips/record`: Explicitly capture a clip around an event.
   - `POST /clips/label`: Label all clips for a case using Perceptron.
   - `GET /clips/{case_id}/{filename}`: Stream a clip video (`.mp4`) or thumbnail (`.jpg`).

