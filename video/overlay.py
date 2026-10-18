"""Every displayed measurement is selected from time-correlated ledger events."""
from __future__ import annotations

import bisect

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .common import INK, PAPER, digest, encode, epoch_at, events, finite, font, frames, info, provenance, save_provenance, stamp, write_json
from .style import ensure_fonts

STEPS=['FIND','PICK','CHECK','HAND','WAIT','RELEASE','HOME']
STEP_MAP={'finding':0,'picking':1,'checking':2,'moving_to_hand':3,'waiting_for_pull':4,'releasing':5,'homing':6}


def display_state(rows, now):
    before=[row for row in rows if row['t']<=now]
    if not before:
        return {'caption':None,'item':None,'lighting':None,'step':None,'out':None,'seconds':None,'event_t':None}
    latest=before[-1]
    command=next((row for row in reversed(before) if row.get('type')=='command'),None)
    correlation=command.get('command_id') if command else None
    metrics=[row for row in before if row.get('command_id')==correlation and row.get('request_to_hand_s') is not None]
    count=next((row.get('out') for row in reversed(before) if isinstance(row.get('out'),list)),None)
    seconds=finite(metrics[-1]['request_to_hand_s']) if metrics else None
    if seconds is not None and seconds<0:
        raise ValueError("Negative request-to-hand time in ledger")
    return {'caption':command.get('heard') if command else None,'item':latest.get('item') or (command or {}).get('item'),
        'lighting':latest.get('lighting'),'step':latest.get('step'),'out':count,'seconds':seconds,'event_t':latest['t']}


def decorate(frame, state):
    image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
    draw=ImageDraw.Draw(image)
    w,h=image.size
    size=max(12,round(w/45))
    mono=font(size,True)
    label=font(size+2)
    # All factual fields originate in display_state; absent values are omitted.
    lines=[]
    if state['caption']:
        lines.append(str(state['caption']))
    if state['item']:
        line=state['item'].replace('_',' ').upper()
        if state['seconds'] is not None:
            line+=f" | request to hand {state['seconds']:.1f} s"
        lines.append(line)
    status=[]
    if state['lighting']:
        status.append(str(state['lighting']).upper())
    if state['out'] is not None:
        status.append(f"OUT {len(state['out'])}: "+', '.join(str(i).replace('_',' ') for i in state['out']))
    if status:
        lines.append(' | '.join(status))
    row_h=size+10
    panel_height=row_h*(len(lines)+1)+16
    y=max(round(h*.55),h-panel_height)
    draw.rectangle((0,y,w,h),fill=INK)
    for n,line in enumerate(lines):
        actual=mono if n else label
        while draw.textlength(line,font=actual)>w-28 and actual.size>10:
            actual=font(actual.size-1,True)
        draw.text((14,y+8+n*row_h),line,font=actual,fill=PAPER)
    active=STEP_MAP.get(state['step'])
    strip_y=h-row_h
    box=w/len(STEPS)
    for i,step in enumerate(STEPS):
        x=round(i*box)
        draw.rectangle((x,strip_y,round((i+1)*box)-1,h),fill=PAPER if i==active else INK,outline=PAPER,width=1)
        draw.text((x+5,strip_y+3),step,font=font(max(10,size-2),True),fill=INK if i==active else PAPER)
    if state['step'] in {'stopped','error'}:
        draw.rectangle((0,y-30,w,y),fill=(200,32,26))
        draw.text((14,y-28),'STOPPED' if state['step']=='stopped' else 'ERROR',font=mono,fill=PAPER)
    return cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)


def overlay(ws,source,ledger,output,case_id=None,allow_synthetic=False):
    ensure_fonts()
    source,ledger,output=ws.source(source),ws.source(ledger),ws.out(output)
    if source==output:
        raise ValueError("Never overwrite source footage")
    meta,details=provenance(source),info(source)
    rows=events(ledger)
    if case_id:
        rows=[row for row in rows if row.get('case_id')==case_id]
    elif len({row.get('case_id') for row in rows})>1:
        raise ValueError("Select --case-id for a multi-case ledger")
    if not rows:
        raise ValueError("No events for overlay")
    synthetic=any(row.get('synthetic') or row.get('fake_arm') for row in rows)
    if synthetic and (not allow_synthetic or meta['kind']=='real'):
        raise ValueError("Synthetic/fake ledger requires --allow-synthetic and non-real footage")
    if meta.get('synthetic') and not allow_synthetic:
        raise ValueError("Synthetic clip requires --allow-synthetic")
    audit=[]
    def images():
        previous=None
        for t,image in frames(source):
            now=epoch_at(meta,t)
            state=display_state(rows,now)
            if state!=previous:
                audit.append({'output_s':t,'source_epoch':now,**state})
                previous=state
            speed=next((segment['speed'] for segment in meta.get('time_map',[]) if segment['output_start']<=t<segment['output_end']),1)
            yield stamp(decorate(image,state),meta,speed)
    encoded=encode(ws,output,images(),details['fps'],audio=source)
    write_json(ws.out('overlays/'+output.stem+'-sources.json'),{'ledger':str(ledger),'sha256':digest(ledger),'changes':audit})
    return save_provenance(output,source,**encoded,ledger_source=str(ledger),ledger_sha256=digest(ledger),
        operations=meta.get('operations',[])+[{'command':'overlay','case_id':case_id,'measurements':'time-correlated ledger only'}])
