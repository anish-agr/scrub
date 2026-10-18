"""Workspace boundaries, source provenance and the bundled-ffmpeg media path."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "data" / "video"
DEFAULT_DATASET = Path.home() / "scrub-dataset"  # arm/record.py --root default
EVENTS_NAME = "events.jsonl"  # written by `export-ledger`, read by find/overlay/cards when --events is omitted
LABELS = {"simulation": "SIMULATION", "reconstructed": "RECONSTRUCTED FROM ARM JOINT DATA",
          "mixed": "MIXED FOOTAGE - NON-REAL SHOTS LABELED; NOT A CONTINUOUS REAL DEMO",
          "photo_plate": "PHOTO PLATE - STATIC BACKGROUND, NOT AN ACTION RECORDING",
          "unknown": "UNVERIFIED SOURCE"}
PAPER, INK = (236, 232, 221), (20, 19, 15)


class Workspace:
    def __init__(self, root=BASE):
        self.root = Path(root).resolve()
        if not self.root.is_relative_to(BASE.resolve()):
            raise ValueError("All output workspaces must be inside this repository's data/video/")
        self.root.mkdir(parents=True, exist_ok=True)

    def out(self, name):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Output escapes the video workspace")
        relative = path.relative_to(self.root)
        if relative.parts[0] in {"raw", "photos"}:
            raise ValueError("Never write derivatives into raw/ or photos/")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def source(self, name):
        path = Path(name).expanduser()
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing a symlink output")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sidecar(path):
    return Path(str(path) + ".video.json")


def provenance(path, verify=True):
    path = Path(path).resolve()
    doc = read_json(sidecar(path)) if sidecar(path).is_file() else None
    if doc is None:
        # Ingest never modifies source media or writes alongside external inputs.
        for parent in path.parents:
            if not parent.is_relative_to(BASE.resolve()):
                break
            registry = parent / "manifest.json"
            if registry.is_file():
                for entry in read_json(registry).get("assets", []):
                    if entry["path"] == str(path):
                        doc = entry["provenance"]
                        break
            if doc is not None:
                break
    doc = doc or {"kind": "unknown", "operations": []}
    if doc.get("kind") not in {*LABELS, "real", "card"}:
        raise ValueError("Unrecognized source provenance")
    if verify and doc.get("sha256") and digest(path) != doc["sha256"]:
        raise ValueError("Media changed after provenance was written; re-ingest the source")
    return doc


def save_provenance(output, parent=None, **fields):
    doc = dict(provenance(parent)) if parent else {"operations": []}
    doc.pop("sha256", None)
    doc.update(fields)
    if parent:
        doc["parent"] = {"file": str(Path(parent).resolve()), "sha256": digest(parent)}
    doc["schema_version"] = 1
    doc["sha256"] = digest(output)
    write_json(sidecar(output), doc)
    return doc


def finite(value, name="value", positive=False):
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return value


def font(size, mono=False):
    cached = BASE / "fonts" / ("IBMPlexMono-Regular.ttf" if mono else "Archivo.ttf")
    candidates = [str(cached), "consola.ttf" if mono else "arial.ttf", "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=max(10, int(size)))
        except OSError:
            pass
    return ImageFont.load_default()


def text_bar(frame, lines, *, bottom=False, color=PAPER, foreground=INK):
    band = _band(frame.shape[1], tuple(map(str,lines)), tuple(color), tuple(foreground))
    result = frame.copy()
    height = min(result.shape[0], band.shape[0])
    y = result.shape[0] - height if bottom else 0
    result[y:y+height] = band[:height]
    return result


@lru_cache(maxsize=128)
def _band(width, lines, color, foreground):
    size = max(12, round(width / 48))
    face = font(size, mono=True)
    measure=ImageDraw.Draw(Image.new('RGB',(1,1)))
    wrapped=[]
    for line in lines:
        current=''
        for word in line.split():
            proposed=(current+' '+word).strip()
            if current and measure.textlength(proposed,font=face)>width-20:
                wrapped.append(current)
                current=word
            else:
                current=proposed
        wrapped.append(current)
    lines=wrapped
    line_h = size + 10
    height = line_h * len(lines) + 12
    image=Image.new('RGB',(width,height),color)
    draw=ImageDraw.Draw(image)
    draw.line((0,height-2,width,height-2),fill=foreground,width=2)
    for i, line in enumerate(lines):
        # Fit full disclosure, never silently crop the reconstruction label.
        actual = face
        while draw.textlength(str(line), font=actual) > image.width - 20 and size > 10:
            size -= 1
            actual = font(size, mono=True)
        draw.text((10, 6 + i * line_h), str(line), font=actual, fill=foreground)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def stamp(frame, meta, speed=1):
    labels = []
    if meta.get("synthetic"):
        labels.append("SIMULATION - SYNTHETIC FIXTURE, NOT REAL-ARM EVIDENCE")
    kind = meta.get("kind", "unknown")
    if kind in LABELS and not (kind == "simulation" and meta.get("synthetic")):
        labels.append(LABELS[kind])
    if speed != 1:
        labels.append(f"{speed:g}x SPEED - SOURCE TIME COMPRESSED")
    return text_bar(frame, labels) if labels else frame


def info(path):
    path = Path(path)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("Unreadable image")
        return {"width": image.shape[1], "height": image.shape[0], "fps": None,
                "frames": 1, "duration_s": None, "audio": False, "media": "image"}
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Unreadable video: " + path.name)
        fps = finite(capture.get(cv2.CAP_PROP_FPS), "source FPS", True)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frames < 1:
            raise ValueError("Video has no frames")
        result = {"width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                  "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), "fps": fps,
                  "frames": frames, "duration_s": frames / fps, "media": "video"}
    finally:
        capture.release()
    probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    result["audio"] = bool(re.search(r"Stream .*Audio:", probe.stderr))
    return result


def frames(path, start=0.0, end=None):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Cannot decode video")
        fps = finite(capture.get(cv2.CAP_PROP_FPS), "FPS", True)
        first = max(0, round(start * fps))
        capture.set(cv2.CAP_PROP_POS_FRAMES, first)
        i = first
        while end is None or i < round(end * fps):
            ok, image = capture.read()
            if not ok:
                break
            yield i / fps, image
            i += 1
    finally:
        capture.release()


def frame_at(path, seconds=0):
    return next(frames(path, seconds))[1]


def run_ffmpeg(ws, args):
    process = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-y", *map(str, args)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        log = ws.out("logs/ffmpeg-" + uuid.uuid4().hex + ".txt")
        log.write_bytes(process.stderr)
        raise RuntimeError(f"ffmpeg failed; inspect {log} (no credentials are used)")


def audible(path):
    process = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path),
        "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    match = re.search(r"max_volume:\s*([-\d.]+) dB", process.stderr)
    return bool(match and float(match.group(1)) > -80)


def encode(ws, output, images, fps=30, audio=None, segments=None, audio_clean=False, video_filter=None):
    """Stream BGR frames to bundled ffmpeg. Optional source-time audio remap."""
    output = Path(output)
    if output.suffix.lower()!='.mp4':
        raise ValueError("Encoded video output must use .mp4")
    fps = finite(fps, "FPS", True)
    iterator = iter(images)
    try:
        first = next(iterator)
    except StopIteration:
        raise ValueError("No output frames") from None
    import itertools
    h, w = first.shape[:2]
    if w % 2 or h % 2:
        raise ValueError("H.264 output dimensions must be even")
    temp = ws.out("work/" + uuid.uuid4().hex + ".mp4")
    error_log = ws.out("logs/encode-" + uuid.uuid4().hex + ".txt")
    count = 0
    with error_log.open("wb") as errors:
        process = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
            "-an", *(["-vf", video_filter] if video_filter else []), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(temp)], stdin=subprocess.PIPE, stderr=errors)
        try:
            for image in itertools.chain([first], iterator):
                if image.shape != first.shape or image.dtype != np.uint8:
                    raise ValueError("Frame dimensions/type changed")
                process.stdin.write(np.ascontiguousarray(image).tobytes())
                count += 1
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError("Encoder failed: " + str(error_log))
        except BaseException:
            process.kill()
            process.wait()
            temp.unlink(missing_ok=True)
            raise
        finally:
            if not process.stdin.closed:
                process.stdin.close()
            close = getattr(iterator, "close", None)
            if close:
                close()
    duration = count / fps
    try:
        if audio is not None and info(audio)["audio"] and audible(audio):
            args = ["-i", temp, "-i", audio]
            if segments:
                filters, names = [], []
                for n, segment in enumerate(segments):
                    start, end, speed = segment["start"], segment["end"], segment["speed"]
                    filters.append(f"[1:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,atempo={min(speed,2)}" +
                                   (f",atempo={speed/2}" if speed > 2 else "") + f"[a{n}]")
                    names.append(f"[a{n}]")
                filters.append("".join(names) + f"concat=n={len(names)}:v=0:a=1[cat]")
                filters.append("[cat]" + ("afftdn," if audio_clean else "") +
                               "loudnorm=I=-16:TP=-1.5:LRA=11,apad[outa]")
                args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[outa]"]
            else:
                args += ["-map", "0:v", "-map", "1:a:0", "-af",
                         ("afftdn," if audio_clean else "") + "loudnorm=I=-16:TP=-1.5:LRA=11,apad"]
        else:
            args = ["-i", temp, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
        mux = ws.out("work/" + uuid.uuid4().hex + ".mp4")
        args += ["-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", duration,
                 "-movflags", "+faststart", mux]
        run_ffmpeg(ws, args)
        mux.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    return {"frames": count, "fps": fps, "duration_s": duration, "width": w, "height": h}


def default_events(ws):
    path = ws.root / EVENTS_NAME
    if not path.is_file():
        raise ValueError(f"No --events and no {path}: run `python -m video export-ledger` first")
    return path


def export_ledger(ws, name=EVENTS_NAME):
    """Write the ledger (Atlas plus ledger/buffer.jsonl) as {"kind","doc"} lines, the format ledger_rows reads."""
    import ledger
    ledger.warm(8)
    event_rows, test_rows = ledger.stored_rows()
    if not event_rows and not test_rows:
        raise ValueError("The ledger returned no rows (MONGODB_URI unset or Atlas unreachable, and ledger/buffer.jsonl empty)")
    out = ws.out(name)
    lines = [json.dumps({"kind": kind, "doc": doc}, default=str) for kind, rows in (("event", event_rows), ("test", test_rows)) for doc in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"events_file": str(out), "events": len(event_rows), "tests": len(test_rows)}


def ledger_rows(path):
    result=[]
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row=json.loads(line)
        kind=row.get('kind')
        doc=dict(row['doc']) if kind in {'event','test'} and 'doc' in row else dict(row)
        doc['_record_kind']=kind if kind in {'event','test'} else 'test' if doc.get('type')=='test' else 'event'
        if doc.get('source') in {'fake','simulation','sim'}:
            doc['synthetic']=True
        finite(doc['t'],'ledger timestamp')
        result.append(doc)
    return sorted(result,key=lambda row:row['t'])


def events(path):
    return [row for row in ledger_rows(path) if row['_record_kind']=='event']


def fit(image, width, height):
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(image, (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))))
    result = np.zeros((height, width, 3), np.uint8)
    y, x = (height - resized.shape[0]) // 2, (width - resized.shape[1]) // 2
    result[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
    return result


def epoch_at(meta, seconds):
    mapping = meta.get("time_map")
    if mapping:
        for segment in mapping:
            if segment["output_start"] <= seconds < segment["output_end"] + 1e-8:
                return segment["epoch_start"] + (seconds-segment["output_start"])*segment["speed"]
        raise ValueError("Output time has no source-clock coverage")
    if meta.get("start_time") is None:
        raise ValueError("No source clock: align the clip with ingest --sync or a clap first")
    return finite(meta["start_time"]) + seconds


def speed_at(meta, seconds):
    return next((s['speed'] for s in meta.get('time_map',[]) if s['output_start']<=seconds<s['output_end']),1)
