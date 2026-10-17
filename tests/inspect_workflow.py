"""Podglad zdarzen workflow Sogni dla nieudanych zadan filmu: python -m tests.inspect_workflow <film_id> [role]"""
import json
import re
import sys

from app import db
from app.providers.sogni import SogniProvider

fid = int(sys.argv[1])
role = sys.argv[2] if len(sys.argv) > 2 else "clip"
p = SogniProvider()
rows = db.rows("SELECT j.id, j.status, j.error, j.workflow_id, j.params, fs.title FROM jobs j JOIN film_shots fs ON fs.id=j.film_shot_id "
               "WHERE fs.film_id=? AND j.role=? AND j.status IN ('failed','retried') ORDER BY j.id", (fid, role))
for j in rows[:3]:
    print(f"\n== job {j['id']} [{j['title']}] {j['status']} workflow {j['workflow_id']}\n   {j['error'][:160]}")
    pr = json.loads(j["params"])
    print("   model/params:", {k: pr.get(k) for k in ("duration", "source_artifact_id", "end_artifact_id")}, "| prompt:", pr.get("prompt", "")[:160])
    if j["workflow_id"]:
        r = p._call("GET", f"/v1/creative-agent/workflows/{j['workflow_id']}")
        wf = r.json().get("data", {}).get("workflow", {})
        print("   status:", wf.get("status"), "| waitingReason:", wf.get("waitingReason"), "| awaitingCostApproval:", wf.get("awaitingCostApproval"))
        for k in ("waiting", "waitingFor", "permission", "permissions", "requiredPermission", "details", "error", "message"):
            if wf.get(k):
                print(f"   {k}:", json.dumps(wf[k], ensure_ascii=False)[:500])
        ev = wf.get("events", [])[-4:]
        for e in ev:
            s = re.sub(r"https?://\S+", "<url>", json.dumps(e, ensure_ascii=False))
            print("   event:", s[:700])
