"""Per-try side-camera videos with operator labels, plus contact sheets.

Offline example (retrospective label, no robot/camera/API):
  python -m arm.video --images <frame-directory> --instruction "pick the hemostat" --try-number 1 --success yes
  python -m arm.video --self-test

Live, ONLY if the side camera is not already owned by LeRobot:
  python -m arm.video --camera 0 --camera-is-free --instruction "pick the hemostat" --tries 3
Prefer --stream-url <side-camera-owner-MJPEG-URL> while LeRobot owns the device.
No side-stream endpoint is assumed or added by this tool; vision's overhead
stream is not automatically the side camera. Never open the same camera twice.

Default output: new data/arm-video/<session>/, already git-ignored. Ctrl-C stops
recording, NOT the robot. No motor control, API key or external upload is used.
Saved sequences carry a permanent OFFLINE watermark. Success is an operator
label, not an inference from pixels or proof of clinical safety.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"yes": "OPERATOR: SUCCESS", "no": "OPERATOR: FAILURE", "unknown": "OUTCOME: UNKNOWN"}
COLORS = {"yes": (75, 240, 130), "no": (255, 100, 100), "unknown": (255, 210, 80)}


@dataclass(frozen=True)
class TryLabel:
    instruction: str
    try_number: int
    success: str
    source_kind: str

    def validate(self):
        if not self.instruction.strip() or len(self.instruction) > 300 or any(ord(c) < 32 for c in self.instruction):
            raise ValueError("Instruction must be a nonempty single line, at most 300 characters")
        if self.try_number < 1 or self.success not in LABELS:
            raise ValueError("Try number must be positive and success must be yes/no/unknown")
        if self.source_kind not in {"saved-images", "side-camera", "side-stream"}:
            raise ValueError("Unknown source kind")


def font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def wrapped(text, width, draw, face):
    lines, line = [], ""
    for word in text.split():
        proposed = (line + " " + word).strip()
        if line and draw.textlength(proposed, font=face) > width:
            lines.append(line)
            line = word
        else:
            line = proposed
    if line:
        lines.append(line)
    # Split unusually long single words, so labels never spill off the frame.
    fitted = []
    for line in lines:
        while draw.textlength(line, font=face) > width and len(line) > 1:
            end = len(line) - 1
            while end > 1 and draw.textlength(line[:end], font=face) > width:
                end -= 1
            fitted.append(line[:end])
            line = line[end:]
        fitted.append(line)
    return fitted


def overlay(frame, label, index, fps):
    label.validate()
    image = Image.fromarray(np.asarray(frame, dtype=np.uint8)).convert("RGB")
    width, height = image.size
    if width < 160 or height < 120:
        raise ValueError("Frames must be at least 160x120 to display readable labels")
    face = font(max(12, round(width / 32)))
    small = font(max(10, round(width / 45)))
    draw = ImageDraw.Draw(image)
    lines = wrapped(label.instruction, width - 20, draw, face)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip(".") + "..."
    line_height = max(16, round(width / 25))
    panel_height = min(height - 30, (len(lines) + 2) * line_height + 14)
    draw.rectangle((0, 0, width, panel_height), fill=(12, 16, 22))
    draw.text((10, 5), f"SCRUB | TRY {label.try_number} | {index / fps:.2f}s", font=face, fill="white")
    for row, text in enumerate(lines):
        draw.text((10, 5 + (row + 1) * line_height), text, font=face, fill="white")
    draw.text((10, 5 + (len(lines) + 1) * line_height), LABELS[label.success], font=face, fill=COLORS[label.success])
    footer = "OFFLINE SAVED IMAGES - NOT A LIVE ARM TEST" if label.source_kind == "saved-images" else "SIDE CAMERA - OPERATOR LABEL - PROTOTYPE"
    draw.rectangle((0, height - 25, width, height), fill=(12, 16, 22))
    draw.text((8, height - 22), footer, font=small, fill=(255, 210, 80))
    return np.asarray(image)


def sequence_paths(directory, pattern="*"):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError("--images must be an existing directory")
    paths = [p for p in directory.glob(pattern) if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}]
    if any(p.is_symlink() for p in paths):
        raise ValueError("Image sequence symlinks are not supported")
    paths.sort(key=lambda p: [int(v) if v.isdigit() else v.lower() for v in re.split(r"(\d+)", p.name)])
    if not paths:
        raise ValueError("No saved images match the sequence")
    return paths


def image_frames(paths):
    for path in paths:
        with Image.open(path) as image:
            yield np.asarray(image.convert("RGB"))


def video_frames(path):
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError("Cannot read the captured scratch video")
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        capture.release()


def contact_sheet(frames, captions, path):
    if not frames:
        raise ValueError("No frames for the contact sheet")
    columns = min(3, len(frames))
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * 340, rows * 285 + 35), (18, 22, 28))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), "SCRUB - OPERATOR-LABELED TAKES (NOT CLINICAL VALIDATION)", font=font(15), fill="white")
    for n, (frame, caption) in enumerate(zip(frames, captions)):
        image = Image.fromarray(frame).convert("RGB")
        image.thumbnail((320, 240))
        x, y = (n % columns) * 340 + 10, (n // columns) * 285 + 35
        sheet.paste(image, (x, y))
        draw.text((x, y + 244), caption, font=font(13), fill="white")
    sheet.save(path, format="JPEG", quality=92)


def export_try(frames, count, fps, label, directory, *, capture_metadata=None):
    """Encode one immutable labeled clip and per-try metadata/contact sheet."""
    import cv2
    label.validate()
    if not math.isfinite(fps) or not 0 < fps <= 120 or count < 1:
        raise ValueError("Need positive frame count and FPS in (0,120]")
    directory = Path(directory)
    stem = f"try-{label.try_number:03d}"
    clip, manifest = directory / (stem + ".mp4"), directory / (stem + ".json")
    sheet = directory / (stem + "-contact.jpg")
    partial = directory / (stem + ".partial.mp4")
    if any(path.exists() or path.is_symlink() for path in (clip, manifest, sheet, partial)):
        raise ValueError("Try output already exists; never overwrite a prior take")
    frames = iter(frames)
    try:
        first = next(frames)
    except StopIteration:
        raise ValueError("Empty frame source") from None
    height, width = first.shape[:2]
    writer = cv2.VideoWriter(str(partial), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    selected = set(np.linspace(0, count - 1, min(6, count), dtype=int).tolist())
    samples, sample_indices, written = [], [], 0
    try:
        if not writer.isOpened():
            raise RuntimeError("MP4 encoder unavailable; install an OpenCV build with mp4v support")
        for index, frame in enumerate(itertools.chain([first], frames)):
            if np.asarray(frame).shape != (height, width, 3):
                raise ValueError("Every frame in a try must have the same RGB dimensions")
            labeled = overlay(frame, label, index, fps)
            writer.write(cv2.cvtColor(labeled, cv2.COLOR_RGB2BGR))
            written += 1
            if index in selected:
                samples.append(labeled)
                sample_indices.append(index)
        if written != count:
            raise ValueError("Decoded frame count differs from the captured count; take not published")
    except BaseException:
        writer.release()
        partial.unlink(missing_ok=True)  # Only this invocation's new partial file.
        raise
    finally:
        writer.release()
    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError("Encoder produced no clip")
    partial.rename(clip)
    contact_sheet(samples, [f"Try {label.try_number} | frame {n}" for n in sample_indices], sheet)
    info = {"schema_version": 1, **asdict(label), "success_is_operator_reported": True,
            "offline": label.source_kind == "saved-images", "frames": written,
            "fps": fps, "duration_s": written / fps, "width": width, "height": height,
            "clip": clip.name, "contact_sheet": sheet.name,
            "capture": capture_metadata or {}, "created_at": time.time()}
    # Source URLs/absolute input paths, tokens and camera credentials are never exported.
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(info, stream, indent=2)
        stream.write("\n")
    return info, samples[len(samples) // 2]


def capture_live(source, scratch, seconds, requested_fps, *, preview=False,
                 capture_factory=None, clock=time.monotonic):
    """Spool unlabeled frames; final outcome is asked only after recording."""
    import cv2
    capture = (capture_factory or cv2.VideoCapture)(source)
    writer, count, first_time, last_time = None, 0, None, None
    stop_reason = "duration"
    start = clock()
    try:
        if not capture.isOpened():
            raise RuntimeError("Cannot open the supplied side-camera source; check ownership and connection")
        if isinstance(source, int):
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, requested_fps)
        while clock() - start < seconds:
            ok, frame = capture.read()
            if not ok:
                stop_reason = "source-ended"
                break
            now = clock()
            if writer is None:
                shape = frame.shape
                writer = cv2.VideoWriter(str(scratch), cv2.VideoWriter_fourcc(*"MJPG"), requested_fps, (shape[1], shape[0]))
                if not writer.isOpened():
                    raise RuntimeError("Scratch-video encoder unavailable")
                first_time = now
            if frame.shape != shape:
                raise ValueError("Side-camera dimensions changed while recording")
            writer.write(frame)
            count += 1
            last_time = now
            if preview:
                cv2.imshow("Scrub side recording (q ends recording, NOT robot motion)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_reason = "operator-stop"
                    break
    except KeyboardInterrupt:
        stop_reason = "operator-stop"
    finally:
        if writer is not None:
            writer.release()
        capture.release()
        if preview:
            cv2.destroyAllWindows()
    if not count:
        raise ValueError("No side-camera frames captured")
    measured = (count - 1) / (last_time - first_time) if count > 1 and last_time > first_time else requested_fps
    if not 0 < measured <= 120:
        raise ValueError("Implausible capture cadence; do not publish an accelerated live take")
    return count, measured, {"requested_fps": requested_fps, "measured_fps": measured,
                             "stop_reason": stop_reason, "wall_duration_s": (last_time - first_time) if count > 1 else 0}


def outcome(value, read=input):
    if value != "ask":
        return value
    while True:
        try:
            answer = read("Actual result? y=success, n=failure, u=unknown (operator label only): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "unknown"  # Keep captured footage without inventing a success.
        if answer in {"y", "n", "u"}:
            return {"y": "yes", "n": "no", "u": "unknown"}[answer]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--images", type=Path, help="saved RGB image sequence directory; permanently labeled OFFLINE")
    source.add_argument("--camera", type=int, help="side camera index; requires --camera-is-free")
    source.add_argument("--stream-url", help="actual side-camera-owner video/MJPEG URL, not an assumed endpoint")
    parser.add_argument("--camera-is-free", action="store_true", help="confirm no LeRobot/other process owns this device")
    parser.add_argument("--instruction")
    parser.add_argument("--try-number", type=int, default=1)
    parser.add_argument("--tries", type=int, default=1, help="live tries, with a new operator label after each")
    parser.add_argument("--success", choices=["ask", "yes", "no", "unknown"], default="ask")
    parser.add_argument("--fps", type=float, default=30, help="saved-sequence FPS or requested camera FPS")
    parser.add_argument("--seconds", type=float, default=25, help="maximum duration per live try")
    parser.add_argument("--pattern", default="*", help="saved-sequence filename glob; natural numeric sorting")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/arm-video")
    parser.add_argument("--preview", action="store_true", help="live preview; q ends recording, not the robot")
    parser.add_argument("--self-test", action="store_true", help="generate saved frames in a temporary directory; never open a camera")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.instruction or (args.images is None and args.camera is None and not args.stream_url):
        parser.error("Supply --instruction and exactly one of --images, --camera, --stream-url")
    if not all(math.isfinite(value) and value > 0 for value in (args.fps, args.seconds)) or args.fps > 120 or args.tries < 1 or args.try_number < 1:
        parser.error("Positive finite seconds/FPS, FPS <=120, and positive try numbers/count required")
    if args.camera is not None and (args.camera < 0 or not args.camera_is_free):
        parser.error("Do not reopen LeRobot's camera: --camera requires a nonnegative index and --camera-is-free")
    if args.images is not None and args.tries != 1:
        parser.error("One saved sequence is one offline try; do not duplicate it into multiple claimed attempts")
    if args.images is None and args.success not in {"ask", "unknown"}:
        parser.error("Label a live success/failure after capture using --success ask, not in advance")
    if args.stream_url:
        url = urlparse(args.stream_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            parser.error("Use a credential-free side-stream HTTP(S) URL without query tokens")
    TryLabel(args.instruction, args.try_number, "unknown", "saved-images" if args.images else "side-camera").validate()
    directory = args.out_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    sheets, captions = [], []
    try:
        for n in range(args.try_number, args.try_number + args.tries):
            if args.images is not None:
                paths = sequence_paths(args.images, args.pattern)
                label = TryLabel(args.instruction, n, outcome(args.success), "saved-images")
                info, sample = export_try(image_frames(paths), len(paths), args.fps, label, directory)
            else:
                if input(f"Try {n}: Enter to record side view (camera only, no robot control), q to finish: ").strip().lower() == "q":
                    break
                print("Recording. Ctrl-C/q stops the recording, NOT the robot.", flush=True)
                with tempfile.TemporaryDirectory(prefix="capture-", dir=directory) as scratch:
                    raw = Path(scratch) / "raw.avi"
                    count, fps, capture = capture_live(args.camera if args.camera is not None else args.stream_url,
                                                     raw, args.seconds, args.fps, preview=args.preview)
                    kind = "side-camera" if args.camera is not None else "side-stream"
                    label = TryLabel(args.instruction, n, outcome(args.success), kind)
                    info, sample = export_try(video_frames(raw), count, fps, label, directory, capture_metadata=capture)
            sheets.append(sample)
            captions.append(f"Try {n} | {LABELS[label.success]}")
            contact_sheet(sheets, captions, directory / "contact-sheet.jpg")
            print(json.dumps({"clip": str(directory / info["clip"]), "frames": info["frames"],
                              "success": info["success"], "offline": info["offline"]}))
        if not sheets:
            print("No takes recorded.")
            return 1
        print(f"Contact sheet: {directory / 'contact-sheet.jpg'}")
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"Video stopped ({type(error).__name__}); existing takes remain in {directory}")
        return 1


def self_test():
    """Real MP4 encoding/decoding from synthetic saved frames, no device access."""
    import unittest
    from unittest.mock import Mock, patch
    import cv2

    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
            self.images, self.output = self.root / "images", self.root / "output"
            self.images.mkdir()
            self.output.mkdir()
            for n in range(12):
                frame = Image.new("RGB", (320, 240), (40 + n * 6, 100, 160))
                ImageDraw.Draw(frame).rectangle((n * 8, 140, n * 8 + 25, 190), fill="white")
                frame.save(self.images / f"frame-{n}.png")
            self.label = TryLabel("pick the hemostat", 2, "yes", "saved-images")

        def test_natural_sequence_order(self):
            self.assertEqual([p.name for p in sequence_paths(self.images)][:4], ["frame-0.png", "frame-1.png", "frame-2.png", "frame-3.png"])
            self.assertEqual(sequence_paths(self.images)[-1].name, "frame-11.png")

        def test_saved_sequence_encodes_clip_and_contact_sheet(self):
            paths = sequence_paths(self.images)
            info, sample = export_try(image_frames(paths), len(paths), 30, self.label, self.output)
            decoded = list(video_frames(self.output / info["clip"]))
            self.assertEqual(len(decoded), 12)
            self.assertEqual((info["width"], info["height"]), (320, 240))
            self.assertTrue(info["offline"])
            self.assertEqual(info["success"], "yes")
            self.assertEqual(info["try_number"], 2)
            self.assertAlmostEqual(info["duration_s"], .4)
            self.assertTrue((self.output / info["contact_sheet"]).is_file())
            self.assertTrue((self.output / "try-002.json").is_file())
            # Both the header and permanent OFFLINE footer are burned in.
            self.assertLess(float(decoded[0][:10, :10].mean()), 40)
            self.assertLess(float(decoded[-1][-4:, :10].mean()), 40)
            self.assertEqual(sample.shape, (240, 320, 3))

        def test_label_changes_pixels_and_preserves_source(self):
            original = np.full((240, 320, 3), 160, dtype=np.uint8)
            copy = original.copy()
            yes = overlay(original, self.label, 0, 30)
            no = overlay(original, TryLabel("pick the hemostat", 2, "no", "saved-images"), 0, 30)
            self.assertFalse(np.array_equal(yes, no))
            np.testing.assert_array_equal(original, copy)

        def test_prior_take_never_overwritten(self):
            paths = sequence_paths(self.images)
            export_try(image_frames(paths), len(paths), 30, self.label, self.output)
            old = (self.output / "try-002.mp4").read_bytes()
            with self.assertRaises(ValueError):
                export_try(image_frames(paths), len(paths), 30, self.label, self.output)
            self.assertEqual((self.output / "try-002.mp4").read_bytes(), old)

        def test_bad_frame_count_is_not_published(self):
            paths = sequence_paths(self.images)
            with self.assertRaises(ValueError):
                export_try(image_frames(paths), 20, 30, self.label, self.output)
            self.assertFalse((self.output / "try-002.mp4").exists())
            self.assertFalse((self.output / "try-002.partial.mp4").exists())

        def test_saved_sequence_cli_never_opens_camera(self):
            # Encoding is real; any camera/network acquisition call is forbidden.
            with patch.object(cv2, "VideoCapture", side_effect=AssertionError("camera/network not permitted")):
                self.assertEqual(main(["--images", str(self.images), "--instruction", "pick the hemostat",
                                       "--success", "yes", "--out-dir", str(self.output)]), 0)
            sessions = list(self.output.iterdir())
            self.assertEqual(len(sessions), 1)
            self.assertTrue((sessions[0] / "contact-sheet.jpg").is_file())

        def test_live_camera_requires_explicit_ownership_confirmation(self):
            with patch.object(cv2, "VideoCapture", side_effect=AssertionError("must not open")), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    main(["--camera", "0", "--instruction", "pick the hemostat"])

        def test_invalid_label_and_empty_source(self):
            for label in (TryLabel("", 1, "yes", "saved-images"), TryLabel("pick", 0, "yes", "saved-images")):
                with self.assertRaises(ValueError):
                    label.validate()
            with self.assertRaises(ValueError):
                sequence_paths(self.output)

        def test_contact_sheet_combines_tries(self):
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            path = self.output / "sheet.jpg"
            contact_sheet([frame] * 4, ["Try 1", "Try 2", "Try 3", "Try 4"], path)
            with Image.open(path) as sheet:
                self.assertEqual(sheet.size, (1020, 605))

        def test_operator_result_is_explicit(self):
            self.assertEqual(outcome("ask", read=lambda prompt: "n"), "no")
            self.assertEqual(outcome("unknown"), "unknown")
            def no_answer(prompt):
                raise EOFError
            self.assertEqual(outcome("ask", read=no_answer), "unknown")

        def test_live_capture_spools_with_injected_fake_camera_only(self):
            frame = np.full((240, 320, 3), 110, dtype=np.uint8)
            capture = Mock()
            capture.isOpened.return_value = True
            capture.read.side_effect = [(True, frame.copy())] * 4 + [(False, None)]
            factory = Mock(return_value=capture)
            ticks = itertools.count()
            raw = self.output / "test-raw.avi"
            count, fps, metadata = capture_live(17, raw, 2, 30, capture_factory=factory,
                                                clock=lambda: next(ticks) / 60)
            self.assertEqual(count, 4)
            self.assertAlmostEqual(fps, 30)
            self.assertEqual(len(list(video_frames(raw))), 4)
            self.assertEqual(metadata["stop_reason"], "source-ended")
            factory.assert_called_once_with(17)
            capture.release.assert_called_once()

        def test_live_outcome_cannot_be_claimed_in_advance(self):
            with patch.object(cv2, "VideoCapture", side_effect=AssertionError("must not open")), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    main(["--camera", "0", "--camera-is-free", "--instruction", "pick the hemostat", "--success", "yes"])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
