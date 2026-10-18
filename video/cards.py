"""Headless HTML cards. Measured success tables come only from ledger test rows."""
from __future__ import annotations

import base64
from collections import defaultdict
import html
import math
import os
import statistics

from .common import BASE, digest, ledger_rows, save_provenance, write_json
from .style import CSS, ensure_fonts


def trial_table(rows):
    groups=defaultdict(list)
    for row in rows:
        if row.get('_record_kind')!='test':
            continue
        if type(row.get('success')) is not bool:
            raise ValueError("Trial success must be an actual ledger boolean")
        groups[(row.get('setting','unknown'),row.get('item','unknown'),row.get('lighting','unknown'))].append(row)
    result=[]
    for (setting,item,lighting),group in sorted(groups.items()):
        n=len(group)
        k=sum(row['success'] for row in group)
        p=k/n
        z=1.959963984540054
        center=(p+z*z/(2*n))/(1+z*z/n)
        margin=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
        times=[float(row['seconds']) for row in group if row['success'] and row.get('seconds') is not None]
        if any(not math.isfinite(t) or t<0 for t in times):
            raise ValueError("Invalid measured trial timing")
        result.append({'setting':setting,'item':item,'lighting':lighting,'attempts':n,'successes':k,
            'rate':p,'low':max(0,center-margin),'high':min(1,center+margin),
            'median_s':statistics.median(times) if times else None})
    return result


def table_html(table):
    if not table:
        return '<p>No measured trials in the supplied ledger. No success rate claimed.</p>'
    body=[]
    for row in table:
        label=html.escape(row['setting']+' / '+row['item'].replace('_',' '))
        time='Not measured' if row['median_s'] is None else f"{row['median_s']:.1f} s"
        body.append(f"<tr><td>{label}</td><td>{html.escape(row['lighting'])}</td>"
            f"<td>{row['rate']:.0%} &nbsp; {row['successes']}/{row['attempts']} &nbsp; [{row['low']:.0%}–{row['high']:.0%}]</td><td>{time}</td></tr>")
    return '<table><thead><tr><th>Tray / item</th><th>Lighting</th><th>Success / tries / Wilson range</th><th>Median</th></tr></thead><tbody>'+''.join(body)+'</tbody></table>'


def cards(ws,ledger,allow_synthetic=False):
    from playwright.sync_api import sync_playwright
    ledger=ws.source(ledger)
    rows=ledger_rows(ledger)
    synthetic=any(row.get('synthetic') or row.get('fake_arm') for row in rows)
    if synthetic and not allow_synthetic:
        raise ValueError("Synthetic/fake ledger requires --allow-synthetic; numbers are not real-arm evidence")
    table=trial_table(rows)
    folder=ensure_fonts()
    embedded=''
    for family,file in (('Archivo','Archivo.ttf'),('Plex','IBMPlexMono-Regular.ttf')):
        data=base64.b64encode((folder/file).read_bytes()).decode('ascii')
        embedded+=f"@font-face{{font-family:{family};src:url(data:font/ttf;base64,{data}) format('truetype');font-weight:100 900;}}"
    definitions={
        'title':('SCRUB','A robot arm that passes instruments when you ask.'),
        'safe-spot':('Safe spot.','Sharps go to the neutral zone, never hand to hand.'),
        'return':('Return.','From the return spot to the instrument slot.'),
        'lighting':('Bright, normal, dim.','Lighting conditions are tagged in the ledger.'),
        'bench':('Same code. Different tray.','The robotics bench.'),
        'training':('Demonstrations to model.','Picking is learned. The move to the hand is planned.'),
        'count':('What is still out.','The count and the case summary.'),
        'end':('Scrub','Anish, Caiden, Brandon, Evan.'),
    }
    generated=[]
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(BASE/'browser'))
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
            for name,(title,subtitle) in definitions.items():
                # Page multiple success tables rather than clipping rows off screen.
                chunks=[table[i:i+7] for i in range(0,len(table),7)] or [[]]
                if name!='end':
                    chunks=[[]]
                for index,chunk in enumerate(chunks):
                    suffix='' if index==0 else '-'+str(index+1)
                    key=name+suffix
                    disclosure='<div class="disclosure">SIMULATION - SYNTHETIC FIXTURE, NOT REAL-ARM RESULTS</div>' if synthetic else ''
                    content=f'<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p>'
                    if name=='end':
                        content+=table_html(chunk)+'<p class="label">Perceptron Robotics · Photon · Gemini · MongoDB Atlas</p>'
                    document='<!doctype html><meta charset="utf-8"><style>'+embedded+CSS+'</style>'+\
                        f'<body class="{name}">{disclosure}<header><span class="brand">SCRUB</span><span class="label">Robot instrument assistant · prototype</span></header>'+content+\
                        '<footer>DubHacks · Engineering prototype, not clinically validated</footer></body>'
                    html_path=ws.out('cards/'+key+'.html')
                    html_path.write_text(document,encoding='utf-8')
                    page.set_content(document,wait_until='load')
                    page.evaluate('document.fonts.ready')
                    # Refuse a table that is visually clipped by the fixed canvas.
                    if page.locator('table').count() and page.locator('table').bounding_box()['y']+page.locator('table').bounding_box()['height']>900:
                        raise ValueError("Success table exceeds card; reduce rows per card")
                    png=ws.out('cards/'+key+'.png')
                    page.screenshot(path=str(png))
                    save_provenance(png,kind='card',synthetic=synthetic,ledger_source=str(ledger),ledger_sha256=digest(ledger),
                        operations=[{'command':'cards','renderer':'Playwright Chromium','fonts':['Archivo','IBM Plex Mono']}])
                    generated.append(str(png))
        finally:
            browser.close()
    report={'cards':generated,'table':table,'ledger':str(ledger),'ledger_sha256':digest(ledger),
            'synthetic':synthetic,'note':'Only supplied test rows form rate denominators. Events are not success trials.'}
    write_json(ws.out('cards/index.json'),report)
    return report
