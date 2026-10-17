"""Pomocnik Etapu 0: steruje dzialajacym programem (localhost:8000) przez jego API.

Uzycie: python -m tests.stage0 <komenda> [argumenty]
  setup                      tworzy postac testowa
  gen <char> <az> <el> <dist> <fmt> <kind> <n> <akcja...>
  wait <char>                czeka na koniec zadan i wypisuje wyniki
  approve <artifact> <rola>
  usage                      pokazuje zuzycie planu (tylko odczyt)
"""
import json
import sys
import time

import httpx

import os

B = os.getenv("STUDIO_URL", "http://localhost:8000")
c = httpx.Client(base_url=B, timeout=60)


def show(x):
    print(json.dumps(x, ensure_ascii=False, indent=1)[:3000])


def main(a):
    cmd = a[0]
    if cmd == "setup":
        r = c.post("/api/characters", json={
            "name": "Aria", "archetype": "adult huntress in her late 20s",
            "traits": "long silver braided hair, green eyes, small scar on left cheek, athletic build",
            "outfit": "dark green hooded cloak over brown leather armor, silver clasp, fingerless gloves",
            "style": "cinematic fantasy, semi-realistic, soft natural light, detailed",
            "adult_fictional": True})
        show(r.json())
    elif cmd == "gen":
        cid, az, el, dist, fmt, kind, n = int(a[1]), *map(float, a[2:5]), a[5], a[6], int(a[7])
        action = " ".join(a[8:])
        sh = c.post("/api/shots", json={"character_id": cid, "az": az, "el": el, "dist": dist, "fov": 35,
                                        "fmt": fmt, "action": action}).json()
        g = c.post(f"/api/shots/{sh['id']}/generate", json={"kind": kind, "count": n})
        print("shot", sh["id"], g.status_code, g.json())
    elif cmd == "wait":
        cid = int(a[1])
        end = time.time() + 900
        while time.time() < end:
            jobs = c.get(f"/api/jobs?character_id={cid}").json()
            if jobs and all(j["status"] in ("done", "failed") for j in jobs):
                break
            time.sleep(5)
        for j in jobs[:12]:
            print("job", j["id"], j["kind"], j["model"], j["status"], (j["error"] or "")[:200])
        for ar in c.get(f"/api/artifacts?character_id={cid}").json()[:12]:
            print("artifact", ar["id"], "shot", ar["shot_id"], ar["kind"], ar["path"], "az", ar["az"], "el", ar["el"])
    elif cmd == "approve":
        r = c.post(f"/api/artifacts/{a[1]}/approve", data={"role": a[2]})
        print(r.status_code, r.text)
    elif cmd == "usage":
        sys.path.insert(0, ".")
        from app.providers.sogni import SogniProvider
        u = SogniProvider()._call("GET", "/v1/subscriptions/usage").json()["data"]["usage"]
        print("daily:", u["value"]["daily"], "\ncycle:", u["value"]["cycle"], "\nfairUse:", u.get("fairUse"))


main(sys.argv[1:])
