"""python -m video --help. All derivatives stay under data/video/."""
from __future__ import annotations

import argparse
import json
import sys

from .common import BASE, DEFAULT_DATASET, Workspace, default_events


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=str(BASE), help="workspace inside data/video/ (before command)")
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo-assets", help="generate labeled synthetic footage/photos/events/joints; never real results")
    demo.add_argument("--seconds", type=float, default=6)
    sub.add_parser("export-ledger", help="write <root>/events.jsonl from the ledger (Atlas via MONGODB_URI plus ledger/buffer.jsonl)")
    c = sub.add_parser("corners", help="detect markerless tray and drag corners to fix")
    c.add_argument("--input", required=True)
    c.add_argument("--camera", required=True)
    c.add_argument("--width-mm", type=float, required=True, help="actually measured left-to-right tray extent")
    c.add_argument("--height-mm", type=float, required=True, help="actually measured top-to-bottom tray extent")
    c.add_argument("--points", help="JSON [[TLx,TLy],[TRx,TRy],[BRx,BRy],[BLx,BLy]]")
    c.add_argument("--headless", action="store_true")
    c.add_argument("--accept-auto", action="store_true", help="explicitly accept unattended calibration (fixtures only recommended)")
    ingest = sub.add_parser("ingest", help="index raw clips/photos, contact sheets and explicit clock sync")
    ingest.add_argument("--sync", help="JSON keyed by asset basename: {start_time: epoch, kind: real|simulation}")
    ingest.add_argument("--kind", choices=["real", "simulation", "reconstructed"])
    ingest.add_argument("--clap-clip")
    ingest.add_argument("--clap-ledger-time", type=float)
    ingest.add_argument("--clap-second", type=float, help="omit for isolated audio-peak detection in first minute")
    top = sub.add_parser("topdown", help="plane warp, static photo plate or exact recorded-joint replay")
    top.add_argument("--mode", choices=["warp", "plate", "reconstruction"], required=True)
    top.add_argument("--input", help="clip/image for warp; dataset directory or six-joint JSON for reconstruction (default ~/scrub-dataset, where arm.record writes)")
    top.add_argument("--camera", default="side")
    top.add_argument("--output", required=True)
    top.add_argument("--no-track", action="store_true", help="locked tripod only")
    top.add_argument("--reference")
    top.add_argument("--photos", default="photos")
    top.add_argument("--empty-scene", action="store_true")
    top.add_argument("--episode", type=int, default=0)
    top.add_argument("--width", type=int, default=960)
    top.add_argument("--height", type=int, default=720)
    top.add_argument("--plate")
    top.add_argument("--plate-alignment")
    top.add_argument("--start-time", type=float, help="explicit epoch sync to the real clip, not inferred")
    cl = sub.add_parser("clean", help="optional logged cleanup; idle changes require reviewed analysis")
    cl.add_argument("--input", required=True)
    cl.add_argument("--output", default="clean/clip.mp4")
    cl.add_argument("--stabilize", action="store_true")
    cl.add_argument("--reference", help="image for exposure/white-balance matching")
    cl.add_argument("--deflicker", action="store_true")
    cl.add_argument("--denoise", action="store_true")
    cl.add_argument("--faces", action="store_true", help="MediaPipe blur-all by default; review privacy manually")
    cl.add_argument("--keep-team", action="store_true", help="click known team faces on first frame; new faces blur")
    idle = cl.add_mutually_exclusive_group()
    idle.add_argument("--idle-speed", type=int, choices=[2,4])
    idle.add_argument("--cut-idle", action="store_true")
    cl.add_argument("--idle-confirmed", action="store_true")
    cl.add_argument("--analyze-only", action="store_true")
    cl.add_argument("--audio", action="store_true", help="afftdn denoise + -16 LUFS target")
    cl.add_argument("--upscale", action="store_true", help="optional GPU path; unavailable models explicitly skipped")
    fi = sub.add_parser("find", help="rank/cut original takes correlated by ledger command_id")
    fi.add_argument("--events", help="ledger JSONL; default <root>/events.jsonl from export-ledger")
    fi.add_argument("--manifest", default="manifest.json")
    fi.add_argument("--cut", action="store_true")
    fi.add_argument("--gemini", action="store_true", help="report optional scorer availability; never uploads by default")
    ov=sub.add_parser('overlay',help='burn ledger-backed request, timing, steps, lighting and count')
    ov.add_argument('--input',required=True)
    ov.add_argument('--events',help='ledger JSONL; default <root>/events.jsonl from export-ledger')
    ov.add_argument('--output',required=True)
    ov.add_argument('--case-id')
    ov.add_argument('--allow-synthetic',action='store_true')
    ca=sub.add_parser('cards',help='render Scrub HTML cards through headless Chromium at 1080p')
    ca.add_argument('--events',help='ledger JSONL; default <root>/events.jsonl from export-ledger. Rates require kind=test rows')
    ca.add_argument('--allow-synthetic',action='store_true')
    re=sub.add_parser('render',help='strict 1080p/30 H.264/AAC EDL assembly; no missing-shot substitutions')
    re.add_argument('--edl',required=True,help='repository YAML path, not workspace-relative')
    re.add_argument('--bindings',required=True,help='workspace JSON mapping slot names to source/in_s/treatment inputs')
    re.add_argument('--output',default='renders/final.mp4')
    re.add_argument('--demo',action='store_true',help='synthetic tests only: permanently labeled, may loop fixture footage')
    pr=sub.add_parser('preview',help='same EDL/timing/honesty gates at 640x360/15 for a fast review')
    pr.add_argument('--edl',required=True)
    pr.add_argument('--bindings',required=True)
    pr.add_argument('--output',default='renders/preview.mp4')
    pr.add_argument('--demo',action='store_true')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    ws = Workspace(args.root)
    try:
        if args.command == "demo-assets":
            from .common import finite
            from .synthetic import demo_assets
            if not 2 <= finite(args.seconds) <= 60:
                raise ValueError("Demo seconds must be between 2 and 60")
            result = demo_assets(ws, args.seconds)
        elif args.command == "export-ledger":
            from .common import export_ledger
            result = export_ledger(ws)
        elif args.command == "corners":
            from .geometry import corners
            result = corners(ws, args.input, args.camera, args.width_mm, args.height_mm,
                json.loads(args.points) if args.points else None, args.headless, args.accept_auto)
        elif args.command == "ingest":
            from .ingest import ingest
            result = ingest(ws, args.sync, args.kind, args.clap_clip, args.clap_ledger_time, args.clap_second)
        elif args.command == "topdown":
            from .topdown import warp, photo_plate
            if args.mode == "warp":
                if not args.input:
                    raise ValueError("warp needs --input")
                result = warp(ws, args.input, args.camera, args.output, not args.no_track)
            elif args.mode == "plate":
                if not args.reference:
                    raise ValueError("plate needs --reference")
                result = photo_plate(ws, args.reference, args.photos, args.camera, args.output, args.empty_scene)
            else:
                from .reconstruction import render_joints
                source = ws.source(args.input) if args.input else DEFAULT_DATASET
                result = render_joints(ws, source, ws.out(args.output), args.width, args.height,
                    args.episode, ws.source(args.plate) if args.plate else None, args.start_time,
                    ws.source(args.plate_alignment) if args.plate_alignment else None)
        elif args.command == "clean":
            from .clean import clean
            result = clean(ws,args.input,args.output,args.stabilize,args.reference,args.deflicker,args.denoise,
                args.faces,args.keep_team,args.idle_speed,args.cut_idle,args.idle_confirmed,args.analyze_only,args.audio,args.upscale)
        elif args.command == "find":
            from .takes import find
            result = find(ws,args.events or default_events(ws),args.manifest,args.cut,args.gemini)
        elif args.command == 'overlay':
            from .overlay import overlay
            result=overlay(ws,args.input,args.events or default_events(ws),args.output,args.case_id,args.allow_synthetic)
        elif args.command == 'cards':
            from .cards import cards
            result=cards(ws,args.events or default_events(ws),args.allow_synthetic)
        elif args.command == 'render':
            from .edit import render
            result=render(ws,args.edl,args.bindings,args.output,args.demo)
        elif args.command == 'preview':
            from .edit import render
            result=render(ws,args.edl,args.bindings,args.output,args.demo,preview=True)
        else:
            raise ValueError("Unknown command")
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, ImportError) as error:
        # No keys are read. Avoid printing external SDK/network exception bodies.
        print(f"video: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
