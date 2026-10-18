"""The two read-only pages share the same question lifecycle, with no new CSS."""
import subprocess
from pathlib import Path


def test_waiting_question_lifecycle():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "-e", r"""
const assert = require('node:assert/strict');
const waiting = require('./dashboard/clarify.js');
const q = {type:'clarify', question_id:'q1', say:'Which screwdriver: flathead or Phillips?', candidates:[{}, {}], t:100};
assert.equal(waiting([q], 101), q);
assert.equal(waiting([q], 115), null);
assert.equal(waiting([q, {type:'clarify_answer',question_id:'q1',t:102}], 103), null);
assert.equal(waiting([q, {type:'clarify_answer',question_id:'other',t:102}], 103), q);
assert.equal(waiting([q, {type:'stopped',t:102}], 103), null);
assert.equal(waiting([q, {type:'error',step:'error',t:102}], 103), null);
assert.equal(waiting([q, {type:'error',step:'idle',t:102}], 103), q);
assert.equal(waiting([{...q, say:'<script>unsafe</script>'}], 101).say, '<script>unsafe</script>');
assert.deepEqual(globalThis.scrubOutItems({out:['hemostat'],out_instances:[{item:'hemostat',id:'a'},{item:'hemostat',id:'b'}]}), ['hemostat','hemostat']);
assert.deepEqual(globalThis.scrubOutItems({out:['hemostat']}), ['hemostat']);
assert.deepEqual(globalThis.scrubOutItems({out:[],out_instances:[]}), []);
"""], cwd=root, check=True)
    for page in ("dashboard/index.html", "controller/ops.html"):
        text = (root / page).read_text(encoding="utf-8")
        assert 'id="waiting-question"' in text
        assert 'clarify.js' in text
        assert 'scrub.css' in text
