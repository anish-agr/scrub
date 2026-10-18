"""The browser adapter preserves every tray while editing the five-item bench."""
import subprocess
from pathlib import Path


def test_layout_round_trip_preserves_other_trays():
    subprocess.run(["node", "-e", r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const ctx = {window:{}, location:{pathname:'/web/viewer.html',search:'',protocol:'http:',origin:'http://localhost:8302'},URLSearchParams};
vm.runInNewContext(fs.readFileSync('sim/web/common.js','utf8'), ctx);
const S = ctx.window.SCRUB, raw = JSON.parse(fs.readFileSync('sim/layout.json','utf8'));
raw.setting = 'bench';
const layout = S.fromSim(raw), result = S.toSim(layout);
assert.equal(layout.slots.length, 5);
assert.deepEqual(JSON.parse(JSON.stringify(result.setting_items.bench)), raw.setting_items.bench);
assert.deepEqual(JSON.parse(JSON.stringify(result.slots)), raw.slots);
assert.deepEqual(JSON.parse(JSON.stringify(result.setting_slots.bench)), raw.setting_slots.bench);
assert.deepEqual(JSON.parse(JSON.stringify(result.setting_items.surgical)), raw.setting_items.surgical);
assert.equal(S.settingJSON(layout).items.filter(i=>i.group==='screwdriver').length, 2);
"""], cwd=Path(__file__).resolve().parents[1], check=True)
