"""Explicit direct upload, never called by hardware code."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .perceptron import APIError, USER_AGENT

ALLOWED = {".json", ".jsonl", ".parquet", ".mp4", ".png", ".jpg", ".jpeg"}


def manifest(root: Path):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Dataset root must be a real directory")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Dataset must not contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if path.suffix.lower() not in ALLOWED or not 0 < size <= 4 * 1024**3 or len(relative) > 512:
            raise ValueError(f"Unsupported dataset file: {relative}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024**2), b""):
                digest.update(block)
        files.append({"path": relative, "size_bytes": size, "sha256": digest.hexdigest()})
    if not any(f["path"] == "meta/info.json" for f in files):
        raise ValueError("Missing meta/info.json")
    if sum(f["size_bytes"] for f in files) > 20 * 1024**3:
        raise ValueError("Dataset exceeds 20 GiB")
    return files


def batches(files):
    batch = []
    for descriptor in files:
        candidate = batch + [descriptor]
        if len(candidate) > 500 or len(json.dumps({"files": candidate}).encode()) >= 512 * 1024:
            yield batch
            batch = []
        batch.append(descriptor)
    if batch:
        yield batch


def put_file(client, reservation, path, *, poll_timeout=300):
    url = reservation["url"]
    if urlparse(url).scheme != "https":
        raise ValueError("Signed upload requires HTTPS")
    headers = reservation.get("headers", {})
    if any(k.lower() in {"authorization", "modal-authorization"} for k in headers):
        raise ValueError("Unexpected credentials in upload reservation")
    try:
        with path.open("rb") as stream:
            response = client.put(url, headers=headers, content=stream)
        deadline = time.monotonic() + poll_timeout
        while response.status_code == 303:
            location = response.headers.get("location", "")
            if urlparse(location).scheme != "https":
                raise APIError("Missing or unsafe upload poll Location")
            if time.monotonic() >= deadline:
                raise APIError("Upload polling timed out; do not finalize")
            time.sleep(1)
            # No body, team key, or reservation headers on this GET.
            response = client.get(location)
        if not response.is_success:
            raise APIError(f"Upload HTTP {response.status_code}; do not finalize")
    except httpx.HTTPError:
        raise APIError("Upload transport failed; do not finalize") from None


def upload(api, root, name, idempotency_key):
    root = Path(root)
    files = manifest(root)
    dataset = api.register_dataset({"name": name, "source_kind": "upload"}, idempotency_key)
    dataset_id = dataset.get("id") or dataset.get("dataset_id")
    if not dataset_id:
        raise APIError("Dataset response has no id")
    with httpx.Client(timeout=300, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT}) as unsigned:
        for batch in batches(files):
            reservation = api.reserve_uploads(dataset_id, batch)
            expected = {f["path"]: f for f in batch}
            returned = reservation["files"]
            if len(returned) != len(batch) or {f["path"] for f in returned} != set(expected):
                raise APIError("Upload reservation does not match requested paths")
            for entry in returned:
                path = root / entry["path"]
                # Detect files changed since the manifest before committing bytes.
                descriptor = expected[entry["path"]]
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024**2), b""):
                        digest.update(block)
                if path.stat().st_size != descriptor["size_bytes"] or digest.hexdigest() != descriptor["sha256"]:
                    raise APIError("Dataset changed during upload; do not finalize")
                put_file(unsigned, entry, path)
    return {"dataset_id": dataset_id, "finalize": api.finalize(dataset_id)}


if __name__ == "__main__":
    from .train import main
    import sys
    main(["upload", *sys.argv[1:]])
