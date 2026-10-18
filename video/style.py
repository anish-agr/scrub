"""Scrub paper/monitor typography; no gradients, animation or invented metrics."""
from __future__ import annotations

from urllib.request import urlopen

from .common import BASE

FONTS = {
    'Archivo.ttf':'https://raw.githubusercontent.com/google/fonts/main/ofl/archivo/Archivo%5Bwdth,wght%5D.ttf',
    'IBMPlexMono-Regular.ttf':'https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexmono/IBMPlexMono-Regular.ttf',
}


def ensure_fonts():
    folder=BASE/'fonts'
    folder.mkdir(exist_ok=True,parents=True)
    for name,url in FONTS.items():
        path=folder/name
        if not path.exists():
            with urlopen(url,timeout=60) as response:
                content=response.read()
            if len(content)<10000:
                raise ValueError("Font download incomplete; supply licensed Archivo and IBM Plex Mono TTFs in data/video/fonts/")
            path.write_bytes(content)
    return folder


CSS = """
* { box-sizing:border-box; }
html,body { margin:0; width:1920px; height:1080px; overflow:hidden; }
body { background:#ece8dd; color:#14130f; font-family:Archivo,Arial,sans-serif; padding:82px 96px; }
header { border-bottom:4px solid #14130f; padding-bottom:20px; display:flex; justify-content:space-between; align-items:baseline; }
.brand { font-weight:900; font-size:62px; letter-spacing:-2px; }
.label { font-size:22px; letter-spacing:.14em; text-transform:uppercase; color:#625f55; }
h1 { font-size:106px; letter-spacing:-3px; line-height:1.04; max-width:1650px; margin:110px 0 42px; }
p { font-size:38px; max-width:1550px; line-height:1.35; }
.mono,td { font-family:Plex,monospace; font-variant-numeric:tabular-nums; }
table { border-collapse:collapse; width:100%; font-size:27px; margin-top:40px; }
th,td { border-bottom:1px solid #b9b4a4; padding:15px 12px; text-align:left; }
th { font-size:20px; letter-spacing:.14em; text-transform:uppercase; }
footer { position:absolute; left:96px; right:96px; bottom:60px; border-top:2px solid #14130f; padding-top:20px; font-size:22px; color:#625f55; }
.disclosure { background:#14130f; color:#ece8dd; padding:12px 18px; font-family:Plex,monospace; font-size:23px; }
.end h1 { margin:48px 0 22px; font-size:64px; }
"""
