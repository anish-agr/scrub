"""Read-only asset checks against a running stack. Not a browser layout test."""
import argparse
from pathlib import Path
from urllib.parse import urljoin

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", default="http://localhost:8000")
    parser.add_argument("--ledger", default="http://localhost:8080")
    parser.add_argument("--sim", default="http://localhost:8002")
    args = parser.parse_args()
    groups = (
        (args.controller, ("/", "/tablet.html", "/nurse", "/demo"), "/style.css"),
        (args.ledger, tuple(f"/{n}.html" for n in ("index", "cases", "case", "series", "memory", "card")), "/style.css"),
        (args.sim, ("/web/viewer.html", "/web/layout.html"), "/web/style.css"),
    )
    expected = (ROOT / "design/scrub.css").read_bytes()
    with httpx.Client(timeout=10) as client:
        for origin, pages, css in groups:
            result = client.get(urljoin(origin, css))
            result.raise_for_status()
            assert "css" in result.headers.get("content-type", ""), css
            assert result.content == expected, f"Wrong shared stylesheet at {origin}{css}"
            for path in pages:
                result = client.get(urljoin(origin, path))
                result.raise_for_status()
                assert 'class="scrub-ui"' in result.text or 'class="scrub-console"' in result.text, path
                print(f"PASS {origin}{path} and shared CSS")
        assets = (
            (args.controller, "/tablet.css", "css"),
            (args.controller, "/app.js", "javascript"),
            (args.controller, "/tablet.js", "javascript"),
            (args.sim, "/web/page.css", "css"),
            (args.sim, "/web/common.js", "javascript"),
            *((args.ledger, f"/{name}.js", "javascript") for name in ("app", "cases", "memory", "series")),
        )
        for origin, path, kind in assets:
            result = client.get(urljoin(origin, path))
            result.raise_for_status()
            assert kind in result.headers.get("content-type", "")
        result = client.get(urljoin(args.ledger, "/qr.png"))
        result.raise_for_status()
        assert result.content.startswith(b"\x89PNG\r\n\x1a\n")
        print("PASS page layout assets and QR PNG")


if __name__ == "__main__":
    main()
