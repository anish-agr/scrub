"""Rough cut of the demo video, in the order of the edit plan (team/DEVPOST.md, "Video edit plan").

Each beat uses the real clip if one is in data/video/kit/real/<slot>.mp4 (A1.mp4 for the hemostat, and so on),
else the labeled sim clip from data/video/kit/sim/ if that beat has one, else a "TO FILM" card. Rerun it after
dropping in each real take; the cut fills in by itself. Cards follow the Scrub design system (paper, ink, mono).

  python -m video.roughcut            # writes data/video/kit/rough-cut.mp4 and prints what is real, sim or missing
  python -m video.roughcut --cards    # only (re)draw the cards into data/video/kit/cards/

Sim footage is always labeled SIMULATION in the picture (video/simcine.py burns it in). Don't relabel it.
"""
import argparse
import subprocess
from pathlib import Path

KIT = Path("data/video/kit")
W, H, FPS = 1920, 1080, 30
PAPER, INK, MUTE, AMBER, RED = (236, 232, 221), (20, 19, 15), (98, 95, 85), (154, 91, 0), (200, 32, 26)

# slot, seconds in the plan, sim stand-in, title on the card, what to film (team/VIDEO.md)
BEATS = [
    ("V0", 20, "S0-establishing.mp4", "Why we built it",
     "Anish and Caiden tell the two stories in their own voices (phone voice memo), over the arm at rest and photos of the station."),
    ("V1", 2, None, "\"Hemostat.\"", "The phone on speaker, the word \"hemostat\"."),
    ("V2", 14, "S1-hemostat-handoff.mp4", "The pick and the handoff",
     "The pick from the tray (captioned model or taught), the carry, handle first into an open gloved hand, the pull, the gripper opening."),
    ("V3", 7, "S2-scalpel-safe-spot.mp4", "Scalpel to the safe spot", "\"Scalpel.\" Set on the safe spot, never the hand. \"Scalpel down.\""),
    ("V4", 5, None, "Stop", "\"Stop\" mid-move, the red STOPPED banner on the dashboard, the reset."),
    ("V5", 10, None, "The hand", "The hand tracker's view of the open hand, the arm slowing near it, the hand pulled away, the arm holding."),
    ("V6", 12, None, "Bright light", "Lamp on, glare on the steel, a handoff still finishes."),
    ("V7", 10, "S4-return.mp4", "Return", "A tool set in the return spot, the arm putting it back in its slot."),
    ("V8", 12, None, "Count and the text",
     "The dashboard count, the count sheet read with any mismatch, the summary text arriving on the phone."),
    ("V9", 15, None, "The build", "The temperature graph from the thermal page, then the arm folding to rest."),
    ("V10", 15, "S3-scissors-handoff.mp4", "How it works",
     "Training montage (recorded demonstrations at 4x, labeled), the sim replay, what the wrist camera sees."),
    ("V11", 8, None, "Scrub", "The arm at rest, then the end card: SCRUB, $250, open source."),
]


def _fonts():
    from PIL import ImageFont

    def f(names, size):
        for n in names:
            for d in ("C:/Windows/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                      "/usr/share/fonts/truetype/dejavu"):
                p = Path(d) / n
                if p.exists():
                    return ImageFont.truetype(str(p), size)
        return ImageFont.load_default()
    return {"brand": f(["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 150),
            "head": f(["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"], 64),
            "body": f(["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"], 38),
            "mono": f(["consola.ttf", "Menlo.ttc", "DejaVuSansMono.ttf"], 30)}


def _wrap(d, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def card(path, label, title, body=None, color=INK, brand=False):
    from PIL import Image, ImageDraw

    fo = _fonts()
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([120, 150, W - 120, 154], fill=INK)  # masthead rule
    d.text((120, 100), label.upper(), font=fo["mono"], fill=color)
    if brand:
        d.text((120, 330), "SCRUB", font=fo["brand"], fill=INK)
        d.text((124, 520), title, font=fo["head"], fill=INK)
    else:
        d.text((120, 300), title, font=fo["head"], fill=INK)
    y = 640 if brand else 420
    for line in _wrap(d, body or "", fo["body"], W - 240):
        d.text((120, y), line, font=fo["body"], fill=MUTE)
        y += 54
    d.rectangle([120, H - 130, W - 120, H - 128], fill=INK)
    d.text((120, H - 110), "SCRUB  ·  DubHacks '26  ·  Anish, Caiden, Brandon, Evan", font=fo["mono"], fill=MUTE)
    img.save(path)
    return path


def draw_cards():
    out = KIT / "cards"
    out.mkdir(parents=True, exist_ok=True)
    card(out / "title.png", "DubHacks '26", "A robot arm that passes instruments when you ask.", brand=True)
    card(out / "end.png", "Built in 24 hours", "Scrub",
         "Anish, Caiden, Brandon, Evan. SO-101 arm, Perceptron Isaac fine-tuned on our demonstrations, voice over a "
         "phone call, every handoff logged. Research and training prototype, not a medical device.")
    for slot, _, _, title, film in BEATS:
        card(out / f"todo-{slot}.png", f"To film: {slot}", title, film, color=AMBER)
    how_cards(out)
    return out


def how_cards(out):
    """Three 'how it works' cards: the handoff pipeline, the safety layer, the training."""
    from PIL import Image, ImageDraw

    fo = _fonts()
    small = fo["mono"]

    def frame(label, title):
        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        d.text((120, 100), label.upper(), font=small, fill=MUTE)
        d.rectangle([120, 150, W - 120, 154], fill=INK)
        d.text((120, 190), title, font=fo["head"], fill=INK)
        d.rectangle([120, H - 130, W - 120, H - 128], fill=INK)
        d.text((120, H - 110), "SCRUB  ·  DubHacks '26", font=small, fill=MUTE)
        return img, d

    # 1. the pipeline, left to right
    img, d = frame("How it works", "From a spoken word to an instrument in your hand")
    steps = [("ASK", "Phone call on speaker", "Photon + ElevenLabs"), ("UNDERSTAND", "One command from the tray's list", "Gemini"),
             ("FIND", "Where the instrument lies", "Perceptron vision"), ("PICK", "Fine-tuned on our demos", "Perceptron Isaac"),
             ("HAND", "Handle first to the open hand", "MediaPipe hand tracking"), ("LOG", "Every handoff timed", "MongoDB Atlas")]
    from PIL import ImageFont
    bold = next((ImageFont.truetype(n, 50) for n in ("C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if Path(n).exists()), fo["head"])
    w, h, gap = 544, 250, 24
    for i, (k, what, how) in enumerate(steps):
        x, y = 120 + (i % 3) * (w + gap), 330 + (i // 3) * (h + gap)
        d.rectangle([x, y, x + w, y + h], outline=INK, width=2)
        d.text((x + 24, y + 22), f"{i + 1:02d}", font=small, fill=MUTE)
        d.text((x + 24, y + 62), k, font=bold, fill=INK)
        d.text((x + 24, y + 134), what, font=_small_body(), fill=INK)
        d.text((x + 24, y + h - 50), how, font=small, fill=MUTE)
    img.save(out / "how-1.png")

    # 2. the safety layer
    img, d = frame("How it works", "The model picks. Our code keeps it safe.")
    rows = [("Sharps", "The scalpel only ever goes to the safe spot, never to a hand."),
            ("Stop", "\"Stop\" freezes the arm at once, without waiting on the language model."),
            ("Grasp check", "The gripper and the camera check every pick; a miss is retried once, then said out loud."),
            ("Hand", "The arm slows near the hand, and holds still if the hand leaves."),
            ("Release", "It lets go when the person pulls, or says \"got it\"."),
            ("Heat", "Motor temperatures are watched; the arm rests between requests.")]
    y = 360
    for k, v in rows:
        d.rectangle([120, y - 14, W - 120, y - 13], fill=(185, 180, 164))
        d.text((120, y), k.upper(), font=small, fill=RED if k in ("Sharps", "Stop") else INK)
        d.text((480, y - 6), v, font=_small_body(), fill=INK)
        y += 90
    img.save(out / "how-2.png")

    # 3. the training
    img, d = frame("How it works", "Taught by demonstration")
    rows = [("Record", "We move a leader arm by hand; the robot copies it while two cameras record at 30 fps."),
            ("Check", "Every episode is checked for frame rate, lighting and a clean grasp before it can be used."),
            ("Fine-tune", "Perceptron's Isaac model is fine-tuned on our demonstrations, one instruction per task."),
            ("Run", "The arm runs the trained model live, a new prediction every half second, inside our safety layer."),
            ("Measure", "Every try is logged. The numbers on our dashboard are real tries, with the range.")]
    y = 360
    for k, v in rows:
        d.rectangle([120, y - 14, W - 120, y - 13], fill=(185, 180, 164))
        d.text((120, y), k.upper(), font=small, fill=INK)
        d.text((480, y - 6), v, font=_small_body(), fill=INK)
        y += 100
    img.save(out / "how-3.png")


def _small_body():
    from PIL import ImageFont

    for n in ("C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(n).exists():
            return ImageFont.truetype(n, 30)
    return ImageFont.load_default()


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _has_audio(src):
    return "Audio:" in subprocess.run([ffmpeg(), "-i", str(src)], capture_output=True, text=True).stderr


def _norm(src, dst, seconds=None, still=False):
    """One part: 1920x1080, 30 fps, H.264, stereo AAC (the clip's own sound, else silence)."""
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x14130f,"
          f"fps={FPS},format=yuv420p")
    cmd = [ffmpeg(), "-loglevel", "error", "-y"]
    cmd += ["-loop", "1", "-t", str(seconds), "-i", str(src)] if still else ["-i", str(src)]
    real_audio = not still and _has_audio(src)
    if not real_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if real_audio else "1:a:0", "-vf", vf, "-c:v", "libx264", "-crf", "20",
            "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
    if seconds:
        cmd += ["-t", str(seconds)]
    if not real_audio:
        cmd += ["-shortest"]
    subprocess.run(cmd + [str(dst)], check=True)
    return dst


def build(out):
    cards = draw_cards()
    tmp = KIT / "parts"
    tmp.mkdir(parents=True, exist_ok=True)
    parts, report = [], []
    parts.append(_norm(cards / "title.png", tmp / "00-title.mp4", 3, still=True))
    for i, (slot, secs, sim, title, _) in enumerate(BEATS, start=1):
        real = KIT / "real" / f"{slot}.mp4"
        if slot == "V10":  # how it works: the three cards, then a sim clip or real footage
            for n in (1, 2, 3):
                parts.append(_norm(cards / f"how-{n}.png", tmp / f"{i:02d}-{slot}-how{n}.mp4", 5, still=True))
        if real.exists():
            parts.append(_norm(real, tmp / f"{i:02d}-{slot}.mp4", secs * 1.5))
            report.append((slot, "REAL", real))
        elif sim and (KIT / "sim" / sim).exists():
            parts.append(_norm(KIT / "sim" / sim, tmp / f"{i:02d}-{slot}.mp4"))
            report.append((slot, "SIM", KIT / "sim" / sim))
        else:
            parts.append(_norm(cards / f"todo-{slot}.png", tmp / f"{i:02d}-{slot}.mp4", 3, still=True))
            report.append((slot, "MISSING", f"card: {title}"))
    parts.append(_norm(cards / "end.png", tmp / "99-end.mp4", 4, still=True))
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
    print(f"wrote {out}")
    for slot, kind, src in report:
        print(f"  {slot:3} {kind:8} {src}")
    print("Drop real takes in data/video/kit/real/<slot>.mp4 and run this again.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", default=str(KIT / "rough-cut.mp4"))
    p.add_argument("--cards", action="store_true", help="only draw the cards")
    a = p.parse_args()
    if a.cards:
        print(draw_cards())
    else:
        build(Path(a.out))


if __name__ == "__main__":
    main()
