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
}


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/stats":
            self._json(stats())
            return
        if path == "/api/cases":
            self._json(list_cases())
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
        body = (PUBLIC / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def serve() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"public page on http://127.0.0.1:{port}")
    server.serve_forever()
