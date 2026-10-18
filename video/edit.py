"""Strict EDL assembly. Real shots never loop, freeze, invent metrics or borrow outcomes."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess
import uuid

import cv2
import imageio_ffmpeg
import yaml

from .common import audible, digest, encode, finite, fit, info, provenance, read_json, run_ffmpeg, save_provenance, speed_at, stamp, text_bar, write_json


class Reader:
    def __init__(self,path,demo=False):
        self.path=Path(path)
        self.details=info(path)
        self.meta=provenance(path)
        self.demo=demo
        self.image=cv2.imread(str(path)) if self.details['media']=='image' else None
        self.capture=None if self.image is not None else cv2.VideoCapture(str(path))
        self.index=-1
        self.last=None

    def get(self,t):
        if self.image is not None:
            return self.image.copy()
        if t<0:
            raise ValueError("Negative EDL source time")
        if t>=self.details['duration_s']-1e-8:
            if not self.demo or not self.meta.get('synthetic'):
                raise ValueError("Source too short: never loop/freeze real action footage")
            t=t%self.details['duration_s']
        target=min(self.details['frames']-1,math.floor(t*self.details['fps']+1e-5))
        if target==self.index:
            return self.last.copy()
        if target!=self.index+1:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES,target)
        ok,image=self.capture.read()
        if not ok:
            raise ValueError("Source decode ended before EDL out point")
        self.index,self.last=target,image
        return image.copy()

    def close(self):
        if self.capture:
            self.capture.release()


def resolve_plan(ws,edl,bindings,demo=False):
    plan=yaml.safe_load(Path(edl).read_text(encoding='utf-8'))
    if not isinstance(plan,dict) or plan.get('version')!=1:
        raise ValueError("EDL requires version: 1")
    if (plan.get('width'),plan.get('height'),plan.get('fps'))!=(1920,1080,30):
        raise ValueError("Delivery EDL must specify 1920x1080 at 30 FPS")
    links=read_json(ws.source(bindings))
    if plan.get('mode')=='continuous_arm':
        if 'ARM_ROLL' not in links:
            raise ValueError("Unedited arm EDL requires ARM_ROLL binding to one complete source")
        roll=links['ARM_ROLL']
        source=ws.source(roll['source'])
        details,meta=info(source),provenance(source)
        if details['media']!='video' or roll.get('in_s',0)!=0 or roll.get('layout') or roll.get('events') or roll.get('speed',1)!=1:
            raise ValueError("Arm roll must be a full continuous video, no trim/speed/composite")
        if meta.get('time_altered') or meta.get('continuous') is False or any('find cut'==op.get('command') for op in meta.get('operations',[])):
            raise ValueError("Edited/time-altered derivative cannot be an unedited arm roll")
        shots=[{'slot':'ARM_ROLL','duration_s':details['duration_s'],'treatment':'clean'}]
        cards=read_json(ws.source('cards/index.json'))['cards']
        for path in cards:
            if Path(path).stem=='end' or Path(path).stem.startswith('end-'):
                name=Path(path).stem
                links[name]={'source':path}
                shots.append({'slot':name,'duration_s':plan.get('end_card_s',8),'treatment':'none'})
    else:
        shots=plan.get('shots',[])
    if not shots:
        raise ValueError("EDL has no shots")
    prepared=[]
    for shot in shots:
        key=shot['slot']
        if key not in links:
            raise ValueError(f"Missing footage binding for {key}; no automatic fake-arm substitution")
        binding=dict(links[key])
        if binding.get('speed',1)!=1:
            raise ValueError("EDL speed changes are not implicit; use reviewed clean idle edits with labels")
        source=ws.source(binding['source'])
        details,meta=info(source),provenance(source)
        if meta['kind']=='unknown':
            raise ValueError("Ingest and declare source provenance before rendering: "+source.name)
        if not demo and plan.get('real_only',True) and meta['kind'] not in {'real','card'}:
            raise ValueError("Real-demo/arm EDL refuses simulated, reconstructed and plate action substitutes")
        if meta.get('synthetic') and not demo:
            raise ValueError("Synthetic fixture cannot be a production export; use --demo for labeled tests")
        duration=finite(shot['duration_s'],'shot duration',True)
        begin=finite(binding.get('in_s',0),'EDL in point')
        if begin<0:
            raise ValueError("EDL in point must not be negative")
        if details['media']=='video' and begin+duration>details['duration_s']+1/60 and not (demo and meta.get('synthetic')):
            raise ValueError(f"{key} needs {duration:g}s of real source; reshoot or edit the EDL, never stretch it")
        caption=shot.get('caption')
        if caption and re.search(r'\d',caption):
            raise ValueError("Typed numeric captions are prohibited; generate metrics from ledger/dataset")
        prepared.append({**shot,'binding':binding,'path':str(source),'source_info':details,'meta':meta,'in_s':begin,'duration_s':duration})
    duration=sum(shot['duration_s'] for shot in prepared)
    if plan.get('duration_s') is not None and abs(duration-float(plan['duration_s']))>1/30:
        raise ValueError("EDL declared duration does not equal shot durations")
    return plan,prepared,duration


def prepare_source(ws,shot,job,ordinal,demo):
    source=Path(shot['path'])
    treatment=shot.get('treatment','none')
    binding=shot['binding']
    if treatment not in {'none','clean','topdown','side-by-side','picture-in-picture'}:
        raise ValueError("Unsupported EDL treatment")
    if treatment=='clean' and info(source)['media']=='video':
        from .clean import clean
        options=binding.get('clean',{})
        allowed={'stabilize','reference','deflicker','denoise','faces','audio_clean'}
        if set(options)-allowed:
            raise ValueError("EDL cleanup only supports appearance/audio filters; no hidden time edits")
        target=f'work/{job}/clean-{ordinal}.mp4'
        clean(ws,source,target,**options)
        source=ws.source(target)
    if treatment=='topdown':
        from .topdown import warp
        target=f'work/{job}/plane-{ordinal}.mp4'
        warp(ws,source,binding.get('camera','side'),target,track=not binding.get('locked_tripod',False))
        source=ws.source(target)
    if binding.get('events'):
        from .overlay import overlay
        target=f'work/{job}/overlay-{ordinal}.mp4'
        overlay(ws,source,binding['events'],target,binding.get('case_id'),demo)
        source=ws.source(target)
    return source


def normalize_delivery(ws,assembled,output,duration,allow_leveling=True):
    """Two-pass measured loudness for audible content; silence stays silence."""
    if not audible(assembled):
        run_ffmpeg(ws,['-i',assembled,'-c','copy','-t',duration,'-movflags','+faststart',output])
        return {'target_lufs':-16,'measured_lufs':None,'note':'Silent track retained; silence has no finite LUFS.'}
    process=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-i',str(assembled),'-vn',
        '-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    match=re.search(r'\{\s*"input_i".*?\}',process.stderr,re.S)
    if process.returncode or not match:
        raise RuntimeError("Cannot measure final program loudness")
    measured=json.loads(match.group())
    parameters=':'.join(f'{key}={measured[value]}' for key,value in
        [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
    run_ffmpeg(ws,['-i',assembled,'-c:v','copy','-af','loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:'+parameters,
        '-c:a','aac','-ar','48000','-ac','2','-t',duration,'-movflags','+faststart',output])
    verification=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-i',str(output),'-vn',
        '-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    match=re.search(r'\{\s*"input_i".*?\}',verification.stderr,re.S)
    if verification.returncode or not match:
        raise RuntimeError("Cannot verify delivered loudness")
    verified=json.loads(match.group())
    integrated=finite(verified['input_i'],'delivered integrated LUFS')
    if abs(integrated+16)>1:
        if not allow_leveling:
            raise ValueError(f"Delivered loudness {integrated:g} LUFS misses the -16 LUFS target after dynamics leveling; review audio")
        # A loud clap beside quiet speech can make the true-peak ceiling prevent
        # simple gain from reaching target. One transparent, bounded dynamics
        # pass is allowed; no speech, room sound or samples are generated.
        leveled=ws.out('work/'+uuid.uuid4().hex+'-audio-leveled.mp4')
        recipe='acompressor=threshold=0.003:ratio=8:attack=0.01:release=50:makeup=1'
        run_ffmpeg(ws,['-i',assembled,'-c:v','copy','-af',recipe,'-c:a','aac','-ar','48000','-ac','2',leveled])
        result=normalize_delivery(ws,leveled,output,duration,allow_leveling=False)
        result['dynamics_leveling']={'filter':recipe,'reason':'True-peak-limited program missed integrated target',
                                     'before_lufs':integrated,'review':'Listen for altered room-noise/speech balance before publication.'}
        return result
    return {'target_lufs':-16,'input_measurement':measured,'measured_lufs':integrated,
            'verification':verified,'method':'two-pass measured loudnorm, delivery remeasured'}


def render(ws,edl,bindings,output,demo=False,preview=False):
    plan,shots,duration=resolve_plan(ws,edl,bindings,demo)
    if ws.out(output) in [Path(shot['path']) for shot in shots]:
        raise ValueError("Render output cannot replace any input")
    width,height,fps=(640,360,15) if preview else (1920,1080,30)
    job=uuid.uuid4().hex
    segments,audit=[],[]
    mixed_secondary=False
    planned_cursor=0.0
    for ordinal,shot in enumerate(shots):
        source=prepare_source(ws,shot,job,ordinal,demo)
        reader=Reader(source,demo)
        secondary=None
        binding=shot['binding']
        layout=binding.get('layout',shot.get('treatment'))
        if layout in {'side-by-side','picture-in-picture'}:
            if not binding.get('secondary'):
                raise ValueError("Composite treatment needs a secondary binding, not invented dashboard content")
            secondary=Reader(ws.source(binding['secondary']),demo)
            if secondary.meta['kind']=='unknown' or (not demo and secondary.meta.get('synthetic')):
                raise ValueError("Secondary source has no admissible provenance")
            if not demo and plan.get('real_only',True) and secondary.meta['kind'] not in {'real','card'}:
                raise ValueError("Real-demo secondary source must also be real, not a reconstruction")
            mixed_secondary=mixed_secondary or secondary.meta['kind'] not in {'real','card'}
            if secondary.details['media']=='video' and not demo:
                primary_epoch=reader.meta.get('start_time')
                secondary_epoch=secondary.meta.get('start_time')
                if primary_epoch is None or secondary_epoch is None or abs(primary_epoch+shot['in_s']-secondary_epoch-binding.get('secondary_in_s',0))>1/30:
                    raise ValueError("Dashboard/action composite must share a verified clock; align in points first")
        count=round((planned_cursor+shot['duration_s'])*fps)-round(planned_cursor*fps)
        planned_cursor+=shot['duration_s']
        if count<1:
            raise ValueError("Shot is shorter than one output frame")
        def images():
            try:
                for n in range(count):
                    t=shot['in_s']+n/fps
                    image=reader.get(t)
                    image=stamp(image,reader.meta,speed_at(reader.meta,t))
                    if secondary:
                        other=secondary.get(binding.get('secondary_in_s',0)+n/fps)
                        other=stamp(other,secondary.meta)
                        if secondary.details['media']=='image':
                            other=text_bar(other,['DASHBOARD STILL - NOT A LIVE STATE'],bottom=True)
                        if layout=='side-by-side':
                            import numpy as np
                            image=np.hstack([fit(image,width//2,height),fit(other,width//2,height)])
                        else:
                            image=fit(image,width,height)
                            inset=fit(other,width//3,height//3)
                            image[-inset.shape[0]:,-inset.shape[1]:]=inset
                    else:
                        image=fit(image,width,height)
                    if shot.get('caption'):
                        image=text_bar(image,[shot['caption']],bottom=True)
                    if demo:
                        image=stamp(image,{'kind':'simulation','synthetic':True})
                    else:
                        # Put the required label outside cropped/scaled panels as well.
                        image=stamp(image,reader.meta,speed_at(reader.meta,t))
                    yield image
            finally:
                reader.close()
                if secondary:
                    secondary.close()
        segment=ws.out(f'work/{job}/segment-{ordinal:03d}.mp4')
        audio=source if reader.details['media']=='video' else None
        source_segments=[{'start':shot['in_s'],'end':shot['in_s']+shot['duration_s'],'speed':1}] if audio and not demo else None
        encoded=encode(ws,segment,images(),fps,audio=audio,segments=source_segments)
        segments.append(segment)
        audit.append({'slot':shot['slot'],'source':shot['path'],'source_sha256':digest(shot['path']),
            'in_s':shot['in_s'],'duration_s':count/fps,'frames':count,'kind':shot['meta']['kind'],
            'treatment':shot.get('treatment'),'output_start_s':sum(a['duration_s'] for a in audit)})
    concat=ws.out(f'work/{job}/concat.txt')
    concat.write_text(''.join("file '"+p.as_posix().replace("'","'\\''")+"'\n" for p in segments),encoding='utf-8')
    assembled=ws.out(f'work/{job}/assembled.mp4')
    run_ffmpeg(ws,['-f','concat','-safe','0','-i',concat,'-c','copy',assembled])
    output=ws.out(output)
    candidate=ws.out(f'work/{job}/delivery-checked.mp4')
    loudness=normalize_delivery(ws,assembled,candidate,sum(a['duration_s'] for a in audit))
    details=info(candidate)
    expected=sum(a['frames'] for a in audit)
    if details['frames']!=expected or abs(details['fps']-fps)>.001:
        raise ValueError("Delivery frame count/rate differs from EDL; do not publish")
    candidate.replace(output)
    report={'edl':str(Path(edl).resolve()),'edl_sha256':digest(edl),'bindings_sha256':digest(ws.source(bindings)),
        'output':str(output),'frames':expected,'fps':fps,'width':width,'height':height,
        'duration_s':expected/fps,'preview':preview,'synthetic':demo,'shots':audit,'loudness':loudness,
        'note':'DEMO FIXTURE / NOT REAL-ARM EVIDENCE' if demo else 'Only bound source footage and source-backed cards. Review before publishing.'}
    write_json(ws.out('renders/'+output.stem+'-report.json'),report)
    kind='simulation' if demo else 'real' if not mixed_secondary and all(s['meta']['kind'] in {'real','card'} for s in shots) else 'mixed'
    save_provenance(output,kind=kind,synthetic=demo,frames=expected,fps=fps,
        operations=[{'command':'preview' if preview else 'render','edl':str(edl),'shots':audit}],
        continuous=plan.get('mode')=='continuous_arm',duration_s=expected/fps)
    return report
