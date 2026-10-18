"""Exercise the station page's real JS with a minimal DOM; no browser, server or hardware."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_question_render_controls_and_clear(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the station page JS unit test")
    page = Path(__file__).with_name("station.html").read_text()
    script = page.split("<script>", 1)[1].split("</script>", 1)[0]
    test = r'''
const vm=require("node:vm"), assert=require("node:assert/strict");
const nodes=new Map();
function node(id){
  if(!nodes.has(id))nodes.set(id,{value:"autopick",hidden:false,disabled:false,textContent:"",dataset:{},style:{},
    classList:{toggle(){}},querySelector:()=>node(id+"-small"),addEventListener(){},blur(){}});
  return nodes.get(id);
}
const ctx=vm.createContext({document:{getElementById:node,querySelectorAll:()=>[],addEventListener(){}},
  localStorage:{getItem:()=>null,setItem(){}},setInterval(){},setTimeout(){},clearTimeout(){},
  fetch:()=>new Promise(()=>{})});
vm.runInContext(SOURCE,ctx);
const q={id:"active-123",say:"Your left or your right?",orientation:"left = image right",timeout_s:15};
ctx.sample={state:"running",run:{driver:"autopick",driver_status:{question:q}},runs:[]};
vm.runInContext("renderRun(sample)",ctx);
assert.equal(node("which-one").hidden,false);
assert.equal(node("which-question").textContent,q.say);
assert.match(node("which-orientation").textContent,/15 seconds/);
assert.equal(node("b-left").disabled,false);
let sent;
ctx.fetch=async (url,options)=>{
  if(url!=="/control")return new Promise(()=>{});
  sent=JSON.parse(options.body);return {json:async()=>({ok:true})};
};
(async()=>{
  await node("b-left").onclick();
  assert.deepEqual(sent,{action:"clarify_answer",question_id:q.id,side:"left"});
  await vm.runInContext('answerChoice("closest","active-123")',ctx);
  assert.deepEqual(sent,{action:"clarify_answer",question_id:q.id,side:"closest"});
  ctx.sample.run.driver_status.question=null;
  vm.runInContext("renderRun(sample)",ctx);
  assert.equal(node("which-one").hidden,true); // timeout clears without waiting for the run to end
  ctx.sample.run.driver_status.question=q;ctx.sample.state="homing";
  vm.runInContext("renderRun(sample)",ctx);
  assert.equal(node("which-one").hidden,true); // stop/abort hides a stale question
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    path = tmp_path / "station-page-test.cjs"
    path.write_text("const SOURCE=" + json.dumps(script) + ";\n" + test)
    result = subprocess.run([node, str(path)], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
