"""Download the SO-101 URDF + MuJoCo model from TheRobotStudio/SO-ARM100 (Apache-2.0) into sim/models/so101/.

Pinned to one commit so everyone gets identical files. Run from the repo root: python -m sim.fetch_model
"""
import json
import pathlib
import urllib.request

REPO = "TheRobotStudio/SO-ARM100"
SHA = "a758567c3978dfeefe282ede0500085a48fe8f78"
SRC = "Simulation/SO101"
FILES = [
    "so101_new_calib.xml", "so101_new_calib_camera.xml", "so101_new_calib.urdf",
    "so101_new_calib_camera.urdf", "scene.xml", "joints_properties.xml", "README.md",
]
DEST = pathlib.Path(__file__).resolve().parent / "models" / "so101"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main() -> None:
    raw = f"https://raw.githubusercontent.com/{REPO}/{SHA}/{SRC}"
    listing = json.loads(_get(f"https://api.github.com/repos/{REPO}/contents/{SRC}/assets?ref={SHA}"))
    assets = [f"assets/{e['name']}" for e in listing if e["name"].endswith(".stl")]
    (DEST / "assets").mkdir(parents=True, exist_ok=True)
    for rel in FILES + assets:
        out = DEST / rel
        if out.exists() and out.stat().st_size > 0:
            continue
        out.write_bytes(_get(f"{raw}/{rel}"))
        print("fetched", rel)
    (DEST / "LICENSE-NOTE.txt").write_text(
        f"From https://github.com/{REPO} at {SHA} ({SRC}). Apache License 2.0. Not modified.\n")
    print(f"done: {DEST}")


if __name__ == "__main__":
    main()
