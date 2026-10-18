"""Write ledger/public/qr.png for SCRUB_PUBLIC_URL in the repo-root .env."""

from __future__ import annotations

import argparse
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


def png_bytes(url: str | None = None) -> bytes:
    """PNG bytes for the current public URL. The card always serves this."""
    import io

    import qrcode

    image = qrcode.make(url or public_url())
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_qr(url: str | None = None) -> str:
    target = url or public_url()
    PNG.parent.mkdir(parents=True, exist_ok=True)
    PNG.write_bytes(png_bytes(target))
    return target


def main() -> None:
    argparse.ArgumentParser(prog="python -m ledger.qr", description=__doc__).parse_args()
    target = write_qr()
    print(f"wrote {PNG}")
    print(f"points at {target}")


if __name__ == "__main__":
    main()
