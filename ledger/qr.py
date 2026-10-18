"""Write ledger/public/qr.png for SCRUB_PUBLIC_URL in the repo-root .env."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG = Path(__file__).resolve().parent / "public" / "qr.png"
FALLBACK = "http://127.0.0.1:8080"


def public_url() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    url = os.environ.get("SCRUB_PUBLIC_URL", "").strip()
    return url.rstrip("/") if url else FALLBACK


def write_qr(url: str | None = None) -> str:
    import qrcode

    target = url or public_url()
    image = qrcode.make(target)
    PNG.parent.mkdir(parents=True, exist_ok=True)
    image.save(PNG)
    return target


def main() -> None:
    target = write_qr()
    print(f"wrote {PNG}")
    print(f"points at {target}")


if __name__ == "__main__":
    main()
