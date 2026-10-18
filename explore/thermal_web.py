"""Live arm temperature site: http://localhost:8093 (and http://<this Mac's LAN IP>:8093 for the team).

  .venv/bin/python explore/thermal_web.py            # reads MongoDB scrub.thermal (works on any machine with the URI)
  .venv/bin/python explore/thermal_web.py --local    # reads ~/scrub-logs/thermal instead

Big per-motor readouts (green < 55 C, amber 55-59, red >= 60 = cool-down), a 30-minute chart, the
recorder's phase, how old the data is, and the latest guard events. Polls every 3 s.
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import thermal_log as T

KINDS = ["sample", "cooling", "idle", "experiment"]
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])  # controller/ops.html reads /api/data
LOCAL = False


def _temps(r: dict) -> dict:
    if r.get("motors"):
        return {m: v.get("temp") for m, v in r["motors"].items()}
    t = r.get("temps") or {}
    return {T.NAMES[int(k) - 1] if str(k).isdigit() else k: v for k, v in t.items()}


def _rows(since: float) -> list[dict]:
    if LOCAL:
        rows = []
        for p in sorted(T.DIR.glob("*.jsonl"))[-10:]:
            for line in p.read_text().splitlines():
                if line and '"t"' in line:
                    r = json.loads(line)
                    if r["t"] >= since and (r.get("kind") in KINDS or r.get("kind") == "event"):
                        rows.append(r)
        return sorted(rows, key=lambda r: r["t"])
    return list(T._collection().find({"t": {"$gte": since}, "kind": {"$in": KINDS + ["event"]}},
                                     {"_id": 0, "t": 1, "kind": 1, "phase": 1, "motors": 1, "temps": 1,
                                      "event": 1, "motor": 1, "host": 1}).sort("t", 1))


_DIRECT = {"t": 0.0, "temps": None}


def _direct() -> dict | None:
    """With no recorder running, read the follower directly (every 5 s at most), so the page stays live."""
    import subprocess
    if subprocess.run(["pgrep", "-f", "arm_session.py|lerobot-"], capture_output=True).stdout:
        return None  # the recorder owns the port; it logs samples itself
    if time.time() - _DIRECT["t"] > 5:
        _DIRECT["t"] = time.time()
        try:
            regs = T.read_registers(T.PORTS["follower"])
            _DIRECT["temps"] = {m: r["present_temperature"] for m, r in regs.items()}
        except Exception:  # noqa: BLE001 - unplugged or busy
            _DIRECT["temps"] = None
    return {"t": _DIRECT["t"], "kind": "direct", "phase": "recorder stopped", "host": socket.gethostname(),
            "temps": _DIRECT["temps"]} if _DIRECT["temps"] else None


@app.get("/api/data")
def data(minutes: float = 30):
    now = time.time()
    rows = _rows(now - minutes * 60)
    series = [{"t": r["t"], "temps": _temps(r)} for r in rows if r.get("kind") in KINDS]
    if len(series) > 900:  # keep the page light
        step = len(series) // 900 + 1
        series = series[::step] + series[-1:]
    last = next((r for r in reversed(rows) if r.get("kind") in KINDS), None)
    events = [{"t": r["t"], "event": r.get("event"), "motor": r.get("motor")} for r in rows if r.get("kind") == "event"][-8:]
    if (last is None or now - last["t"] > 30) and not LOCAL and (live := _direct()):
        series.append({"t": live["t"], "temps": live["temps"]})
        return {"now": now, "series": series, "events": events, "latest": live}
    return {"now": now, "series": series, "events": events,
            "latest": {"t": last["t"], "kind": last["kind"], "phase": last.get("phase"), "host": last.get("host"),
                       "temps": _temps(last)} if last else None}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Arm Temperatures</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>
:root{--bg:#111312;--panel:#191c1b;--fg:#e6e4dd;--mute:#8f8c84;--rule:#2e3230;--ok:#6fbf86;--warn:#e2b04f;--hot:#ef6f63;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "IBM Plex Sans",system-ui,sans-serif;padding:16px}
header{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline;border-bottom:1px solid var(--rule);padding-bottom:10px;margin-bottom:14px}
h1{font-size:18px;margin:0}.meta{font:13px "IBM Plex Mono",monospace;color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.m{background:var(--panel);border:1px solid var(--rule);padding:12px}
.m .n{font:12px "IBM Plex Mono",monospace;color:var(--mute);text-transform:uppercase;letter-spacing:.05em}
.m .v{font:500 44px/1.1 "IBM Plex Mono",monospace}.m .s{font:12px "IBM Plex Mono",monospace;color:var(--mute)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.hot{color:var(--hot)}
.chart{background:var(--panel);border:1px solid var(--rule);margin-top:12px;padding:8px}svg{width:100%;height:auto;display:block}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font:12px "IBM Plex Mono",monospace;padding:4px}.legend i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}
#ev{font:13px "IBM Plex Mono",monospace;color:var(--mute);margin-top:10px;white-space:pre-wrap}
.ab{background:var(--panel);color:var(--fg);border:1px solid var(--fg);padding:9px 14px;font:500 14px "IBM Plex Sans",sans-serif;cursor:pointer;border-radius:0}
.ab:disabled{opacity:.4;cursor:not-allowed}
select{background:var(--panel);color:var(--fg);border:1px solid var(--rule);font:13px "IBM Plex Mono",monospace}
</style></head><body>
<header><h1>Arm temperatures</h1><span class="meta" id="meta">loading</span>
<span class="meta">window <select id="win"><option value="10">10 min</option><option value="30" selected>30 min</option><option value="120">2 h</option><option value="480">8 h</option></select></span></header>
<div id="armbar" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px">
<button class="ab" data-a="home">Home + motors off</button><button class="ab" data-a="on">Motors on</button><button class="ab" data-a="off">Motors off</button>
<span class="meta" id="armst">arm: checking</span></div>
<div class="grid" id="grid"></div>
<div class="chart"><svg id="svg" viewBox="0 0 900 320"></svg><div class="legend" id="legend"></div></div>
<div id="ev"></div>
<script>
const N=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"];
const C=["#7fb2e5","#ef6f63","#6fbf86","#c39be6","#e2b04f","#5fd0d8"];
const cls=t=>t==null?"":t>=60?"hot":t>=55?"warn":"ok";
function fmtAge(s){return s<90?`${s.toFixed(0)} s ago`:`${(s/60).toFixed(0)} min ago`}
async function tick(){
  let d; try{d=await (await fetch("/api/data?minutes="+document.getElementById("win").value)).json()}catch(e){document.getElementById("meta").textContent="server unreachable";return}
  const L=d.latest, age=L?d.now-L.t:null;
  document.getElementById("meta").textContent=L?`${fmtAge(age)} · ${L.kind}${L.phase?" · "+L.phase:""} · ${L.host||""}${age>30?" · not live (recorder stopped?)":""}`:"no data yet";
  document.getElementById("grid").innerHTML=N.map((n,i)=>{const t=L&&L.temps[n];
    return `<div class="m"><div class="n">${n.replace("_"," ")}</div><div class="v ${cls(t)}">${t??"--"}<small style="font-size:18px">°C</small></div><div class="s">${t==null?"":t>=60?"COOL-DOWN":t>=55?"warm":"ok"}</div></div>`}).join("");
  const S=d.series, W=900,H=320,l=40,r=12,tp=10,b=28; if(!S.length){document.getElementById("svg").innerHTML="";return}
  const t0=S[0].t,t1=Math.max(S[S.length-1].t,t0+60); let lo=40,hi=65;
  S.forEach(p=>N.forEach(n=>{const v=p.temps[n]; if(v!=null){lo=Math.min(lo,v-2);hi=Math.max(hi,v+2)}}));
  const x=t=>l+(W-l-r)*(t-t0)/(t1-t0), y=v=>tp+(H-tp-b)*(hi-v)/(hi-lo); let g="";
  for(let v=Math.ceil(lo/5)*5;v<=hi;v+=5)g+=`<line x1="${l}" x2="${W-r}" y1="${y(v)}" y2="${y(v)}" stroke="#2e3230"/><text x="${l-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="#8f8c84" font-family="IBM Plex Mono">${v}</text>`;
  [55,60].forEach(v=>g+=`<line x1="${l}" x2="${W-r}" y1="${y(v)}" y2="${y(v)}" stroke="${v==60?"#ef6f63":"#e2b04f"}" stroke-dasharray="5 4"/>`);
  for(let k=0;k<=4;k++){const t=t0+(t1-t0)*k/4;g+=`<text x="${x(t)}" y="${H-8}" text-anchor="middle" font-size="11" fill="#8f8c84" font-family="IBM Plex Mono">${new Date(t*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</text>`}
  N.forEach((n,i)=>{let path="",pen=false,prev=null;S.forEach(p=>{const v=p.temps[n];if(v==null){pen=false;return}
    const gap=prev!=null&&p.t-prev>120;path+=(pen&&!gap?"L":"M")+x(p.t).toFixed(1)+","+y(v).toFixed(1);pen=true;prev=p.t});
    g+=`<path d="${path}" fill="none" stroke="${C[i]}" stroke-width="2"/>`});
  document.getElementById("svg").innerHTML=g;
  document.getElementById("legend").innerHTML=N.map((n,i)=>`<span><i style="background:${C[i]}"></i>${n}</span>`).join("");
  document.getElementById("ev").textContent=d.events.length?"recent guard events:\n"+d.events.map(e=>`${new Date(e.t*1000).toLocaleTimeString()}  ${e.event}${e.motor?" "+e.motor:""}`).join("\n"):"";
}
async function armTick(){
  let a; try{a=await (await fetch("/api/arm")).json()}catch(e){return}
  const free=a.free; document.querySelectorAll(".ab").forEach(b=>b.disabled=!free||busy);
  if(!busy) document.getElementById("armst").textContent=free?`arm: motors ${a.torque_on?"ON ("+a.torque_on+"/6)":"OFF"}`:"arm: in use by a recording session (buttons off)";
}
let busy=false;
document.querySelectorAll(".ab").forEach(b=>b.onclick=async()=>{
  busy=true; document.querySelectorAll(".ab").forEach(x=>x.disabled=true);
  const st=document.getElementById("armst"); st.textContent=b.dataset.a==="home"?"moving home...":"working...";
  try{const r=await (await fetch("/api/arm/"+b.dataset.a,{method:"POST"})).json();
    st.textContent=r.ok?(b.dataset.a==="home"?`home reached, motors OFF (off by ${JSON.stringify(r.result.off_by_deg)})`:`motors ${b.dataset.a.toUpperCase()}`):"error: "+r.error;}
  catch(e){st.textContent="error: "+e}
  busy=false; setTimeout(armTick,1500);
});
document.getElementById("win").onchange=tick; tick(); setInterval(tick,3000); armTick(); setInterval(armTick,4000);
</script></body></html>"""


_ARM_LOCK = __import__("threading").Lock()


def _recorder_running() -> bool:
    import subprocess
    return bool(subprocess.run(["pgrep", "-f", "arm_session.py|lerobot-"], capture_output=True).stdout)


@app.post("/api/arm/{action}")
def arm_action(action: str):
    """Home + motors off / motors on / motors off, only while no recorder owns the arm. Local use only."""
    import home_pose
    if action not in ("home", "on", "off"):
        return {"ok": False, "error": "unknown action"}
    if _recorder_running():
        return {"ok": False, "error": "a recording session owns the arm: stop it first"}
    if not _ARM_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "busy with the last button"}
    try:
        result = {"home": home_pose.go_home_and_rest, "on": lambda: home_pose.torque(True),
                  "off": lambda: home_pose.torque(False)}[action]()
        T.get({"source": "thermal_web"}).write({"kind": "event", "event": f"button_{action}", "result": result})
        return {"ok": True, "result": result}
    except SystemExit as e:  # home_pose exits with a readable reason (port busy, no power)
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _ARM_LOCK.release()


@app.get("/api/arm")
def arm_state():
    if _recorder_running():
        return {"free": False}
    try:
        import home_pose
        scs, ph, pk = home_pose._bus()
        try:
            tq = [pk.read1ByteTxRx(ph, i, 40)[0] for i in range(1, 7)]
        finally:
            ph.closePort()
        return {"free": True, "torque_on": sum(tq), "of": 6}
    except BaseException as e:  # noqa: BLE001
        return {"free": False, "error": str(e)}


@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE


def main() -> None:
    global LOCAL
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8093)
    p.add_argument("--local", action="store_true")
    a = p.parse_args()
    LOCAL = a.local
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("8.8.8.8", 80))  # no packet sent: just picks the LAN interface
        ip = sk.getsockname()[0]
        sk.close()
    except OSError:
        ip = "this-mac"
    print(f"arm temperatures: http://localhost:{a.port}  (team: http://{ip}:{a.port})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
