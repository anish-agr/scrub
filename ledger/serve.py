"""Read-only page for the count and the success tables. No arm controls."""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ledger import stats
from ledger.cases import case_view, list_cases
from ledger.qr import png_bytes, public_url

_CASE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

PUBLIC = Path(__file__).resolve().parent / "public"
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/cases.html": ("cases.html", "text/html; charset=utf-8"),
    "/case.html": ("case.html", "text/html; charset=utf-8"),
    "/cases.js": ("cases.js", "text/javascript; charset=utf-8"),
    "/card.html": ("card.html", "text/html; charset=utf-8"),
    "/qr.png": ("qr.png", "image/png"),
}


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")  # read-only GETs, any origin may read
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            self._route()
        except Exception:
            try:
                self._json({"error": "ledger failed"}, 500)
            except Exception:
                return

    def _route(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/favicon.ico":
            self.send_response(204)  # no icon file; stops the browser's 404 in the console
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/stats":
            sim = (parse_qs(parsed.query).get("sim") or [""])[0] in ("1", "true")
            self._json(stats(include_sim=sim))  # ?sim=1 also counts fake-arm and sim rows
            return
        if path == "/api/cases":
            self._json(list_cases())
            return
        if path == "/api/public":
            self._json({"url": public_url()})
            return
        if path == "/qr.png":
            try:
                body = png_bytes()
            except Exception:
                body = b""
            if body:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        if path == "/api/case":
            case_id = (parse_qs(parsed.query).get("id") or [""])[0]
            if not _CASE_ID.fullmatch(case_id):
                self._json({"error": "bad case id"}, 400)
                return
            view = case_view(case_id)
            if view is None:
                self._json({"error": "no case"}, 404)
                return
            self._json(view)
            return
        item = FILES.get(path)
        if item is None:
            self.send_error(404)
            return
        name, content_type = item
        try:
            body = (PUBLIC / name).read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def serve() -> None:
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")  # the server service sets 127.0.0.1: only nginx reaches it
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"public page on http://127.0.0.1:{port}")
    server.serve_forever()
