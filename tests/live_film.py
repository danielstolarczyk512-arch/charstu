"""Prawdziwa produkcja filmu na Sogni przez dzialajacy program: STUDIO_URL=... python -m tests.live_film <film_id> [start|watch|assemble]
start: ustawia glos (projekt raz + klon), uruchamia produkcje; watch: pokazuje postep do konca; assemble: montaz."""
import json
import os
import sys
import time

import httpx

c = httpx.Client(base_url=os.getenv("STUDIO_URL", "http://localhost:8001"), timeout=120)
fid = int(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "watch"


def tree():
    return c.get(f"/api/films/{fid}").json()


def line(t):
    f, p = t["film"], t["progress"]
    return (f"[{time.strftime('%H:%M:%S')}] {f['status']:15s} obrazy {p['images']}/{p['shots']} klipy {p['clips']}/{p['shots']} "
            f"kwestie {p['speech_done']}/{p['speech_needed']} podklad {'tak' if p['bed'] else 'nie'} bledy {p['failed']} "
            f"| zuzycie {t['spent']['spark']} ({t['spent']['source']}) | {(f['note'] or '')[:90]}")


if mode == "start":
    t = tree()
    cid = t["film"]["character_id"]
    v = c.get(f"/api/characters/{cid}/voice").json()
    if v["mode"] != "clone":
        d = c.post(f"/api/characters/{cid}/voice/design", json={"description": "A calm, warm young woman's voice, low-mid pitch, "
                                                                            "thoughtful and steady, speaking slowly", "language": "english"})
        print("projekt glosu:", d.status_code, d.json())
        end = time.time() + 300
        while time.time() < end:
            v = c.get(f"/api/characters/{cid}/voice").json()
            if v["mode"] == "clone":
                break
            time.sleep(5)
        print("glos:", {k: v.get(k) for k in ("mode", "ref_artifact_id", "language")})
    r = c.post(f"/api/films/{fid}/produce")
    print("produkcja:", r.status_code, r.json()["film"]["status"], r.json().get("estimate"))
elif mode == "watch":
    last = ""
    end = time.time() + float(os.getenv("WATCH_SECONDS", "540"))
    while time.time() < end:
        t = tree()
        s = line(t)
        if s[11:] != last[11:]:
            print(s, flush=True)
            last = s
        if t["film"]["status"] in ("ready", "needs_attention", "paused", "draft"):
            break
        time.sleep(10)
    t = tree()
    for sc in t["scenes"]:
        for sh in sc["shots"]:
            print(f"   {sc['idx'] + 1}.{sh['idx'] + 1} {sh['title'][:28]:28s} {sh['state']['label']:14s} {sh['note'] or ''}")
elif mode == "assemble":
    r = c.post(f"/api/films/{fid}/assemble", json={"fade": 0.4, "audio_mode": "normalize", "subtitles": "burn"})
    print("montaz:", r.status_code)
    end = time.time() + 300
    while time.time() < end:
        s = tree()["film"]["assemble_state"] or ""
        if s.startswith(("done", "error")):
            print(s[:600])
            break
        time.sleep(4)
