"""Write ledger/public/qr.png for SCRUB_PUBLIC_URL in the repo-root .env."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNG = Path(__file__).resolve().parent / "public" / "qr.png"
VULTR_URL = "http://144.202.95.111"  # the Vultr box until a domain is set


def _loopback(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    if not host.startswith("["):
        host = host.rsplit(":", 1)[0]
    host = host.strip("[]").lower()
    return host in ("", "localhost", "0.0.0.0", "::1") or host.startswith("127.")


def lan_url(port: int | None = None) -> str:
    """http://<this machine's LAN address>:<port>, never loopback. Empty if there is none."""
    import socket

    port = port or int(os.environ.get("PORT", "8080"))
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the route
        address = probe.getsockname()[0]
        probe.close()
    except OSError:
        return ""
    return "" if address.startswith("127.") or address == "0.0.0.0" else f"http://{address}:{port}"


def public_url() -> str:
    """What the table card's QR code and printed link point at. Never loopback.

    SCRUB_PUBLIC_URL (the domain) wins. SCRUB_PUBLIC_URL=lan means this machine's
    LAN address. Otherwise the Vultr box; the LAN address is the last resort.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    url = os.environ.get("SCRUB_PUBLIC_URL", "").strip().rstrip("/")
    if url.lower() == "lan":
        return lan_url() or VULTR_URL
    if url and not _loopback(url):
        return url
    server_ip = os.environ.get("SCRUB_SERVER_IP", "").strip()
    if server_ip and not _loopback(server_ip):
        return f"http://{server_ip}"
    return VULTR_URL or lan_url()


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
