"""FastAPI app: the endpoints in docs/CONTRACTS.md."""
import asyncio
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core import Controller

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"


class Command(BaseModel):
    id: Optional[str] = None
    action: str
    item: Optional[str] = None
    heard: Optional[str] = None
    source: Optional[str] = None
    t: Optional[float] = None


class Setting(BaseModel):
    setting: str


class Lighting(BaseModel):
    lighting: Literal["bright", "normal", "dim"]
    lux: Optional[float] = None


class Force(BaseModel):
    miss_grasp: int = 0
    out_of_region: int = 0
    skill_fail: int = 0
    no_pull: int = 0


def make_app(ctl: Controller, extra=None) -> FastAPI:
    """extra(app) adds routes before the dashboard mount at / (which would shadow them)."""
    app = FastAPI(title="Scrub controller")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.post("/command")
    async def command(cmd: Command):
        return ctl.submit(cmd.model_dump())

    @app.post("/stop")
    async def stop():
        ctl.stop()
        return {"accepted": True}

    @app.post("/reset")
    async def reset():
        """Clear a stop: home, open the gripper, clear the count."""
        try:
            ctl.reset()
        except RuntimeError:
            raise HTTPException(409, "busy: stop first")
        return {"ok": True}

    @app.get("/state")
    async def state():
        return ctl.state()

    @app.get("/setting")
    async def current_setting():
        return ctl.setting

    @app.post("/setting")
    async def setting(body: Setting):
        try:
            return ctl.set_setting(body.setting)
        except KeyError:
            raise HTTPException(404, f"no setting {body.setting!r}")
        except RuntimeError:
            raise HTTPException(409, "busy: stop or wait for idle before switching trays")

    @app.post("/lighting")
    async def lighting(body: Lighting):
        ctl.set_lighting(body.lighting, body.lux)
        return {"ok": True}

    @app.post("/vision/tray")
    async def vision_tray(body: dict):
        ctl.post_tray(body)
        return {"ok": True}

    @app.post("/vision/hand")
    async def vision_hand(body: dict):
        ctl.post_hand(body)
        return {"ok": True}

    @app.get("/stats")
    async def stats():
        return await asyncio.to_thread(ctl.stats)

    @app.get("/events/recent")
    async def recent(n: int = 50):
        return list(ctl.history)[-n:]

    @app.post("/fake/force")
    async def fake_force(body: Force):
        """Force the next failures on the fake arm (testing only)."""
        if not hasattr(ctl.arm, "force"):
            raise HTTPException(400, "only with --fake-arm")
        for k, v in body.model_dump().items():
            if v:
                ctl.arm.force[k] = ctl.arm.force.get(k, 0) + v
        return {"force": ctl.arm.force}

    @app.post("/fake/pull")
    async def fake_pull():
        """Simulate the clinician tugging the item (sim arm), else the same as got_it."""
        if ctl.fake_arm and hasattr(ctl.arm, "pull"):
            ctl.arm.pull()
            return {"ok": True}
        return ctl.submit({"action": "got_it", "source": "dashboard"})

    @app.websocket("/events")
    async def events(ws: WebSocket):
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue()
        entry = (asyncio.get_running_loop(), q)
        ctl.listeners.append(entry)
        try:
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            ctl.listeners.remove(entry)

    if extra:
        extra(app)
    if (DASHBOARD / "index.html").exists():
        app.mount("/", StaticFiles(directory=DASHBOARD, html=True), name="dashboard")
    else:
        @app.get("/", response_class=HTMLResponse)
        async def placeholder():
            return PLACEHOLDER

    return app


# Shown until Evan's dashboard/index.html lands.
PLACEHOLDER = """<!doctype html><meta charset=utf-8><title>Scrub controller</title>
<style>body{font:15px system-ui;margin:24px;background:#fff;color:#111}pre{background:#f4f4f4;padding:8px;height:60vh;overflow:auto}
button{font-size:15px;margin:2px}#stop{background:#c00;color:#fff;font-weight:bold}</style>
<h1>Scrub controller</h1><p>Placeholder until <code>dashboard/index.html</code> exists. Space = stop.</p>
<div id=btns></div><button id=stop onclick="post('/stop')">STOP</button>
<p id=state></p><pre id=log></pre>
<script>
const post=(u,b)=>fetch(u,{method:'POST',headers:{'content-type':'application/json'},body:b?JSON.stringify(b):undefined}).then(r=>r.json());
const cmd=(action,item)=>post('/command',{action,item,source:'dashboard',t:Date.now()/1000});
async function refresh(){const s=await (await fetch('/state')).json();document.getElementById('state').textContent=JSON.stringify(s)}
async function init(){const s=await (await fetch('/setting')).json();
 const b=document.getElementById('btns');(s?s.items:[]).forEach(i=>{const e=document.createElement('button');e.textContent=i.name;e.onclick=()=>cmd('handover',i.id);b.append(e)});
 [['return',null],['count',null],['got_it',null]].forEach(([a])=>{const e=document.createElement('button');e.textContent=a;e.onclick=()=>cmd(a,null);b.append(e)})}
const ws=new WebSocket(`ws://${location.host}/events`);ws.onmessage=m=>{const e=JSON.parse(m.data);const l=document.getElementById('log');
 l.textContent=`${new Date(e.t*1000).toLocaleTimeString()} ${e.type} ${e.step||''} ${e.item||''} ${e.say?'"'+e.say+'"':''}\\n`+l.textContent;refresh()};
document.onkeydown=e=>{if(e.code==='Space'){e.preventDefault();post('/stop')}};init();refresh();
</script>"""
