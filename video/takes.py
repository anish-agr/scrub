"""Rank ledger-correlated handovers. Image sharpness never establishes success."""
from __future__ import annotations

from collections import defaultdict

import cv2

from .common import digest, encode, events, frame_at, frames, provenance, read_json, save_provenance, stamp, write_json


def successful_trials(rows):
    groups=defaultdict(list)
    for row in rows:
        if row.get('command_id'):
            groups[(row.get('case_id'),row['command_id'])].append(row)
    accepted,excluded=[],[]
    for (_case,command),group in groups.items():
        group.sort(key=lambda row:row['t'])
        request=next((row for row in group if row.get('type')=='command' and row.get('action')=='handover'),None)
        handed=next((row for row in group if row.get('type')=='handed'),None)
        released=next((row for row in group if row.get('type')=='released'),None)
        bad=any(row.get('type') in {'error','missed','stopped'} or (row.get('retries') or 0)>0 for row in group)
        if not request or not handed or not released or bad or handed.get('retries') != 0 or not request['t']<=handed['t']<=released['t']:
            excluded.append({'command_id':command,'reason':'Not a complete ordered handed+released handover with explicit zero retries and no failure'})
            continue
        accepted.append({'command_id':command,'item':request.get('item'),'case_id':request.get('case_id'),
            'start':request['t'],'end':released['t'],'handed':handed['t'],
            'request_to_hand_s':handed.get('request_to_hand_s'),'synthetic':any(row.get('synthetic') or row.get('fake_arm') for row in group)})
    return accepted,excluded


def find(ws, ledger, manifest='manifest.json', cut=False, gemini=False):
    ledger=ws.source(ledger)
    trials,excluded=successful_trials(events(ledger))
    assets=read_json(ws.source(manifest))['assets']
    ranked=[]
    for trial in trials:
        for asset in assets:
            start=asset['start_time']
            if asset['media']!='video' or start is None or not start<=trial['start']<trial['end']<=start+asset['duration_s']:
                continue
            source=ws.source(asset['path'])
            meta=provenance(source)
            if meta.get('time_altered'):
                raise ValueError("Rank original clips, not time-compressed derivatives")
            if trial['synthetic'] and meta['kind']=='real':
                raise ValueError("Synthetic ledger cannot establish a real take outcome")
            begin=max(0,trial['start']-start-.3)
            end=min(asset['duration_s'],trial['end']-start+.5)
            image=frame_at(source,trial['handed']-start)
            sharpness=float(cv2.Laplacian(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var())
            item={**trial,'asset':asset['id'],'source':str(source),'in_s':begin,'out_s':end,
                'framing_score_laplacian':sharpness,'success_evidence':'ledger handed + released, zero retries, no failure',
                'framing_warning':'Sharpness is not proof the handoff is visible; review contact sheet.',
                'ledger_source':str(ledger),'ledger_sha256':digest(ledger),'kind':meta['kind']}
            if cut:
                safe_id=''.join(c for c in trial['command_id'] if c.isalnum() or c in '-_')[:80]
                output=ws.out('takes/'+asset['id']+'-'+safe_id+'.mp4')
                encoded=encode(ws,output,(stamp(image,meta) for _t,image in frames(source,begin,end)),asset['fps'],
                    audio=source,segments=[{'start':begin,'end':end,'speed':1}])
                save_provenance(output,source,**encoded,start_time=start+begin,time_map=None,
                    continuous=False,operations=meta.get('operations',[])+[{'command':'find cut','start':begin,'end':end}],
                    ledger_source=str(ledger),ledger_sha256=digest(ledger))
                item['cut']=str(output)
            ranked.append(item)
    ranked.sort(key=lambda row:row['framing_score_laplacian'],reverse=True)
    report={'takes':ranked,'excluded':excluded,'unmatched_trials':[t['command_id'] for t in trials if not any(r['command_id']==t['command_id'] for r in ranked)],
        'gemini':'not used; local ledger and sharpness only' if not gemini else 'SKIPPED: optional remote framing scorer not configured; no footage uploaded',
        'note':'Editorial selection only, not a measured success-rate denominator. Failures remain in the ledger.'}
    write_json(ws.out('ranked.json'),report)
    return report
