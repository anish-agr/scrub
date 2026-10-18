"""Rough cut of the demo video, in the order of team/VIDEO-SCRIPT.md (the shot list is team/HANDOFF-7AM.md).

Each beat uses the real take if one is in data/video/kit/real/V<n>.mp4 (or .mov), else a labeled sim clip from
data/video/kit/sim/ if that beat has one, else a plain "TO FILM" card. Every spoken line is burned in as a caption.
Narration memos named data/video/kit/real/V11-<Speaker>-<n>.m4a (or .wav) play under their line; without them the
cut is silent with captions. Rerun after each new file; the cut fills in by itself.

  python -m video.roughcut            # writes data/video/kit/rough-cut.mp4, prints what is real, sim or missing
  python -m video.roughcut --cards    # only (re)draw the cards into data/video/kit/cards/

Optional trims: data/video/kit/real/trims.json, e.g. {"V1": [2.5, 31.0]} (start and end second of the take).
Sim footage is labeled SIMULATION in its own picture (video/simdemo.py burns it in). Don't relabel it.
"""
import argparse
import json
import subprocess
from pathlib import Path

KIT = Path("data/video/kit")
REAL, SIM = KIT / "real", KIT / "sim"


def _set_kit(path):
    global KIT, REAL, SIM
    KIT = Path(path)
    REAL, SIM = KIT / "real", KIT / "sim"
W, H, FPS = 1920, 1080, 30
PAPER, INK, MUTE = (18, 18, 17), (238, 236, 230), (160, 158, 150)  # cards: light type on near-black
WPS = 2.6        # spoken words per second, for timing captions when there is no memo
GAP = 0.35       # silence between lines
SPEAKERS = ("Anish", "Caiden", "Evan", "Brandon")

# Each beat: slot, sim stand-ins (first that exists), card title, what to film, label burned on the picture,
# lines [(speaker, text)], options. Speaker None = said in the clip itself (the ask): captioned only on a real take.
# "if_real": the beat's narration plays only over a real take (the lighting line needs logged tries; the model
# line needs a real model pick). "optional": the beat is left out of the cut entirely until its take exists.
BEATS = [
    dict(slot="V1", sim=["sim-hemostat.mp4"], title="Hemostat",
         film="The ask on the phone (\"hemostat\"), the pick, the carry, the handle into the gloved hand, the release "
              "on the pull, the arm going home.",
         lines=[("Anish", "Surgeons work with a scrub tech who hands them each instrument. Hospitals can't hire "
                          "enough of them."),
                ("Anish", "When nobody is there, the surgeon looks away from the patient and searches the tray."),
                (None, "\"Hemostat.\""),
                ("Anish", "This is Scrub. You ask out loud, on the phone. It picks the hemostat with a skill we "
                          "taught it."),
                ("Anish", "It slows down as it nears the handoff point and holds the handle out."),
                ("Anish", "It lets go when you pull, then goes straight home on its own.")]),
    dict(slot="V2", sim=["sim-scissors.mp4"], title="Mayo scissors",
         film="Same as V1 with the Mayo scissors.",
         lines=[(None, "\"Mayo scissors.\""),
                ("Caiden", "It knows three instruments: the scalpel, the hemostat and the Mayo scissors."),
                ("Caiden", "We taught it each pick by moving the arm ourselves.")]),
    dict(slot="V3", sim=["sim-stop.mp4"], title="Stop mid-move",
         film="\"Stop\" mid-move, the arm freezes, the red STOPPED banner, then reset and the pass finishes.",
         lines=[(None, "\"Stop.\""),
                ("Caiden", "Say stop and the arm freezes where it is."),
                ("Caiden", "It stays stopped until someone resets it. Then it finishes the pass.")]),
    dict(slot="V4", sim=[], title="Manual return", label="MANUAL RETURN",
         film="A tool put back in its slot by hand (or the arm jogged).",
         lines=[("Evan", "On the real arm, putting a tool back is manual for now. A person sets it back in its "
                         "slot.")]),
    dict(slot="R", sim=["sim-return.mp4"], title="Simulated return", label="SIMULATED RETURN (electromagnet)",
         film="Rendered by video/simdemo.py.", sim_only=True,
         lines=[("Evan", "In simulation we modeled the return with an electromagnet that picks the tool up and "
                         "puts it back.")]),
    dict(slot="V5", sim=[], title="Lighting", if_real=True,
         film="Lamp on, glare on the steel, a handoff that still finishes. Log the bright, normal and dim tries.",
         lines=[("Evan", "Operating lights are bright and steel throws glare. We ran handoffs in bright, normal "
                         "and dim light.")]),
    dict(slot="V6", sim=[], title="Thermal",
         film="Screen recording of the temperature graph during a hold, then the arm folding to rest, torque off.",
         lines=[("Brandon", "These motors heat up when they hold a pose."),
                ("Brandon", "Scrub watches every motor's temperature, and between requests it folds to rest with "
                            "the torque off.")]),
    dict(slot="V7", sim=[], title="Count and count sheet",
         film="Screen recording: the dashboard count, then the count-sheet OCR read (Perceptron, Gemini fallback) "
              "with the latency shown.",
         lines=[("Brandon", "The dashboard keeps the count of what's out."),
                ("Brandon", "It reads the paper count sheet with Perceptron's OCR, with Gemini as a fallback, and "
                            "shows any mismatch.")]),
    dict(slot="V8", sim=[], title="Tray check",
         film="Screen recording: one overhead frame of the three instruments through Perceptron detect, with the "
              "result and latency.",
         lines=[("Brandon", "Perceptron's vision checks the tray from one overhead frame and finds all three "
                            "instruments.")]),
    dict(slot="V9", sim=[], title="Model picks", optional=True, if_real=True,
         film="Only if a Perceptron model is deployed: an unedited roll of real model picks, then the success table.",
         lines=[("Caiden", "These picks run on a model trained on our demonstrations. Every try is in the table.")]),
    dict(slot="V10", sim=["simdemo-final.mp4", "simdemo.mp4", "../../out/sim-demo.mp4"], title="How it works",
         film="Rendered by video/simdemo.py.", how=True,
         lines=[("Caiden", "How it works. Gemini turns what you said into one instrument from the tray."),
                ("Caiden", "Perceptron's vision finds it, and the arm runs the skill we taught it."),
                ("Caiden", "Our code keeps it in bounds: speed and joint limits, a grasp check before it carries, "
                           "and release only on a pull."),
                ("Anish", "Here is the same routine in simulation.")]),
    dict(slot="END", sim=[], title="Close", end=True,
         lines=[("Anish", "Scrub never touches the patient. It's a research prototype, not a medical device."),
                ("Anish", "A clinic version would run under a sterile drape on a medical-grade arm, like today's "
                          "surgical robots."),
                ("Anish", "It helps scrub techs. It doesn't replace them. We're Anish, Caiden, Evan and Brandon. "
                          "This is Scrub.")]),
]


# ---------------------------------------------------------------- fonts and cards

def _font(size, bold=False):
    from PIL import ImageFont
    names = (["Arial Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["Arial.ttf", "arial.ttf", "DejaVuSans.ttf"])
    for n in names:
        for d in ("/System/Library/Fonts/Supplemental", "/Library/Fonts", "C:/Windows/Fonts",
                  "/usr/share/fonts/truetype/dejavu"):
            if (Path(d) / n).exists():
                return ImageFont.truetype(str(Path(d) / n), size)
    return ImageFont.load_default()


def _wrap(d, text, font, width):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def _page(title, body=(), kicker=None, big=False):
    """A plain card: light type on near-black, left aligned. No boxes, no rules, no decoration."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    x, y = 160, 300 if big else 200
    if kicker:
        d.text((x, y - 70), kicker, font=_font(34), fill=MUTE)
    ft = _font(150 if big else 72, bold=True)
    d.text((x, y), title, font=ft, fill=INK)
    y += 200 if big else 130
    fb = _font(44)
    for para in body:
        for line in _wrap(d, para, fb, W - 2 * x):
            d.text((x, y), line, font=fb, fill=INK if big else MUTE)
            y += 62
        y += 26
    return img


def draw_cards():
    out = KIT / "cards"
    out.mkdir(parents=True, exist_ok=True)
    _page("Scrub", ["A robot arm that passes surgical instruments when you ask."], big=True).save(out / "title.png")
    _page("Scrub", ["Anish, Caiden, Evan, Brandon. DubHacks 2026.",
                    "Research prototype. Not a medical device. Open source."], big=True).save(out / "end.png")
    for b in BEATS:
        if b.get("film"):
            _page(b["title"], [b["film"]], kicker=f"To film: {b['slot']}").save(out / f"todo-{b['slot']}.png")
    _page("How it works", [
        "1. You ask for an instrument out loud, on the phone.",
        "2. Gemini turns what you said into one instrument from the tray.",
        "3. Perceptron's vision finds it on the tray.",
        "4. The arm runs a skill we taught it, then slows as it nears the handoff point.",
        "5. It lets go when you pull and goes home on its own.",
        "6. Every try is logged."]).save(out / "how-1.png")
    _page("What keeps it in bounds", [
        "Stop freezes the arm until someone resets it.",
        "Speed and joint limits on every move.",
        "A grasp check before it carries anything.",
        "Release only on a pull.",
        "Motor temperatures watched; the arm rests with the torque off between requests."]).save(out / "how-2.png")
    return out


def caption_png(text, path):
    """Plain white caption, bottom center, thin dark outline, transparent everywhere else."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font(46)
    rows = _wrap(d, text, f, 1500)
    y = H - 90 - 60 * len(rows)
    for r in rows:
        w = d.textlength(r, font=f)
        d.text(((W - w) / 2, y), r, font=f, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 230))
        y += 60
    img.save(path)
    return path


def label_png(text, path):
    """Small plain label, top left, same style as the captions."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((60, 50), text, font=_font(36), fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 230))
    img.save(path)
    return path


# ---------------------------------------------------------------- media helpers

def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe(src):
    """(duration seconds, has audio) from ffmpeg's banner."""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(src)], capture_output=True, text=True).stderr
    dur = 0.0
    for line in err.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            hh, mm, ss = line.split(",")[0].split()[1].split(":")
            dur = int(hh) * 3600 + int(mm) * 60 + float(ss)
    return dur, "Audio:" in err


def _real(slot):
    for ext in (".mp4", ".mov", ".MOV", ".MP4"):
        if (REAL / f"{slot}{ext}").exists():
            return REAL / f"{slot}{ext}"
    return None


def _memos():
    """{(speaker, n): path} for narration memos V11-<Speaker>-<n>.m4a/.wav."""
    found = {}
    if REAL.exists():
        for p in REAL.iterdir():
            parts = p.stem.split("-")
            if (len(parts) == 3 and parts[0] == "V11" and p.suffix.lower() in (".m4a", ".wav", ".mp3")
                    and parts[1].capitalize() in SPEAKERS and parts[2].isdigit()):
                found[(parts[1].capitalize(), int(parts[2]))] = p
    return found


def numbered_lines():
    """Every narrated line with its memo number: [(beat slot, speaker, n, text)]. n counts per speaker, in order."""
    count, out = {}, []
    for b in BEATS:
        for spk, text in b["lines"]:
            if spk:
                count[spk] = count.get(spk, 0) + 1
                out.append((b["slot"], spk, count[spk], text))
    return out


# ---------------------------------------------------------------- one beat

def render_part(dst, src, seconds, captions, audio_lines, label=None, still=False, start=0.0, clip_audio=False):
    """One 1920x1080 30 fps part: the picture (held on its last frame if short), captions on their timings, the
    clip's own sound (lowered under narration) plus narration memos. captions: [(png, t0, t1)];
    audio_lines: [(path, t0)]."""
    cmd = [ffmpeg(), "-loglevel", "error", "-y"]
    if still:
        cmd += ["-loop", "1", "-t", f"{seconds:.3f}", "-i", str(src)]
    else:
        cmd += ["-ss", f"{start:.3f}", "-i", str(src)]
    overlays = [p for p, _, _ in captions] + ([label] if label else [])
    for p in overlays:
        cmd += ["-i", str(p)]
    for p, _ in audio_lines:
        cmd += ["-i", str(p)]
    cmd += ["-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    n_ov, n_au = len(overlays), len(audio_lines)
    silence = 1 + n_ov + n_au
    fc = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x101010,"
          f"fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration={seconds:.3f},trim=duration={seconds:.3f},"
          f"setpts=PTS-STARTPTS[v0]"]
    cur = "v0"
    for i, (_, t0, t1) in enumerate(captions):
        fc.append(f"[{cur}][{i + 1}:v]overlay=0:0:enable='between(t,{t0:.2f},{t1:.2f})'[c{i}]")
        cur = f"c{i}"
    if label:
        fc.append(f"[{cur}][{n_ov}:v]overlay=0:0[lab]")
        cur = "lab"
    fc.append(f"[{cur}]format=yuv420p[vout]")
    mix = [f"[{silence}:a]"]
    if clip_audio:
        vol = 0.5 if audio_lines else 1.0
        fc.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol}[ca]")
        mix.append("[ca]")
    for j, (_, t0) in enumerate(audio_lines):
        ms = int(t0 * 1000)
        fc.append(f"[{1 + n_ov + j}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[n{j}]")
        mix.append(f"[n{j}]")
    fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0[aout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]", "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(dst)]
    subprocess.run(cmd, check=True)
    return dst


def plan_lines(lines, memos, numbers, real, start=0.4):
    """Timings for a beat's lines: [(speaker, text, t0, t1, memo or None)], and the end time."""
    t, out = start, []
    for spk, text in lines:
        if spk is None and not real:
            continue  # the ask is only heard on a real take
        memo = memos.get(numbers.get((spk, text))) if spk else None
        dur = _probe(memo)[0] if memo else max(1.4, len(text.split()) / WPS)
        out.append((spk, text, t, t + dur, memo))
        t += dur + GAP
    return out, t


# ---------------------------------------------------------------- the cut

def build(out):
    cards = draw_cards()
    tmp = KIT / "parts"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*"):
        old.unlink()
    memos = _memos()
    numbers = {(spk, text): (spk, n) for _, spk, n, text in numbered_lines()}
    trims = {}
    if (REAL / "trims.json").exists():
        trims = json.loads((REAL / "trims.json").read_text())
    parts, report, any_audio, cap_i, report_len = [], [], bool(memos), 0, {}

    def caps(timed, prefix):
        nonlocal cap_i
        res = []
        for spk, text, t0, t1, _ in timed:
            cap_i += 1
            res.append((caption_png(text, tmp / f"cap-{cap_i:03d}.png"), t0, t1))
        return res

    parts.append(render_part(tmp / "000-title.mp4", cards / "title.png", 3.0, [], [], still=True))
    for i, b in enumerate(BEATS, start=1):
        slot, label = b["slot"], None
        real = None if b.get("sim_only") or b.get("end") else _real(slot)
        sim = next((SIM / s for s in b["sim"] if (SIM / s).exists()), None)
        if b.get("optional") and not real:
            report.append((slot, "MISSING", "optional, left out of the cut"))
            continue
        if b.get("how"):  # the two plain cards come first, narration runs across cards and clip
            src, kind, still = cards / "how-1.png", None, True
        elif b.get("end"):
            src, kind, still = cards / "end.png", "CARD", True
        elif real:
            src, kind, still = real, "REAL", False
        elif sim:
            src, kind, still = sim, "SIM", False
        else:
            src, kind, still = cards / f"todo-{slot}.png", "MISSING", True
        speak = b["lines"] if (real or not b.get("if_real")) else []
        timed, need = plan_lines(speak, memos, numbers, bool(real))
        audio = [(m, t0) for _, _, t0, _, m in timed if m]
        if b.get("label") and kind in ("REAL", "SIM"):
            label = label_png(b["label"], tmp / f"label-{slot}.png")

        if b.get("how"):
            # how-1 under the first two lines, how-2 under the third, then the sim clip under the rest.
            cut1 = timed[1][3] + GAP if len(timed) > 1 else 5.0
            cut2 = timed[2][3] + GAP if len(timed) > 2 else cut1 + 5.0
            segs = [(cards / "how-1.png", 0.0, cut1, True), (cards / "how-2.png", cut1, cut2, True)]
            if sim:
                simlen = _probe(sim)[0]
                segs.append((sim, cut2, max(need, cut2 + min(simlen, 8.0)), False))
                report.append((slot, "SIM", sim))
            else:
                segs.append((cards / f"todo-{slot}.png", cut2, max(need, cut2 + 3.0), True))
                report.append((slot, "MISSING", "sim render (cards shown)"))
            for k, (s, a, z, st) in enumerate(segs):
                sub = [(spk, tx, max(t0, a) - a, min(t1, z) - a, m) for spk, tx, t0, t1, m in timed
                       if t0 < z and t1 > a]
                sub_audio = [(m, t0 - a) for _, _, t0, _, m in timed if m and a <= t0 < z]
                parts.append(render_part(tmp / f"{i:03d}-{slot}-{k}.mp4", s, z - a, caps(sub, slot), sub_audio,
                                         still=st))
            report_len[slot] = segs[-1][2]
            continue

        start, length = 0.0, None
        if kind in ("REAL", "SIM"):
            length, has_audio = _probe(src)
            if kind == "REAL" and slot in trims:
                start, end = trims[slot]
                length = end - start
            seconds = max(need + 0.6, min(length, need + 2.0))  # trims.json picks the window
            any_audio = any_audio or (kind == "REAL" and has_audio)
        else:
            has_audio = False
            seconds = max(need + 0.6, 3.0)
        parts.append(render_part(tmp / f"{i:03d}-{slot}.mp4", src, seconds, caps(timed, slot), audio, label=label,
                                 still=still, start=start, clip_audio=(kind == "REAL" and has_audio)))
        if kind != "CARD":
            report.append((slot, kind, (src if kind != "MISSING" else f"card: {b['title']}")))
        report_len[slot] = seconds

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    joined = tmp / "joined.mp4"
    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(joined)], check=True)
    if any_audio:  # bring the whole cut to about -16 LUFS
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(joined), "-c:v", "copy",
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-movflags", "+faststart", str(out)], check=True)
    else:
        joined.replace(out)
    total = _probe(out)[0]
    print(f"wrote {out}  ({int(total // 60)}:{total % 60:04.1f}{', over 3:00!' if total >= 180 else ''})")
    for slot, kind, src in report:
        secs = f"{report_len[slot]:5.1f}s" if slot in report_len else "      "
        print(f"  {slot:4} {kind:8} {secs}  {src}")
    have = sorted(f"{s}-{n}" for s, n in memos)
    print(f"  narration memos: {', '.join(have) if have else 'none (silent, captions only)'}")
    print("Drop real takes in data/video/kit/real/V<n>.mp4 and run this again.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--kit", default=str(KIT), help="kit folder (real/, sim/), for testing")
    p.add_argument("--out", default=None, help="default: <kit>/rough-cut.mp4")
    p.add_argument("--cards", action="store_true", help="only draw the cards")
    p.add_argument("--lines", action="store_true", help="print every narrated line with its memo file name")
    a = p.parse_args()
    _set_kit(a.kit)
    if a.lines:
        for slot, spk, n, text in numbered_lines():
            print(f"{slot:4} V11-{spk}-{n}.m4a  {text}")
    elif a.cards:
        print(draw_cards())
    else:
        build(Path(a.out or KIT / "rough-cut.mp4"))


if __name__ == "__main__":
    main()
