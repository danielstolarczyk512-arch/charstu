"""Sonda billing_mode (dodatek do briefu): zadanie na modelu POZA planem (wan3-uncensored, 5 s) wychodzi z billing_mode='tokens'
i nie zjada planu. Drukuje wycene, odpowiedz Sogni i roznice licznika planu (renderSpark). Nie jest testem.
Argument rozdzielczosci (480p) NIE jest ustawiany: nazwa argumentu nie jest potwierdzona, a Sogni ignoruje nieznane.
python -m tests.billing_probe"""
import json
import time
import uuid

from app import config, models
from app.providers.sogni import SogniProvider

p = SogniProvider()


def usage():
    return p._call("GET", "/v1/subscriptions/usage").json()["data"]["usage"]["value"]["daily"]["renderSpark"]


def balance():
    return p._call("GET", "/v1/account/balance").json()["data"]


MODEL = "wan3.0-spicy-video"
bill = models.billing_for(MODEL, config.SOGNI_BILLING_MODE)
print("billing_mode dla", MODEL, "=", bill)
u0, b0 = usage(), balance()
print("przed: plan renderSpark", round(u0, 2), "saldo", b0)
step = {"id": "s1", "toolName": "generate_video", "arguments": {
    "prompt": "A calm slow shot of waves on a quiet beach at dusk.", "videoModel": MODEL, "duration": 5}}
body = {"input": {"title": "probe-billing", "steps": [step]}, "billing_mode": bill, "app_source": "character-studio",
        "safe_content_filter": False, "max_estimated_capacity_units": config.SOGNI_MAX_CAPACITY_UNITS}
est = p._call("POST", "/v1/creative-agent/workflows", json={**body, "confirm_cost": False},
              headers={"Idempotency-Key": str(uuid.uuid4())})
print("wycena HTTP", est.status_code, est.text[:700])
r = p._call("POST", "/v1/creative-agent/workflows", json={**body, "confirm_cost": True},
            headers={"Idempotency-Key": str(uuid.uuid4())})
print("start HTTP", r.status_code, r.text[:500])
if r.status_code in (200, 201, 202):
    wid = r.json()["data"]["workflow"]["workflowId"]
    for i in range(30):
        g = p._call("GET", f"/v1/creative-agent/workflows/{wid}").json()["data"]["workflow"]
        print(i, g.get("status"), g.get("waitingReason"), p._last_message(g)[:200], flush=True)
        if g.get("status") in ("completed", "failed", "cancelled", "partial_failure") or g.get("waitingReason"):
            break
        time.sleep(6)
    print("powod:", p._why(g)[:500])
u1, b1 = usage(), balance()
print("po: plan renderSpark", round(u1, 2), "(roznica", round(u1 - u0, 2), ") saldo", b1)
