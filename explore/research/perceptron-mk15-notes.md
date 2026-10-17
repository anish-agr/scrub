# Perceptron Mk1.5 quick reference (for A4 perception client, A5 verify)

Source: the team's Mk1.5 summary page (claude.ai artifact LgZp77XnpyjFz16YYPS5p1), built from docs.perceptron.inc/perceptron-mk1.5, SDK 0.4, Oct 2026.
Verify field names against the live docs before relying on them.

- SDK: `pip install "perceptron>=0.4.0"`. Platform: platform.perceptron.inc. MCP server: api.perceptron.inc/mcp (question, caption, detect, ocr). CLI: `perceptron detect clip.mp4 --classes person`.
- Chat: `POST /v1/chat/completions`, OpenAI-compatible, model `perceptron-mk1.5`. Context 36,864 tokens, output 8,192. $0.15 / $1.50 per 1M in/out, cached input $0.0375.
- Detect: `POST /v1/detect` with an image, optional `categories` (up to 256), `exemplars` (up to 64), `negative_exemplars`, `output: box|point`. Returns JSON detections in **pixels**. Reach `Detection.box` is normalized `[x,y,w,h]`, so divide by the image size.
- Chat spatial output: `<point>`, `<point_box>` and `<polygon>` tags on a **0 to 1000 grid**, with `mention=` and `asset_idx=`. Set it with `annotation_format: "box" | "point" | "polygon" | "clip"`.
- Video: `<track>` gives timestamped boxes for one object. `<clip t="a seconds b seconds"/>` cites moments or spans. Video Q&A returns the goal, the subgoals in order, and an outcome of done, not done or unclear.
- Audio: WAV/MP3/FLAC, about 21.8 min per item. It does sound event detection and transcription. `enable_audio_in_video: true`.
- Structured output: `response_format` as a JSON Schema, a Pydantic model or a regex (e.g. `yes|no`). Tools and a schema cannot share one request.
- Tools: `tools`, then `tool_calls`, then `role:"tool"` results. `reasoning_effort` takes none, minimal, low, medium or high (use none for fast captions).
- Multilook: `.../completions/multilook` sends the media once with up to 16 prompts. Useful for one frame per tick: detect + safety + verify questions together.
- Few-shot: labeled reference boxes in the prompt, no training. "Teach it Grandma's mug from one photo."
- Limits: 300 req/min chat, 150 Multilook, 20 MiB per body, 120 s per request. Files API: 128 MiB per file.

## Ideas this unlocks
- **Verify (A5):** send the before/after frames or a short clip, ask for the outcome, and use regex `yes|no` or a schema `{success:bool, confidence:number, reason:string}`.
- **Stove guardian:** audio sound-event detection hears a smoke alarm or sizzle, alongside video events.
- **Few-shot personal objects:** the user uploads one photo of "my blue mug" as an exemplar, and detection finds it with no fine-tuning.
- **Multilook safety tick:** "Is a human hand within the workspace? Is the target visible? Is the gripper holding something?" in one call.
- **Video segmentation for Watch Once (prototype 13):** video Q&A with subgoals and clips gives the primitive timeline.
