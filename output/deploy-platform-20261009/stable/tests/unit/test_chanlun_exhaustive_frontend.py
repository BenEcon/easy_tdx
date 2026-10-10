"""Cross-runtime acceptance of every actual engine leaf, not hand-made UI data."""

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from easy_tdx.chanlun.exhaustive_recursion import GRAMMAR, exhaustive_leaf
from tests.unit.test_chanlun_released_recursion import release_fixture


@pytest.mark.skipif(shutil.which("node") is None, reason="Node needed for frontend contract")
def test_all_engine_leaves_pass_browser_graph_guard_and_bad_batches_fail_closed():
    data = release_fixture()
    path = []
    snapshots = []
    while path is not None:
        leaf = exhaustive_leaf(*data, path)
        snapshots.append(leaf["snapshot"])
        path = leaf["next_path"]
    root = Path(__file__).parents[2]
    script = """
import ts from 'typescript'; import fs from 'node:fs'; import vm from 'node:vm';
import assert from 'node:assert/strict';
const options={compilerOptions:{module:ts.ModuleKind.CommonJS}};
const guard = ts.transpileModule(
 fs.readFileSync('web-ui/src/released-evidence.ts','utf8'), options).outputText;
const guardExports={}; vm.runInNewContext(guard, {exports:guardExports, require});
const code = ts.transpileModule(
 fs.readFileSync('web-ui/src/exhaustive-research.ts','utf8'), options).outputText;
const out={}; vm.runInNewContext(code, {exports:out, require:()=>guardExports});
const {snapshots,total,scope,audit}=JSON.parse(fs.readFileSync(0,'utf8'));
for (const [i,snapshot] of snapshots.entries()) {
 const p={scope,fingerprint:'test',complete:false,next_cursor:'signed',emitted:i+1,
 results:[{id:String(i),ordinal:i+1,solution_token:'signed',snapshot}],eligible_for_trading:false,
 theory_equivalence_claim:false,historical_data_vintage:false,coverage:'all_disjoint_subsets_on_fixed_base_including_unresolved'};
 assert.ok(out.validSearchPage(p,total,i),'leaf '+i);
 for (const mutate of [p=>p.complete=true,p=>p.emitted++,p=>p.results[0].ordinal++,
   p=>p.next_cursor=null,p=>p.fingerprint='other',p=>p.theory_equivalence_claim=true,
   p=>p.results[0].snapshot.eligible_for_trading=true]) {
   const bad=structuredClone(p); mutate(bad);
   assert.equal(out.validSearchPage(bad,total,i,'test'),false);
 }
}
assert.ok(out.validAudit(audit,total,0,'test'));
for (const mutate of [a=>a.offset++, a=>a.total_attempts++, a=>a.next_offset=null,
 a=>a.input.chain_boundaries=null,a=>a.attempts[0].known_index=total,
 a=>a.attempts[0].outcome='not_evaluated',a=>a.summary.x=-1]) {
 const bad=structuredClone(audit); mutate(bad);
 assert.equal(out.validAudit(bad,total,0,'test'),false);
}
"""
    # createRequire is needed only for loading installed TypeScript from web-ui.
    script = (
        "import {createRequire} from 'node:module'; "
        "const require=createRequire(process.cwd()+'/web-ui/package.json');\n"
        + script.replace("import ts from 'typescript';", "const ts=require('typescript');")
    )
    audit = exhaustive_leaf(*data, trace=True)["audit"]
    rows = audit.pop("attempts")
    audit_response = {
        "scope": "actual_candidate_gate_trace_v1",
        "fingerprint": "test",
        "interpretation": "solution",
        "total_attempts": len(rows),
        "offset": 0,
        "next_offset": 50,
        "attempts": rows[:50],
        "summary": dict(Counter(r["reason"] or "candidate_formed" for r in rows)),
        "input": audit,
        "eligible_for_trading": False,
        "as_of_index": len(data[1]) - 1,
    }
    subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=root,
        input=json.dumps(
            {
                "snapshots": snapshots,
                "total": len(data[1]),
                "scope": GRAMMAR,
                "audit": audit_response,
            }
        ),
        text=True,
        check=True,
        capture_output=True,
    )
