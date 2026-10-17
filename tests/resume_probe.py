"""Sonda B1: co zwraca /resume po safety_review_required (filtr true przy starcie, model Dark Beast Identity Edit).
Drukuje kody HTTP i stany; nie jest testem. python -m tests.resume_probe"""
import json
import time
import uuid

from app import config
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
refs = [O / "job5_0.png", O / "exp_poseref_p1_photo.png"]
media = [{"kind": "image", "url": p._upload_image(r, f"contextImage{i + 1}", str(uuid.uuid4()))} for i, r in enumerate(refs)]
step = {"id": "s1", "toolName": "edit_image", "arguments": {
    "prompt": "The woman in the first image takes the same body pose as the man in the second image. Keep her face, silver braided hair, "
              "green hooded cloak, leather armor and the cliff background from the first image. Only one person is visible.",
    "model": "dark-beast-krea2-identity-edit", "aspectRatio": "16:9", "contextImageIndices": [-1, -2]}}
body = {"input": {"title": "probe-resume", "steps": [step]}, "billing_mode": config.SOGNI_BILLING_MODE, "app_source": "character-studio",
        "safe_content_filter": True, "confirm_cost": True, "media_references": media}
r = p._call("POST", "/v1/creative-agent/workflows", json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
wid = r.json()["data"]["workflow"]["workflowId"]
resumed = 0
for i in range(40):
    g = p._call("GET", f"/v1/creative-agent/workflows/{wid}").json()["data"]["workflow"]
    print(i, g.get("status"), g.get("waitingReason"), flush=True)
    if g.get("status") in ("completed", "failed", "cancelled", "partial_failure"):
        print("koniec; resumes:", resumed); break
    if g.get("waitingReason") == "safety_review_required" and resumed < 3:
        rr = p._call("POST", f"/v1/creative-agent/workflows/{wid}/resume", json={"safe_content_filter": False},
                     headers={"Idempotency-Key": str(uuid.uuid4())})
        resumed += 1
        print("  resume HTTP", rr.status_code, rr.text[:300], flush=True)
    time.sleep(4)
print(json.dumps({k: g.get(k) for k in ("status", "waitingReason")}), p._last_message(g))
