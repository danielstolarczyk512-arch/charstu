"""Ostatnie workflow Sogni (status/powod): python -m tests.recent_workflows [n]"""
import json
import re
import sys

from app.providers.sogni import SogniProvider

p = SogniProvider()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
r = p._call("GET", "/v1/creative-agent/workflows", params={"limit": n})
data = r.json().get("data", {})
items = data.get("workflows") or data.get("items") or []
for w in items[:n]:
    print(w.get("workflowId"), w.get("status"), w.get("title"), "| updated", w.get("updatedAt") or w.get("updated"))
    for e in (w.get("events") or [])[-2:]:
        print("   ", re.sub(r"https?://\S+", "<url>", json.dumps({k: e.get(k) for k in ("type", "status", "message")}, ensure_ascii=False))[:300])
print("HTTP", r.status_code, "| klucze:", list(data.keys())[:6])
