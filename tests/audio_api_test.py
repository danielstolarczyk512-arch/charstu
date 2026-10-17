"""Testy API dzwieku na dostawcy mock: python -m tests.audio_api_test"""
import os
import tempfile
import time

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-audio-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app import audio, config  # noqa: E402
from app.main import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


def wait(c, cid, ids, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        js = {j["id"]: j for j in c.get(f"/api/jobs?character_id={cid}").json()}
        if all(js[i]["status"] in ("done", "failed") for i in ids):
            return js
        time.sleep(0.5)
    raise AssertionError("timeout")


with TestClient(app) as c:
    cid = c.post("/api/characters", json={"name": "V", "archetype": "adult bard", "adult_fictional": True}).json()["id"]

    v = c.get(f"/api/characters/{cid}/voice").json()
    check("1 domyslny glos: studyjny serena, english", v["mode"] == "voice" and v["voice"] == "serena" and v["language"] == "english")
    check("2 lista glosow i jezykow; brak polskiego", "ryan" in v["studio_voices"] and "polish" not in v["languages"])
    r = c.put(f"/api/characters/{cid}/voice", json={"voice": "ryan", "language": "english"})
    check("3 ustawienie glosu studyjnego", r.status_code == 200 and r.json()["voice"] == "ryan")
    check("4 nieznany glos -> 400", c.put(f"/api/characters/{cid}/voice", json={"voice": "x"}).status_code == 400)
    check("5 jezyk spoza listy (polish) -> 400", c.put(f"/api/characters/{cid}/voice", json={"voice": "ryan", "language": "polish"}).status_code == 400)

    j = c.post("/api/speech", json={"character_id": cid, "text": "Welcome to the story of the valley."}).json()
    jm = c.post("/api/music", json={"character_id": cid, "prompt": "calm orchestral theme, 80 BPM, D minor", "duration": 12}).json()
    js = wait(c, cid, [j["job"], jm["job"]])
    arts = [a for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "audio"]
    check("6 kwestia i muzyka dostarczone jako artefakty audio", len(arts) == 2 and all(x["status"] == "done" for x in (js[j["job"]], js[jm["job"]])), len(arts))
    check("7 etykiety artefaktow audio zapisane", {a["label"] for a in arts} >= {"Welcome to the story of the valley."}, [a["label"] for a in arts])
    check("8 tekst pusty -> 400", c.post("/api/speech", json={"character_id": cid, "text": "  "}).status_code == 400)
    check("9 za dlugi tekst -> 400", c.post("/api/speech", json={"character_id": cid, "text": "a" * 601}).status_code == 400)
    check("10 muzyka: dlugosc poza 10-300 -> 400", c.post("/api/music", json={"character_id": cid, "prompt": "x", "duration": 5}).status_code == 400)

    d = c.post(f"/api/characters/{cid}/voice/design", json={"description": "A warm, low-pitched narrator"}).json()
    wait(c, cid, [d["job"]])
    v = c.get(f"/api/characters/{cid}/voice").json()
    check("11 po projekcie glos przelaczony na klon z transkryptem", v["mode"] == "clone" and v["ref_artifact_id"] and len(v["transcript"]) > 100,
          {k: v.get(k) for k in ("mode", "ref_artifact_id")})
    j2 = c.post("/api/speech", json={"character_id": cid, "text": "A line in the cloned voice."}).json()
    check("12 kwestia po projekcie uzywa klona", j2["voice"]["mode"] == "clone")
    wait(c, cid, [j2["job"]])

    # klipy wideo (mock) do sklejki
    sh = c.post("/api/shots", json={"character_id": cid, "az": 0, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9", "action": "stands"}).json()["id"]
    gi = c.post(f"/api/shots/{sh}/generate", json={"kind": "image", "count": 2, "use_refs": False}).json()
    wait(c, cid, gi["jobs"])
    imgs = [a for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "image"]
    vids = []
    for im in imgs[:2]:
        gv = c.post(f"/api/shots/{sh}/generate", json={"kind": "video", "source_artifact_id": im["id"]}).json()
        wait(c, cid, gv["jobs"])
    vids = sorted([a["id"] for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "video"])
    check("13 dwa klipy do sklejki", len(vids) == 2, vids)

    au = {a["label"]: a["id"] for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "audio"}
    bed = next(i for k, i in au.items() if "orchestral" in k)
    speech = [i for k, i in au.items() if "cloned voice" in k or "Welcome" in k]
    r = c.post("/api/stitch", json={"artifact_ids": vids, "fade": 0.3, "audio_mode": "normalize", "bed_artifact_id": bed,
                                    "bed_db": -22, "voice_artifact_ids": speech[:2]})
    j = r.json()
    check("14 sklejka z podkladem i lektorem: HTTP 200", r.status_code == 200, r.text[:200])
    info = j.get("info", {})
    check("15 wynik zmiksowany, glosnosc w okolicy -16 LUFS", info.get("bed") and info.get("voices") == 2 and abs(info["mixed_lufs"] + 16) <= 3, info.get("mixed_lufs"))
    check("16 plik wynikowy istnieje i ma audio", (config.DATA / j["path"]).exists() and audio.loudness(config.DATA / j["path"])["lufs"] > -40)
    check("17 nieznany audio_mode -> 400", c.post("/api/stitch", json={"artifact_ids": vids, "audio_mode": "zly"}).status_code == 400)
    check("18 podklad nie-audio -> 400", c.post("/api/stitch", json={"artifact_ids": vids, "bed_artifact_id": imgs[0]["id"]}).status_code == 400)

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
