"""Weryfikacja trybu Duet prawdziwym Sogni przez API dzialajacego programu (STUDIO_URL, domyslnie http://localhost:8012).
Skrypt doswiadczalny (nie test): zleca zadania, czeka, zapisuje obrazy do katalogu wynikow i drukuje zuzycie planu.
Uzycie: python -m tests.duet_live <etap> [argumenty]
  partner                      tworzy partnera B (fikcyjny, dorosly) i zleca minimalny kanon (twarz + sylwetka)
  approve                      zatwierdza do kanonu B pierwsze wyniki twarzy i sylwetki
  pairs <model> <n>            seria zdjec par (sceny w SCENES) na wskazanym modelu edycji
  pose <slug> <opis>           generuje obraz ukladu cial (generowanie bez kanonu) i dodaje do biblioteki jako obraz pozycji
  posed <slug>                 obraz pary z obrazem pozycji (3 referencje)
  clip <artifact_id>           klip i2v z obrazu pary
  flf <start_id> <end_id>      klip start->koniec
  usage                        zuzycie planu i saldo
Sceny pary sa celowo ubrane/nieeksplicytne: sprawdzaja mechanizm (dwie tozsamosci, interakcja, uklad), nie tresc."""
import json
import os
import sys
import time
from pathlib import Path

import httpx

from app import config

B = os.getenv("STUDIO_URL", "http://localhost:8012")
OUT = Path(os.getenv("DUET_OUT", "duet_render"))
OUT.mkdir(parents=True, exist_ok=True)
STATE = OUT / "state.json"
c = httpx.Client(base_url=B, timeout=120)


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(d):
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def usage():
    c.get("/api/duet/config").raise_for_status()   # serwer zyje
    raw = httpx.get("https://api.sogni.ai/v1/subscriptions/usage", headers={"Authorization": "Bearer " + config.SOGNI_API_KEY},
                    timeout=30)
    d = raw.json()["data"]["usage"]["value"]["daily"]
    return d["renderSpark"], d["jobs"]


def wait_jobs(job_ids, timeout=1500):
    end = time.time() + timeout
    while time.time() < end:
        jobs = {j["id"]: j for j in c.get("/api/jobs").json()}
        if all(jobs[i]["status"] in ("done", "failed") for i in job_ids if i in jobs) and all(i in jobs for i in job_ids):
            return [jobs[i] for i in job_ids]
        time.sleep(5)
    raise TimeoutError("zadania nie skonczyly sie w czasie")


def fetch_artifact(aid_row, name):
    p = OUT / name
    p.write_bytes(httpx.get(B + "/files/" + aid_row["path"], timeout=60).content)
    return str(p)


SCENES = [
    ("embrace", "standing embrace", "Mira and Kael stand on a windswept cliff at dawn, holding each other in a tight embrace", 0, 5, 3.5),
    ("kiss", "kiss", "Mira and Kael share a gentle kiss in a lantern-lit village street at night", 20, 5, 2.4),
    ("lap", "sitting on lap", "Mira sits on Kael's lap on a wooden chair by a fireplace in a cozy tavern, her arms around his neck, both fully dressed", 30, 5, 3.5),
    ("spoon", "spooning", "Mira and Kael lie spooning on a bed under a thick wool blanket, both fully dressed, warm candlelight", 40, 20, 3.5),
    ("wall", "against wall", "Kael leans against a stone wall in a torch-lit corridor while Mira stands close facing him, her hands on his chest, both fully dressed", 25, 5, 3.0),
    ("side", "side by side", "Mira and Kael walk side by side along a forest path holding hands, gentle morning light", 60, 5, 4.5),
]


def pair_shot(key_desc, interaction, az, el, dist):
    s = state()
    return c.post("/api/duet/shots", json={"a_id": s["a"], "b_id": s["b"], "az": az, "el": el, "dist": dist, "fov": 35, "fmt": "16:9",
                                           "action": "", "outfit": "", "outfit_b": "", "interaction": interaction}).json()["id"]


def main(a):
    cmd = a[0]
    s = state()
    if cmd == "usage":
        print("zuzycie dnia (renderSpark, zadania):", usage())
    elif cmd == "partner":
        s["a"] = int(os.getenv("DUET_A", "2"))
        u0 = usage()
        r = c.post("/api/characters", json={"name": "Kael", "archetype": "adult knight in his early 30s",
                                            "traits": "short black hair, trimmed dark beard, brown eyes, broad athletic build",
                                            "outfit": "dark blue tunic with a steel breastplate and leather bracers",
                                            "style": "cinematic fantasy, semi-realistic, soft natural light, detailed",
                                            "adult_fictional": True, "kind": "partner"})
        r.raise_for_status()
        s["b"] = r.json()["id"]
        res = c.post("/api/duet/partner-canon", json={"partner_id": s["b"], "image_model": "krea-2-turbo", "fmt": "1:1" if False else "16:9"})
        res.raise_for_status()
        jobs = [i["jobs"][0] for i in res.json()["items"]]
        print("zlecono kanon B:", jobs)
        done = wait_jobs(jobs)
        print([(j["id"], j["status"], j["error"]) for j in done])
        arts = c.get(f"/api/artifacts?character_id={s['b']}").json()
        for x in arts:
            print(x["id"], x["label"], fetch_artifact(x, f"canonB_{x['id']}.png"))
        s["canon_arts"] = [x["id"] for x in arts]
        save(s)
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "approve":
        for aid, role in ((int(a[1]), "face"), (int(a[2]), "body")):
            r = c.post(f"/api/artifacts/{aid}/approve", data={"role": role})
            print(aid, role, r.status_code)
    elif cmd == "pairs":
        model, n = a[1], int(a[2])
        u0 = usage()
        started = []
        for key, lib, text, az, el, dist in SCENES[:n]:
            sid = pair_shot(key, text, az, el, dist)
            r = c.post(f"/api/duet/shots/{sid}/generate", json={"count": 1, "edit_model": model, "interaction": text})
            r.raise_for_status()
            j = r.json()
            started.append((key, j["jobs"][0], sid))
            print(key, "job", j["jobs"][0], "refs", j["refs"], "ostrz.", j["warnings"])
        done = wait_jobs([x[1] for x in started])
        arts = {x["job_id"]: x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json()}
        s.setdefault("pairs", {})
        for (key, jid, sid), j in zip(started, done):
            if j["status"] == "done" and jid in arts:
                path = fetch_artifact(arts[jid], f"pair_{model}_{key}.png")
                s["pairs"][f"{model}:{key}"] = arts[jid]["id"]
                print(key, "OK", arts[jid]["id"], path)
            else:
                print(key, "BLAD", j["error"])
        save(s)
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "pose":
        # obraz ukladu cial do biblioteki: generowanie bez kanonu (obcy ludzie w neutralnym stroju), potem wgranie jako obraz pozycji
        slug, desc = a[1], a[2]
        u0 = usage()
        if "pose_char" not in s:
            s["pose_char"] = c.post("/api/characters", json={
                "name": "Poza", "archetype": "two adult people", "traits": "plain neutral everyday clothes, neutral faces",
                "outfit": "plain clothes", "style": "photographic, plain studio background, full body", "adult_fictional": True}).json()["id"]
        sid = c.post("/api/shots", json={"character_id": s["pose_char"], "az": 0, "el": 5, "dist": 6.0, "fov": 35, "fmt": "16:9",
                                         "action": desc, "outfit": "plain clothes"}).json()["id"]
        r = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": os.getenv("DUET_POSE_MODEL", "krea-2-turbo"), "count": 1})
        r.raise_for_status()
        wait_jobs(r.json()["jobs"])
        art = [x for x in c.get(f"/api/artifacts?character_id={s['pose_char']}").json() if x["shot_id"] == sid][0]
        p = fetch_artifact(art, f"poseimg_{slug}.png")
        up = c.post(f"/api/duet/interactions/{slug}/image", files={"file": (f"{slug}.png", Path(p).read_bytes(), "image/png")})
        print("obraz pozycji", slug, up.status_code, p)
        save(s)
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "posed":
        slug = a[1]
        u0 = usage()
        text = {k[1].replace(" ", "-"): k[2] for k in SCENES}[slug]
        sid = pair_shot(slug, text, *{k[1].replace(" ", "-"): (k[3], k[4], k[5]) for k in SCENES}[slug])
        r = c.post(f"/api/duet/shots/{sid}/generate", json={"count": 1, "edit_model": "qwen", "interaction": text, "interaction_id": slug})
        r.raise_for_status()
        j = r.json()
        print(slug, "job", j["jobs"][0], "pose_used", j["pose"], "ostrz.", j["warnings"])
        wait_jobs(j["jobs"])
        arts = {x["job_id"]: x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json()}
        s.setdefault("posed", {})
        s["posed"][slug] = arts[j["jobs"][0]]["id"]
        print(slug, "OK", s["posed"][slug], fetch_artifact(arts[j["jobs"][0]], f"posed_{slug}.png"))
        save(s)
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "clip":
        u0 = usage()
        art = int(a[1])
        row = [x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json() if x["id"] == art][0]
        r = c.post(f"/api/duet/shots/{row['shot_id']}/video", json={"source_artifact_id": art, "duration": 5})
        print("klip:", r.status_code, r.text[:300])
        r.raise_for_status()
        done = wait_jobs(r.json()["jobs"], 2400)
        print([(j["id"], j["status"], j["error"]) for j in done])
        arts = {x["job_id"]: x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json()}
        for j in done:
            if j["id"] in arts:
                s.setdefault("clips", {})[str(art)] = arts[j["id"]]["id"]
                print("klip OK", arts[j["id"]]["id"], fetch_artifact(arts[j["id"]], f"clip_{art}.mp4"))
        save(s)
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "flf":
        u0 = usage()
        st, en = int(a[1]), int(a[2])
        row = [x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json() if x["id"] == st][0]
        r = c.post(f"/api/duet/shots/{row['shot_id']}/video", json={"source_artifact_id": st, "end_artifact_id": en})
        print("flf:", r.status_code, r.text[:300])
        r.raise_for_status()
        done = wait_jobs(r.json()["jobs"], 2400)
        print([(j["id"], j["status"], j["error"]) for j in done])
        arts = {x["job_id"]: x for x in c.get(f"/api/duet/artifacts?a={s['a']}&b={s['b']}").json()}
        for j in done:
            if j["id"] in arts:
                print("flf OK", arts[j["id"]]["id"], fetch_artifact(arts[j["id"]], f"flf_{st}_{en}.mp4"))
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    elif cmd == "film":
        # film 2 sceny x 2 ujecia z partnerem: plan rezysera AI, produkcja (obrazy pary + klipy), montaz
        u0 = usage()
        idea = ("Mira i Kael spotykaja sie po dlugiej rozlace w wiosce rozswietlonej latarniami. Scena 1: powitanie i czuly uscisk na "
                "ulicy wieczorem. Scena 2: spokojna wspolna kolacja przy kominku w karczmie, rozmowa i dotyk dloni. Bez przemocy; "
                "oboje sa dorosli i w ubraniach.")
        fid = c.post("/api/films", json={"character_id": s["a"], "partner_id": s["b"], "title": "Powrot", "fmt": "16:9",
                                         "interaction": "Mira and Kael are close, affectionate and fully dressed",
                                         "music_prompt": "warm acoustic folk, soft guitar and strings, slow tempo 70 BPM, instrumental, no vocals"}).json()["film"]["id"]
        s["film"] = fid
        save(s)
        r = c.post(f"/api/films/{fid}/plan", json={"idea": idea, "scenes": 2, "shots_per_scene": 2, "replace": False})
        print("plan:", r.status_code, r.text[:200])
        r.raise_for_status()
        end = time.time() + 600
        while time.time() < end:
            t = c.get(f"/api/films/{fid}").json()
            st = t["film"]["plan_state"] or ""
            if st == "done" or st.startswith("error"):
                break
            time.sleep(5)
        print("plan_state:", st)
        for sc in t["scenes"]:
            print("SCENA", sc["idx"] + 1, sc["title"], "|", sc["location"], "|", sc["lighting"])
            for sh in sc["shots"]:
                print("  ujecie", sh["idx"] + 1, "dist", sh["dist"], "az", sh["az"], "czas", sh["duration"], "link", sh["link_next"], "|", sh["action"][:90], "| inter:", sh["interaction"][:90], "| outfit_b:", sh["outfit_b"][:40])
        if st != "done":
            return
        print("produce:", c.post(f"/api/films/{fid}/produce").status_code)
        end = time.time() + 2400
        while time.time() < end:
            t = c.get(f"/api/films/{fid}").json()
            p = t["progress"]
            print(t["film"]["status"], p, (t["film"]["note"] or "")[:100], flush=True)
            if t["film"]["status"] in ("ready", "needs_attention"):
                break
            time.sleep(30)
        r = c.post(f"/api/films/{fid}/assemble", json={"fade": 0.4, "audio_mode": "normalize", "subtitles": "none", "allow_partial": True})
        print("assemble:", r.status_code, r.text[:120])
        end = time.time() + 600
        while time.time() < end:
            t = c.get(f"/api/films/{fid}").json()
            st = t["film"]["assemble_state"] or ""
            if st.startswith("done") or st.startswith("error"):
                break
            time.sleep(5)
        print("assemble_state:", st[:300])
        fin = t["film"].get("final")
        if fin:
            print("final:", fetch_artifact(fin, "film_final.mp4"))
        for sc in t["scenes"]:
            for sh in sc["shots"]:
                im = sh["state"]["image"]
                if im:
                    fetch_artifact(im, f"film_s{sc['idx'] + 1}_{sh['idx'] + 1}.png")
        u1 = usage()
        print("koszt etapu: Spark", round(u1[0] - u0[0], 2), "zadan", u1[1] - u0[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
