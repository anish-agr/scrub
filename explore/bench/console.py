"""Scrub test bench console, port 8098. Mac only, no real arm or camera needed.

    .venv/bin/python -m controller --sim-arm --port 8031 --sim-port 8032 --setting bench
    .venv/bin/python explore/bench/console.py          # then open http://localhost:8098

Serves console.html and a thin backend: request text -> voice POST /heard (if --voice) or a local
alias match -> controller POST /command; "mirror tray" -> sim POST /scene/items.
Targets can also be set per page load: console.html?controller=...&sim=...&identify=...&voice=...
"""
import argparse
import re
import time
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

HERE = Path(__file__).parent
DEFAULTS = {"controller": "http://localhost:8031", "sim": "http://localhost:8032",
            "identify": "http://localhost:8097", "voice": ""}
RETURN_RE = re.compile(r"\b(return|put (it |that |the .+ )?back|give (it |that )?back|take (it |that )?back)\b")


def make_app(defaults=None):
    base = {**DEFAULTS, **(defaults or {})}
    app = FastAPI(title="Scrub bench console")
    http = httpx.Client(timeout=4.0)

    def cfg(request: Request):
        return {k: (request.query_params.get(k, v) or "").rstrip("/") for k, v in base.items()}

    def call(method, url, **kw):
        """(ok, json-or-text, error). Never raises."""
        try:
            r = http.request(method, url, **kw)
            try:
                data = r.json()
            except ValueError:
                data = r.text
            return r.status_code < 400, data, None if r.status_code < 400 else f"{r.status_code} {str(data)[:200]}"
        except httpx.HTTPError as e:
            return False, None, f"{type(e).__name__}: {e}"

    def sync_setting(c):
        """The sim follows the controller's setting (its layout.json says surgical)."""
        ok, st, _ = call("GET", c["controller"] + "/setting")
        if ok and isinstance(st, dict) and st.get("id"):
            call("POST", c["sim"] + "/scene/setting", json={"setting": st["id"]}, timeout=15.0)

    @app.get("/")
    def page():
        return FileResponse(HERE / "console.html", headers={"cache-control": "no-store"})

    @app.get("/api/config")
    def config(request: Request):
        return cfg(request)

    @app.get("/api/items")
    def items(request: Request):
        sync_setting(cfg(request))
        ok, data, err = call("GET", cfg(request)["controller"] + "/setting")
        return {"ok": ok, "error": err, "setting": data if ok else None}

    @app.get("/api/identify")
    def identify(request: Request):
        c = cfg(request)
        ok, data, err = call("GET", c["identify"] + "/api/state", timeout=1.5)
        return {"ok": ok, "error": err, "state": data if ok else None}

    def match_item(text, setting):
        """Longest id/name/alias found in text -> item id, or None."""
        t = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("-", " ").replace("_", " ")) + " "
        best, best_len = None, 0
        for it in setting.get("items", []):
            words = [it["id"], it.get("name", "")] + list(it.get("aliases", []))
            for w in words:
                w = re.sub(r"[^a-z0-9 ]+", " ", (w or "").lower().replace("_", " ").replace("-", " ")).strip()
                if w and f" {w} " in t and len(w) > best_len:
                    best, best_len = it["id"], len(w)
        return best

    @app.post("/api/request")
    def make_request(request: Request, body: dict = Body(...)):
        """{"text": "..."} free text, or {"action": "handover"|"return", "item": id} from a button."""
        c = cfg(request)
        text = str(body.get("text") or "").strip()
        t0 = time.time()
        if body.get("action") is None and c["voice"]:
            ok, data, err = call("POST", c["voice"] + "/heard", json={"text": text}, timeout=15.0)
            return {"path": "voice", "ok": ok, "error": err, "reply": data, "t": t0}
        ok, setting, err = call("GET", c["controller"] + "/setting")
        if not ok:
            return {"path": "local", "ok": False, "error": f"controller: {err}", "t": t0}
        action = body.get("action")
        item = body.get("item")
        if action is None:
            item = match_item(text, setting)
            action = "return" if RETURN_RE.search(text.lower()) else "handover"
            if re.search(r"\b(stop|halt|freeze)\b", text.lower()):
                action, item = "stop", None
            elif re.search(r"\b(got it|thanks|thank you)\b", text.lower()):
                action, item = "got_it", None
            elif item is None:
                action = "unknown"
        cmd = {"id": uuid.uuid4().hex, "action": action, "item": item,
               "heard": text or f"{action} {item}", "source": "dashboard", "t": t0}  # a contract source
        ok, data, err = call("POST", c["controller"] + "/command", json=cmd)
        return {"path": "local", "ok": ok, "error": err, "command": cmd, "reply": data, "t": t0}

    @app.post("/api/mirror")
    def mirror(request: Request, body: dict = Body(default={})):
        """Put items in the sim where they are. body.items given (manual layout): use it as is.
        Otherwise take the identifier's present items that have arm_xy."""
        c = cfg(request)
        sync_setting(c)
        skipped, items = [], body.get("items")
        source = "manual"
        if items is None:
            source = "identifier"
            ok, st, err = call("GET", c["identify"] + "/api/state", timeout=2.0)
            if not ok:
                return {"ok": False, "source": source, "error": f"identifier not reachable: {err}"}
            items = []
            for it in (st or {}).get("items", []):
                xy = it.get("arm_xy")
                if not it.get("present"):
                    skipped.append({"id": it.get("id"), "why": "not seen by the camera"})
                elif not xy:
                    skipped.append({"id": it.get("id"), "why": "arm_xy is null: no vision/calibration.json, "
                                    "so the camera cannot say where it is in arm meters"})
                else:
                    x, y = (xy.get("x"), xy.get("y")) if isinstance(xy, dict) else xy[:2]
                    items.append({"id": it["id"], "x": x, "y": y, "yaw": it.get("yaw") or 0.0})
        if not items:
            return {"ok": False, "source": source, "skipped": skipped, "results": [],
                    "error": "nothing to move" + (": " + skipped[0]["why"] if skipped else "")}
        ok, data, err = call("POST", c["sim"] + "/scene/items", json={"items": items})
        return {"ok": ok, "source": source, "error": err, "sent": items, "skipped": skipped,
                "results": (data or {}).get("results", []) if ok else []}

    @app.post("/api/reset")
    def reset(request: Request):
        """Items back in their slots, arm home, controller rearmed."""
        c = cfg(request)
        ok, data, err = call("POST", c["controller"] + "/sim/scene_reset", timeout=15.0)
        if ok and isinstance(data, dict) and data.get("ok"):
            sync_setting(c)
            return {"ok": True}
        ok1, _, e1 = call("POST", c["sim"] + "/scene/reset", timeout=15.0)
        ok2, _, e2 = call("POST", c["controller"] + "/reset", timeout=15.0)
        return {"ok": ok1 and ok2, "error": e1 or e2 or ("busy: stop first" if not ok else None)}

    @app.api_route("/api/p/{target}/{path:path}", methods=["GET", "POST"])
    async def proxy(target: str, path: str, request: Request):
        c = cfg(request)
        if target not in c or not c[target]:
            return JSONResponse({"error": f"{target} not configured"}, 404)
        q = {k: v for k, v in request.query_params.items() if k not in base}
        body = await request.body()
        try:
            r = http.request(request.method, f"{c[target]}/{path}", params=q, content=body or None,
                             headers={"content-type": request.headers.get("content-type", "application/json")})
        except httpx.HTTPError as e:
            return JSONResponse({"error": str(e)}, 502)
        return Response(r.content, r.status_code, media_type=r.headers.get("content-type"))

    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8098)
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k}", default=v, help=f"{k} base URL" + (" (optional)" if not v else ""))
    a = ap.parse_args()
    uvicorn.run(make_app({k: getattr(a, k) for k in DEFAULTS}), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
