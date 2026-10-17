"""Odzyskiwanie filmu: resetuje klipy ujec z bledem i wznawia produkcje. STUDIO_URL=... python -m tests.recover_film <film_id>"""
import os
import sys

import httpx

c = httpx.Client(base_url=os.getenv("STUDIO_URL", "http://localhost:8001"), timeout=60)
fid = int(sys.argv[1])
t = c.get(f"/api/films/{fid}").json()
shots = [s for sc in t["scenes"] for s in sc["shots"]]
for s in shots:
    if s["failed"]:
        print("ujecie z bledem:", s["title"], "|", (s["note"] or "")[:100])
        what = "image" if not s["state"]["image"] else "clip"
        print("  reset", what, c.post(f"/api/film-shots/{s['id']}/reset", json={"what": what}).status_code)
r = c.post(f"/api/films/{fid}/produce")
print("produce:", r.status_code, r.json()["film"]["status"], r.json().get("estimate"))
