"""Podglad planu filmu: STUDIO_URL=... python -m tests.show_film <id> [--wait]"""
import json
import os
import sys
import time

import httpx

c = httpx.Client(base_url=os.getenv("STUDIO_URL", "http://localhost:8001"), timeout=60)
fid = sys.argv[1]
if "--wait" in sys.argv:
    end = time.time() + 480
    while time.time() < end:
        st = c.get(f"/api/films/{fid}").json()["film"]["plan_state"] or ""
        if st == "done" or st.startswith("error"):
            break
        time.sleep(5)
t = c.get(f"/api/films/{fid}").json()
f = t["film"]
print("plan_state:", f["plan_state"])
print("tytul:", f["title"], "| logline:", f["logline"])
print("muzyka:", f["music_prompt"])
for sc in t["scenes"]:
    print(f"\nSCENA {sc['idx'] + 1}: {sc['title']} | {sc['location']} | {sc['lighting']}\n  {sc['summary']}")
    for s in sc["shots"]:
        print(f"   - {s['title']}: az {s['az']:.0f} el {s['el']:.0f} dist {s['dist']:.1f} {s['duration']}s link={s['link_next']} | {s['action'][:110]}"
              + (f" | \"{s['dialogue']}\"" if s["dialogue"] else ""))
print("\nUjec:", t["progress"]["shots"], "| szac. czas:", t["est_seconds"], "s | estymata:", t.get("estimate"))
