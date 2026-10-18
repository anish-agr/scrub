"""Printable props for the OCR work: count sheets, tray tags, sterile pack labels.

Run: .venv/bin/python -m explore.recognition.props [--out DIR]

Writes HTML (to print), PNG (clean test images for code agents) and truth.json
(ground truth to score OCR against). No network, no browser: the PNGs are drawn
with Pillow using the same layout in inches as the HTML.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "settings"
OUT = Path(__file__).resolve().parent / "props"
TRAYS = ("surgical", "bench")
PX_WIDTH = 1600
REFERENCE_DATE = "2026-10-18"
INK = (20, 19, 15)
PEN = (28, 38, 120)

FILLED = {"initial": [1, 1, 1], "closing": [1, 0, 1]}
FILLED_FIELDS = {"date": "2026-10-18", "case": "C-0417", "counted_by": "J. Rivera"}


def filled_value(key: str, i: int) -> int:
    """The handwritten count for row i; trays longer than FILLED repeat it (bench has 5 rows)."""
    return FILLED[key][i % len(FILLED[key])]


# 4 sterile pack labels. Items come from the surgical tray.
PACKS = [
    {"item": "scalpel", "lot": "SC-24-0917", "sterilized": "2026-09-02", "expires": "2027-03-15"},
    {"item": "hemostat", "lot": "SC-24-0918", "sterilized": "2026-09-02", "expires": "2027-01-20"},
    {"item": "mayo scissors", "lot": "SC-24-0611", "sterilized": "2026-08-01", "expires": "2026-09-30"},
    {"item": "scalpel", "lot": "SC-24-0921", "sterilized": "2026-10-05", "expires": None},
]
METHOD = "Steam 132 C 4 min"
CLASS = "Class 5 indicator"
INDICATOR = "Indicator: PASS"


# ---------- data ----------

def load_tray(tray_id: str) -> dict:
    data = json.loads((SETTINGS / f"{tray_id}.json").read_text())
    items = [
        {"id": it["id"], "name": it["name"], "expected": int(it.get("qty", 1))}
        for it in data["items"]
    ]
    return {"id": data["id"], "label": data["label"], "title": f'{data["label"]} ({data["id"]})', "items": items}


def qr_payload(tray_id: str) -> str:
    return f"scrub:tray:{tray_id}"


def qr_matrix(text: str) -> list[list[bool]]:
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    q.add_data(text)
    q.make(fit=True)
    return q.get_matrix()


def qr_svg(text: str, quiet: int = 2) -> str:
    m = qr_matrix(text)
    n = len(m) + 2 * quiet
    rects = "".join(
        f'<rect x="{x + quiet}" y="{y + quiet}" width="1" height="1"/>'
        for y, row in enumerate(m) for x, on in enumerate(row) if on
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><g fill="#000">{rects}</g></svg>')


def qr_image(text: str, size: int, quiet: int = 2) -> Image.Image:
    m = qr_matrix(text)
    n = len(m) + 2 * quiet
    cell = max(1, size // n)
    img = Image.new("RGB", (n * cell, n * cell), "white")
    d = ImageDraw.Draw(img)
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            if on:
                d.rectangle([(x + quiet) * cell, (y + quiet) * cell, (x + quiet + 1) * cell - 1, (y + quiet + 1) * cell - 1], fill="black")
    return img


# ---------- drawing helpers ----------

_SANS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
_SANS_REG = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
_MONO = ["/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"]
_HAND = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Italic.ttf", "DejaVuSans-Oblique.ttf"]


def font(kind: str, px: int) -> ImageFont.FreeTypeFont:
    names = {"sans": _SANS, "reg": _SANS_REG, "mono": _MONO, "hand": _HAND}[kind]
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


class Canvas:
    """Draw in inches. `ppi` is pixels per inch."""

    def __init__(self, w_in: float, h_in: float, ppi: float):
        self.ppi = ppi
        self.img = Image.new("RGB", (round(w_in * ppi), round(h_in * ppi)), "white")
        self.d = ImageDraw.Draw(self.img)

    def u(self, v: float) -> int:
        return round(v * self.ppi)

    def rect(self, x, y, w, h, line=0.03, fill=None):
        u = self.u
        if fill:
            self.d.rectangle([u(x), u(y), u(x + w) - 1, u(y + h) - 1], fill=fill)
        if line:
            self.d.rectangle([u(x), u(y), u(x + w) - 1, u(y + h) - 1], outline=INK, width=max(1, u(line)))

    def hline(self, x, y, w, t=0.03):
        self.d.rectangle([self.u(x), self.u(y), self.u(x + w) - 1, self.u(y) + max(1, self.u(t)) - 1], fill=INK)

    def text(self, x, y, s, size, kind="sans", fill=INK, anchor="la", w=None):
        """size in inches (font px height). w: shrink font to fit this width."""
        px = self.u(size)
        f = font(kind, px)
        if w is not None:
            while px > 8 and self.d.textlength(s, font=f) > self.u(w):
                px -= 2
                f = font(kind, px)
        self.d.text((self.u(x), self.u(y)), s, font=f, fill=fill, anchor=anchor)

    def paste_qr(self, text, x, y, size):
        q = qr_image(text, self.u(size)).resize((self.u(size), self.u(size)), Image.NEAREST)
        self.img.paste(q, (self.u(x), self.u(y)))


# ---------- handwriting ----------

_STROKES = {
    "0": [[(0.5 + 0.38 * math.cos(t), 0.5 + 0.5 * math.sin(t)) for t in np.linspace(-1.9, 4.5, 26)]],
    "1": [[(0.28, 0.25), (0.52, 0.0), (0.52, 1.0)]],
}


def hand_digit(layer: ImageDraw.ImageDraw, ch: str, cx: float, cy: float, height: float, rng: random.Random):
    """Draw one digit with jitter and slight rotation. Units in layer pixels."""
    rot = math.radians(rng.uniform(-8, 8))
    width = max(3, int(height * 0.07))
    for stroke in _STROKES[ch]:
        pts = []
        for px, py in stroke:
            x = (px - 0.5) * height * 0.62 + rng.uniform(-1, 1) * height * 0.025
            y = (py - 0.5) * height + rng.uniform(-1, 1) * height * 0.025
            pts.append((cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)))
        layer.line(pts, fill=PEN, width=width, joint="curve")
        for p in (pts[0], pts[-1]):
            layer.ellipse([p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2], fill=PEN)


def hand_text(img: Image.Image, x, y, s, size_px, angle=-1.5):
    """Script-like text for date/case/name fields. x,y is the baseline-left in px."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((x, y), s, font=font("hand", size_px), fill=PEN + (255,), anchor="ls")
    layer = layer.rotate(angle, center=(x, y), resample=Image.BICUBIC)
    img.paste(layer, (0, 0), layer)


# ---------- count sheet ----------

M = 0.6  # page margin, inches
TABLE_COLS = [("Item", 3.0), ("Expected", 1.2), ("Initial count", 1.55), ("Closing count", 1.55)]
TABLE_Y, HEAD_H = 3.75, 0.62
FIELDS = [("Date", M, 2.0), ("Case", M + 2.3, 2.3), ("Counted by", M + 4.9, 2.4)]
FIELD_LINE_Y = 3.3


def row_h(n: int) -> float:
    return min(1.3, 5.6 / max(1, n))


def draw_count_sheet(tray: dict, filled: bool = False, seed: int = 7) -> Image.Image:
    ppi = PX_WIDTH / 8.5
    c = Canvas(8.5, 11, ppi)
    w = 8.5 - 2 * M
    c.rect(M, 0.55, w, 0.08, line=0, fill=INK)
    c.text(M, 0.78, "SCRUB", 0.2)
    c.text(M, 1.02, "Scrub count sheet", 0.6)
    c.text(M, 1.78, tray["title"], 0.36, w=5.3)
    c.text(M, 2.25, f'Tray id: {tray["id"]}', 0.26, "mono")
    qs = 1.75
    qx = 8.5 - M - qs
    c.paste_qr(qr_payload(tray["id"]), qx, 0.8, qs)
    c.text(qx + qs / 2, 2.6, qr_payload(tray["id"]), 0.15, "mono", anchor="ma")

    for label, x, fw in FIELDS:
        c.text(x, FIELD_LINE_Y - 0.55, label.upper(), 0.17)
        c.hline(x, FIELD_LINE_Y, fw, 0.035)

    xs = [M]
    for _, cw in TABLE_COLS:
        xs.append(xs[-1] + cw)
    rh = row_h(len(tray["items"]))
    total_h = HEAD_H + rh * len(tray["items"])
    c.rect(xs[0], TABLE_Y, xs[-1] - xs[0], HEAD_H, line=0.04, fill=(226, 222, 210))
    for (name, _), x0, x1 in zip(TABLE_COLS, xs, xs[1:]):
        left = name == "Item"
        c.text(x0 + 0.15 if left else (x0 + x1) / 2, TABLE_Y + HEAD_H / 2, name.upper(), 0.2,
               anchor="lm" if left else "mm", w=(x1 - x0) - 0.2)
    for i, it in enumerate(tray["items"]):
        y = TABLE_Y + HEAD_H + i * rh
        for x0, x1 in zip(xs, xs[1:]):
            c.rect(x0, y, x1 - x0, rh + 0.04, line=0.04)
        c.text(xs[0] + 0.15, y + rh / 2, it["name"], 0.42, anchor="lm", w=TABLE_COLS[0][1] - 0.3)
        c.text((xs[1] + xs[2]) / 2, y + rh / 2, str(it["expected"]), 0.6, anchor="mm")
    c.text(M, TABLE_Y + total_h + 0.35, "Write one number per box. Count every item in and out.", 0.22, "reg")
    c.text(M, 10.55, "Team Scrub  |  DubHacks '26  |  Print at 100% on US Letter", 0.16, "reg")

    if filled:
        rng = random.Random(seed)
        ss = 2
        layer_img = Image.new("RGBA", (c.img.width * ss, c.img.height * ss), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer_img)
        for i in range(len(tray["items"])):
            y = TABLE_Y + HEAD_H + i * rh + rh / 2
            for col, key in ((2, "initial"), (3, "closing")):
                cx = (xs[col] + xs[col + 1]) / 2 + rng.uniform(-0.08, 0.08)
                hand_digit(ld, str(filled_value(key, i)), cx * ppi * ss, (y + rng.uniform(-0.05, 0.05)) * ppi * ss,
                           rh * 0.55 * ppi * ss, rng)
        layer_img = layer_img.resize(c.img.size, Image.LANCZOS)
        c.img.paste(layer_img, (0, 0), layer_img)
        for (_, x, _), key in zip(FIELDS, ("date", "case", "counted_by")):
            hand_text(c.img, c.u(x + 0.1), c.u(FIELD_LINE_Y - 0.06), FILLED_FIELDS[key], c.u(0.4), angle=rng.uniform(-2, 1))
    return c.img


# ---------- tray tag ----------

def draw_tray_tag(tray: dict) -> Image.Image:
    ppi = PX_WIDTH / 4.0
    c = Canvas(4.0, 2.5, ppi)
    c.rect(0.04, 0.04, 3.92, 2.42, line=0.05)
    c.rect(0.04, 0.04, 3.92, 0.1, line=0, fill=INK)
    c.paste_qr(qr_payload(tray["id"]), 0.15, 0.3, 2.05)
    x = 2.2
    c.text(x, 0.3, "TRAY", 0.5, w=1.65)
    c.text(x, 0.95, tray["label"], 0.3, w=1.6)
    c.text(x, 1.4, tray["id"].upper(), 0.38, "mono", w=1.7)
    c.text(x, 1.95, qr_payload(tray["id"]), 0.1, "mono", w=1.7)
    return c.img


# ---------- pack labels ----------

LABEL_W, LABEL_H, LABEL_GAP, LABEL_TOP = 7.2, 2.3, 0.18, 0.5


def draw_pack_labels() -> Image.Image:
    ppi = PX_WIDTH / 8.5
    c = Canvas(8.5, 11, ppi)
    for i, p in enumerate(PACKS):
        x, y = (8.5 - LABEL_W) / 2, LABEL_TOP + i * (LABEL_H + LABEL_GAP)
        c.rect(x, y, LABEL_W, LABEL_H, line=0.035)
        c.rect(x, y, 1.7, LABEL_H, line=0, fill=INK)
        c.text(x + 0.85, y + LABEL_H / 2, "STERILE", 0.32, anchor="mm", fill="white", w=1.5)
        tx = x + 1.95
        c.text(tx, y + 0.12, p["item"], 0.5, w=5.0)
        c.text(tx, y + 0.8, f'LOT {p["lot"]}', 0.27, "mono")
        c.text(tx, y + 1.1, f'Sterilized {p["sterilized"]}', 0.27, "mono")
        c.text(tx, y + 1.4, f'Expires {p["expires"]}' if p["expires"] else "Event related", 0.27, "mono")
        c.text(tx, y + 1.74, METHOD, 0.22, "mono")
        c.text(tx, y + 1.98, f"{CLASS}   {INDICATOR}", 0.2, "mono", w=5.1)
    return c.img


# ---------- angle ----------

def perspective(img: Image.Image, yaw_edge: float = 0.84, tilt_deg: float = 4.0, pad: float = 0.14) -> Image.Image:
    """Photo-like view: page turned about 20 degrees about its vertical axis, on a table."""
    a = np.array(img)
    h, w = a.shape[:2]
    cw, ch = int(w * (1 + 2 * pad)), int(h * (1 + 2 * pad))
    ramp = np.linspace(0, 18, cw).astype(np.uint8)[None, :, None]
    bg = (np.full((ch, cw, 3), (92, 88, 80), np.uint8) + ramp).astype(np.uint8)
    ox, oy = int(w * pad), int(h * pad)
    bg[oy:oy + h, ox:ox + w] = a
    src = np.float32([[ox, oy], [ox + w, oy], [ox + w, oy + h], [ox, oy + h]])
    sc = math.cos(math.radians(20))
    inset = h * (1 - yaw_edge) / 2
    dst = np.float32([[ox, oy], [ox + w * sc, oy + inset], [ox + w * sc, oy + h - inset], [ox, oy + h]])
    t = math.radians(tilt_deg)
    ctr = np.float32([cw / 2, ch / 2])
    rot = np.float32([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    dst = ((dst - ctr) @ rot.T + ctr).astype(np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(bg, m, (cw, ch), flags=cv2.INTER_CUBIC, borderValue=(92, 88, 80))
    out = cv2.GaussianBlur(out, (3, 3), 0.6)
    s = PX_WIDTH / cw
    return Image.fromarray(out).resize((PX_WIDTH, round(ch * s)), Image.LANCZOS)


# ---------- html ----------

CSS = """
:root{--ink:#14130f;--mute:#625f55;--hair:#b9b4a4;--paper2:#e3dfd2}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font-family:'Archivo',Arial,Helvetica,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.mono{font-family:'IBM Plex Mono','Courier New',monospace;font-weight:700}
@page{size:Letter;margin:0}
"""


def page(title: str, body: str, extra: str = "") -> str:
    return (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><style>{CSS}{extra}</style></head>'
            f'<body>{body}</body></html>\n')


def html_count_sheet(tray: dict) -> str:
    rows = "".join(
        f'<tr><td class="item">{it["name"]}</td><td class="exp">{it["expected"]}</td><td></td><td></td></tr>'
        for it in tray["items"]
    )
    rh = row_h(len(tray["items"]))
    css = f"""
.sheet{{width:8.5in;height:11in;position:relative;overflow:hidden}}
.sheet>*{{position:absolute}}
.rule{{left:{M}in;right:{M}in;top:.55in;height:.08in;background:var(--ink)}}
.kick{{left:{M}in;top:.72in;font-weight:700;font-size:.2in;letter-spacing:.14em}}
h1{{left:{M}in;top:.9in;margin:0;font-size:.6in;font-weight:900;letter-spacing:-.02em;line-height:1}}
.tray{{left:{M}in;top:1.7in;font-size:.36in;font-weight:700}}
.tid{{left:{M}in;top:2.2in;font-size:.26in}}
.qr{{right:{M}in;top:.8in;width:1.75in;height:1.75in}}
.qr svg{{width:100%;height:100%;display:block}}
.qrt{{right:{M}in;top:2.55in;width:1.75in;text-align:center;font-size:.1in}}
.f{{top:2.75in;font-weight:700;font-size:.17in;letter-spacing:.1em;text-transform:uppercase;border-bottom:.035in solid var(--ink);height:.55in}}
table{{left:{M}in;top:{TABLE_Y}in;border-collapse:collapse;table-layout:fixed;width:{sum(w for _, w in TABLE_COLS)}in}}
th{{height:{HEAD_H}in;background:var(--paper2);border:.04in solid var(--ink);font-size:.2in;letter-spacing:.08em;text-transform:uppercase;text-align:center}}
th:first-child{{text-align:left;padding-left:.15in}}
td{{height:{rh}in;border:.04in solid var(--ink)}}
td.item{{font-size:.42in;font-weight:700;padding-left:.15in}}
td.exp{{font-size:.6in;font-weight:700;text-align:center}}
.note{{left:{M}in;top:{TABLE_Y + HEAD_H + rh * len(tray["items"]) + 0.2}in;font-size:.22in}}
.foot{{left:{M}in;top:10.45in;font-size:.16in}}
@media screen{{body{{background:#ddd}}.sheet{{background:#fff;margin:16px auto}}}}
"""
    cols = "".join(f'<col style="width:{w}in">' for _, w in TABLE_COLS)
    heads = "".join(f"<th>{n}</th>" for n, _ in TABLE_COLS)
    fields = "".join(f'<div class="f" style="left:{x}in;width:{fw}in">{label}</div>' for label, x, fw in FIELDS)
    body = (f'<main class="sheet"><div class="rule"></div><div class="kick">SCRUB</div><h1>Scrub count sheet</h1>'
            f'<div class="tray">{tray["title"]}</div><div class="tid mono">Tray id: {tray["id"]}</div>'
            f'<div class="qr">{qr_svg(qr_payload(tray["id"]))}</div><div class="qrt mono">{qr_payload(tray["id"])}</div>'
            f'{fields}<table><colgroup>{cols}</colgroup><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table>'
            f'<div class="note">Write one number per box. Count every item in and out.</div>'
            f'<div class="foot">Team Scrub | DubHacks \'26 | Print at 100% on US Letter</div></main>')
    return page("Scrub count sheet - " + tray["id"], body, css)


def html_tray_tag(tray: dict) -> str:
    css = """
.tag{width:4in;height:2.5in;border:.05in solid var(--ink);position:relative;overflow:hidden}
.bar{position:absolute;left:0;right:0;top:0;height:.1in;background:var(--ink)}
.qr{position:absolute;left:.11in;top:.26in;width:2.05in;height:2.05in}.qr svg{width:100%;height:100%;display:block}
.t{position:absolute;left:2.16in;width:1.75in}
.k{top:.2in;font-size:.5in;font-weight:900}.l{top:.9in;font-size:.3in;font-weight:700;line-height:1.05}
.i{top:1.4in;font-size:.38in}.p{top:1.92in;font-size:.1in}
body{padding:.5in}
"""
    body = (f'<div class="tag"><div class="bar"></div><div class="qr">{qr_svg(qr_payload(tray["id"]))}</div>'
            f'<div class="t k">TRAY</div><div class="t l">{tray["label"]}</div>'
            f'<div class="t i mono">{tray["id"].upper()}</div><div class="t p mono">{qr_payload(tray["id"])}</div></div>')
    return page("Scrub tray tag - " + tray["id"], body, css)


def html_pack_labels() -> str:
    css = f"""
.sheet{{width:8.5in;height:11in;padding:{LABEL_TOP}in 0 0 {(8.5 - LABEL_W) / 2}in}}
.lab{{width:{LABEL_W}in;height:{LABEL_H}in;border:.035in solid var(--ink);margin-bottom:{LABEL_GAP}in;display:flex;break-inside:avoid}}
.st{{width:1.7in;background:var(--ink);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.32in;font-weight:900;letter-spacing:.04em}}
.tx{{padding:.08in .15in;flex:1}}
.nm{{font-size:.5in;font-weight:900;line-height:1.1;margin-bottom:.12in}}
.tx .mono{{font-size:.27in;line-height:.3in}}
.tx .sm{{font-size:.22in;line-height:.28in;margin-top:.06in}}.tx .sm2{{font-size:.2in;line-height:.26in}}
@media screen{{body{{background:#ddd}}.sheet{{background:#fff;margin:16px auto}}}}
"""
    labs = ""
    for p in PACKS:
        exp = f'Expires {p["expires"]}' if p["expires"] else "Event related"
        labs += (f'<div class="lab"><div class="st">STERILE</div><div class="tx"><div class="nm">{p["item"]}</div>'
                 f'<div class="mono">LOT {p["lot"]}<br>Sterilized {p["sterilized"]}<br>{exp}</div>'
                 f'<div class="mono sm">{METHOD}</div><div class="mono sm2">{CLASS}&nbsp;&nbsp;&nbsp;{INDICATOR}</div></div></div>')
    return page("Scrub sterile pack labels", f'<main class="sheet">{labs}</main>', css)


# ---------- truth ----------

def count_truth(tray: dict, filled: bool, angle: int = 0) -> dict:
    items = []
    for i, it in enumerate(tray["items"]):
        items.append({**it, "initial": filled_value("initial", i) if filled else None,
                      "closing": filled_value("closing", i) if filled else None})
    t = {"kind": "count_sheet", "tray_id": tray["id"], "tray_label": tray["label"], "title": "Scrub count sheet",
         "qr": qr_payload(tray["id"]), "items": items, "angle_deg": angle}
    t.update(FILLED_FIELDS if filled else {"date": None, "case": None, "counted_by": None})
    return t


def pack_truth(angle: int = 0) -> dict:
    labels = []
    for p in PACKS:
        labels.append({"item": p["item"], "lot": p["lot"], "sterilized": p["sterilized"], "expires": p["expires"],
                       "event_related": p["expires"] is None, "method": METHOD, "indicator_class": CLASS,
                       "indicator": INDICATOR, "expired": bool(p["expires"] and p["expires"] < REFERENCE_DATE)})
    return {"kind": "pack_labels", "reference_date": REFERENCE_DATE, "labels": labels, "angle_deg": angle}


# ---------- main ----------

def save(img: Image.Image, path: Path) -> None:
    img.save(path, optimize=True)


def generate(out: Path | str = OUT) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    truth: dict[str, dict] = {}
    for tid in TRAYS:
        tray = load_tray(tid)
        (out / f"count_sheet_{tid}.html").write_text(html_count_sheet(tray))
        (out / f"tray_tag_{tid}.html").write_text(html_tray_tag(tray))
        save(draw_count_sheet(tray), out / f"count_sheet_{tid}.png")
        truth[f"count_sheet_{tid}.png"] = count_truth(tray, False)
        filled = draw_count_sheet(tray, filled=True)
        save(filled, out / f"count_sheet_{tid}_filled.png")
        truth[f"count_sheet_{tid}_filled.png"] = count_truth(tray, True)
        save(draw_tray_tag(tray), out / f"tray_tag_{tid}.png")
        truth[f"tray_tag_{tid}.png"] = {"kind": "tray_tag", "tray_id": tray["id"], "tray_label": tray["label"],
                                        "qr": qr_payload(tid), "text": ["TRAY", tray["label"], tid.upper()]}
        if tid == "surgical":
            save(perspective(filled), out / "count_sheet_surgical_angle.png")
            truth["count_sheet_surgical_angle.png"] = count_truth(tray, True, angle=20)
    (out / "pack_labels.html").write_text(html_pack_labels())
    packs = draw_pack_labels()
    save(packs, out / "pack_labels.png")
    truth["pack_labels.png"] = pack_truth()
    save(perspective(packs), out / "pack_labels_angle.png")
    truth["pack_labels_angle.png"] = pack_truth(angle=20)
    (out / "truth.json").write_text(json.dumps({"files": truth}, indent=2) + "\n")
    return truth


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m explore.recognition.props", description=__doc__)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    generate(args.out)
    print(f"wrote props to {args.out}")


if __name__ == "__main__":
    main()
