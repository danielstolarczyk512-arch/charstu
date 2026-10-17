"""Mierzy twarz dla wybranych artefaktow przez dzialajacy program: STUDIO_URL=... python -m tests.measure_all 14 13 18"""
import json
import os
import sys

import httpx

c = httpx.Client(base_url=os.getenv("STUDIO_URL", "http://localhost:8000"), timeout=400)
for aid in sys.argv[1:]:
    r = c.post(f"/api/artifacts/{aid}/measure")
    print(aid, r.status_code, json.dumps(r.json(), ensure_ascii=False)[:260])
