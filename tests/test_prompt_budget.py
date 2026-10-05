"""Exercise the actual browser guard, including custom board copy handlers."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "board"))
import _theme


@pytest.mark.parametrize("length,character", [(50_000, "a"), (50_001, "a"),
                                              (50_000, "🌌"), (50_001, "🌌")])
def test_click_guard_precedes_custom_handler_and_preserves_full_request(length, character):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the browser contract")
    script = r'''
const assert=require('assert');
let status, downloaded, writes=0;
const handlers=[];
global.document={
  addEventListener:(kind,fn)=>{if(kind==='click')handlers.push(fn)},
  getElementById:()=>status,
  createElement:()=>({dataset:{},setAttribute(){},appendChild(){}})
};
global.URL={createObjectURL:blob=>{downloaded=blob;return 'blob:test'},revokeObjectURL(){}};
''' + _theme.JS + r'''
copyCmd=()=>{writes++}; // Heart and other boards may override the copy UI.
const payload=CHARACTER.repeat(LENGTH);
const button={dataset:{cmd:payload},closest:()=>null,
  insertAdjacentElement:(where,p)=>status=p};
handlers.forEach(handler=>handler({target:{closest:selector=>selector==='button.copy'?button:null}}));
assert.equal(writes,LENGTH<=50000?1:0);
if(LENGTH>50000){
  assert.match(status.textContent,/Not copied/);
  downloaded.text().then(text=>assert.equal(text,payload));
}
'''
    script = script.replace("CHARACTER", json.dumps(character)).replace("LENGTH", str(length))
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_clipboard_rejection_never_flashes_success():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the browser contract")
    script = r'''
const assert=require('assert');
global.document={addEventListener(){},body:{appendChild(){}},
  createElement:()=>({select(){},remove(){}}),execCommand:()=>false};
Object.defineProperty(global,'navigator',{
  value:{clipboard:{writeText:async()=>{throw Error('denied')}}}});
document.getElementById=()=>null;
global.setTimeout=()=>{};
''' + _theme.JS + r'''
const b={dataset:{cmd:'Use the health skill.'},textContent:'Copy',closest:()=>null,
  classList:{add(){throw Error('false success')},remove(){}}};
copyCmd(b).then(()=>assert.equal(b.textContent,'Copy failed'));
'''
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
