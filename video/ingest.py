"""Index originals without rewriting them; explicit clock mapping, never mtime sync."""
from __future__ import annotations

from datetime import datetime
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

from .common import digest, finite, font, frame_at, info, provenance, read_json, stamp, write_json

EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".png", ".jpg", ".jpeg"}


def detect_clap(path, search_seconds=60):
    process = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
        "-t", str(search_seconds), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode or not process.stdout:
        raise ValueError("Clap alignment requires an audio stream")
    samples = np.frombuffer(process.stdout, np.int16).astype(float)
    window = 160
    samples = samples[:len(samples)//window*window]
    energy = np.sqrt(np.mean(samples.reshape(-1, window)**2, axis=1))
    peak = int(np.argmax(energy))
    ratio = float(energy[peak] / max(1, np.median(energy)))
    if ratio < 6:
        raise ValueError("No isolated clap peak; use an operator-confirmed --clap-second")
    return (peak+.5)*window/16000, ratio


def contact_sheet(path, details, output, meta):
    count = min(6, details["frames"])
    times = np.linspace(0, max(0, (details.get("duration_s") or 0) - 1/(details.get("fps") or 1)), count)
    sheet = Image.new("RGB", (960, 2*225), (236,232,221))
    draw = ImageDraw.Draw(sheet)
    for n, t in enumerate(times):
        image = cv2.imread(str(path)) if details["media"] == "image" else frame_at(path, float(t))
        image = stamp(image, meta)
        tile = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        tile.thumbnail((310,190))
        x, y = n%3*320, n//3*225
        sheet.paste(tile, (x,y))
        draw.text((x+4,y+194), f"{t:.2f}s | {path.name[:30]}", font=font(12,True), fill=(20,19,15))
    sheet.save(output)


def ingest(ws, sync=None, kind=None, clap_clip=None, clap_time=None, clap_second=None):
    sync_path = ws.source(sync or "sync.json")
    clock_map = read_json(sync_path) if sync_path.exists() else {}
    paths = sorted(p for folder in ("raw", "photos") for p in (ws.root/folder).glob("**/*")
                   if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if not paths:
        raise ValueError("No clips/photos found in workspace raw/ and photos/")
    if len({p.name for p in paths}) != len(paths):
        raise ValueError("Duplicate asset basenames; rename originals before creating sync map")
    if clap_clip:
        if clap_time is None:
            raise ValueError("Clap alignment requires the matching ledger epoch --clap-ledger-time")
        path = ws.source(clap_clip)
        if path not in paths:
            raise ValueError("Clap clip must be one of the ingested raw assets")
        second, ratio = detect_clap(path) if clap_second is None else (finite(clap_second), None)
        if not 0 <= second < info(path)["duration_s"]:
            raise ValueError("Clap time outside clip")
        clock_map[path.name] = {"start_time": finite(clap_time)-second,
            "method": "audio clap peak" if ratio else "operator-confirmed clap", "clap_second": second, "peak_ratio": ratio}
    assets = []
    for path in paths:
        if path.is_symlink():
            raise ValueError("Input symlinks are not supported")
        details = info(path)
        meta = provenance(path)
        requested = clock_map.get(path.name, {}).get("kind", kind)
        if requested:
            if requested not in {"real", "simulation", "reconstructed"}:
                raise ValueError("Input kind must be real/simulation/reconstructed")
            if meta["kind"] != "unknown" and meta["kind"] != requested:
                raise ValueError("Cannot relabel existing source provenance")
            meta = {**meta, "kind": requested}
        if meta.get("synthetic") and meta["kind"] == "real":
            raise ValueError("Synthetic data can never be marked real")
        start = clock_map.get(path.name, {}).get("start_time", meta.get("start_time"))
        if start is not None:
            start = finite(start, "clip epoch start")
        capture_time = None
        if details["media"] == "image":
            with Image.open(path) as photo:
                capture_time = photo.getexif().get(36867)
        meta = {**meta, "start_time": start, "sha256": digest(path)}
        contact = ws.out("contacts/"+path.stem+".jpg")
        contact_sheet(path, details, contact, meta)
        assets.append({"id": path.stem, "path": str(path.resolve()), **details, "start_time": start,
            "sync_method": clock_map.get(path.name, {}).get("method", "source metadata" if start is not None else "UNALIGNED"),
            "capture_time_exif_unverified": capture_time, "mtime_not_used_for_sync": path.stat().st_mtime,
            "contact_sheet": str(contact), "provenance": meta})
    manifest = {"schema_version": 1, "assets": assets,
                "note": "Unaligned clips cannot drive event overlays or take selection. Mtime is not capture sync."}
    write_json(ws.out("manifest.json"), manifest)
    if clap_clip:
        write_json(ws.out("sync.json"), clock_map)
    return {"manifest": str(ws.out("manifest.json")), "assets": len(assets),
            "unaligned": [a["id"] for a in assets if a["media"] == "video" and a["start_time"] is None]}
