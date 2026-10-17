"""Testy zarzadzania postacia (edycja, usuwanie, szafa) na dostawcy mock: python -m tests.character_test"""
import os
import tempfile

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-char-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


with TestClient(app) as c:
    cid = c.post("/api/characters", json={"name": "Aria", "archetype": "adult huntress", "traits": "silver braid", "outfit": "green cloak",
                                         "style": "cinematic", "adult_fictional": True}).json()["id"]
    r = c.patch(f"/api/characters/{cid}", json={"traits": "silver braid, green eyes, scar on left cheek", "style": "painterly"})
    j = r.json()
    check("1 edycja pol karty", r.status_code == 200 and "scar" in j["traits"] and j["style"] == "painterly" and j["name"] == "Aria", j["traits"])
    check("2 pola nieprzekazane zostaja bez zmian", j["outfit"] == "green cloak" and j["archetype"] == "adult huntress")
    j = c.patch(f"/api/characters/{cid}", json={"archetype": "huntress"}).json()
    check("3 archetyp zawsze dorosly (dopisek 'adult')", j["archetype"] == "adult huntress", j["archetype"])
    check("4 pusty archetyp -> 'adult'", c.patch(f"/api/characters/{cid}", json={"archetype": ""}).json()["archetype"] == "adult")
    check("5 puste imie -> 400", c.patch(f"/api/characters/{cid}", json={"name": "  "}).status_code == 400)
    check("6 siatka bezpieczenstwa: niepelnoletnia w opisie -> 400",
          c.patch(f"/api/characters/{cid}", json={"traits": "a 15 year old girl"}).status_code == 400
          and c.patch(f"/api/characters/{cid}", json={"archetype": "teenage ranger"}).status_code == 400)
    check("7 po odrzuconej edycji karta bez zmian", c.get("/api/characters").json()[0]["traits"].startswith("silver braid, green eyes"))
    check("8 edycja nieistniejacej postaci -> 404", c.patch("/api/characters/999", json={"name": "x"}).status_code == 404)

    o = c.post(f"/api/characters/{cid}/outfits", json={"name": "Podróżny", "description": "dark green travel cloak and leather boots"})
    check("9 dodanie stroju do szafy", o.status_code == 200 and o.json()["name"] == "Podróżny")
    c.post(f"/api/characters/{cid}/outfits", json={"name": "Wieczór", "description": "an elegant midnight-blue evening gown"})
    lst = c.get(f"/api/characters/{cid}/outfits").json()
    check("10 lista szafy w kolejnosci dodania", [x["name"] for x in lst] == ["Podróżny", "Wieczór"])
    check("11 pusta nazwa/opis -> 400", c.post(f"/api/characters/{cid}/outfits", json={"name": " ", "description": "x"}).status_code == 400
          and c.post(f"/api/characters/{cid}/outfits", json={"name": "x", "description": ""}).status_code == 400)
    check("12 strój niepelnoletni -> 400", c.post(f"/api/characters/{cid}/outfits", json={"name": "Szkola", "description": "a child school uniform"}).status_code == 400)
    check("13 szafa nieistniejacej postaci -> 404", c.get("/api/characters/999/outfits").status_code == 404)
    c.delete(f"/api/outfits/{lst[0]['id']}")
    check("14 usuniecie stroju", [x["name"] for x in c.get(f"/api/characters/{cid}/outfits").json()] == ["Wieczór"])

    # strój z szafy w promptach (pole outfit ujecia)
    sh = c.post("/api/shots", json={"character_id": cid, "az": 0, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9", "action": "stands",
                                    "outfit": lst[1]["description"], "use_refs": False}).json()
    check("15 strój z szafy trafia do ujecia", "evening gown" in sh["prompt"], sh["prompt"][:100])

    f = c.post("/api/films", json={"character_id": cid, "title": "F"}).json()["film"]["id"]
    check("16 usuniecie postaci z filmami -> 409", c.delete(f"/api/characters/{cid}").status_code == 409)
    c.delete(f"/api/films/{f}")
    r = c.delete(f"/api/characters/{cid}")
    check("17 usuniecie postaci bez filmow + czyszczenie szafy", r.status_code == 200 and not c.get("/api/characters").json()
          and c.get(f"/api/characters/{cid}/outfits").status_code == 404)

    # ---------- arkusz postaci i poprawki ----------
    import io
    import json
    import time

    from PIL import Image

    from app import db
    cid = c.post("/api/characters", json={"name": "B", "archetype": "adult knight", "adult_fictional": True}).json()["id"]
    check("18 arkusz bez kanonu -> 409", c.post(f"/api/characters/{cid}/sheet", json={}).status_code == 409)
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (5, 5, 5)).save(b, "PNG")
    c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"}, files={"file": ("f.png", b.getvalue(), "image/png")})
    r = c.post(f"/api/characters/{cid}/sheet", json={})
    items = r.json()["items"]
    check("19 arkusz: 8 zlecen (4 widoki + 4 miny) przez edycje z kanonu", r.status_code == 200 and len(items) == 8
          and all(i["kind"] == "edit" for i in items), [i["name"] for i in items])
    check("20 arkusz: role kanonu podpowiedziane", [i["role"] for i in items] == ["front", "three_quarter", "profile", "back", "face", "face", "face", "face"])
    ids = [i["jobs"][0] for i in items]
    end = time.time() + 120
    while time.time() < end:
        js = {j["id"]: j for j in c.get(f"/api/jobs?character_id={cid}").json()}
        if all(js[i]["status"] in ("done", "failed") for i in ids):
            break
        time.sleep(0.5)
    arts = [a for a in c.get(f"/api/artifacts?character_id={cid}").json() if a["kind"] == "image"]
    check("21 arkusz: 8 obrazow z etykietami 'arkusz:<rola>:<nazwa>'", len(arts) == 8 and all((a["label"] or "").startswith("arkusz:") for a in arts),
          sorted({a["label"] for a in arts})[:3])
    prompts_ = {json.loads(db.one("SELECT params FROM jobs WHERE id=?", (i,))["params"])["prompt"] for i in ids}
    check("22 arkusz: widoki i miny maja rozne prompty (kamera/ekspresja)", len(prompts_) == 8 and any("back view" in p for p in prompts_)
          and any("surprised" in p for p in prompts_))
    src = arts[0]["id"]
    r = c.post(f"/api/characters/{cid}/refine", json={"source_artifact_id": src, "instruction": "make her braid longer", "count": 2})
    check("23 poprawka: 2 warianty edycji", r.status_code == 200 and len(r.json()["jobs"]) == 2 and r.json()["kind"] == "edit", r.text[:100])
    pj = json.loads(db.one("SELECT params FROM jobs WHERE id=?", (r.json()["jobs"][0],))["params"])
    check("24 poprawka: obraz zrodlowy jako referencja + instrukcja 'zostaje reszta'", pj["ref_artifact_ids"] == [src] and "exactly the same" in pj["prompt"]
          and pj["prompt"].startswith("Make her braid longer."), pj["prompt"][:90])
    check("25 poprawka: pusta instrukcja -> 400", c.post(f"/api/characters/{cid}/refine", json={"source_artifact_id": src, "instruction": " "}).status_code == 400)
    check("26 poprawka: niepelnoletnia -> 400", c.post(f"/api/characters/{cid}/refine", json={"source_artifact_id": src, "instruction": "make her look like a child"}).status_code == 400)
    check("27 poprawka: zrodlo nie jest obrazem/nie istnieje -> 400", c.post(f"/api/characters/{cid}/refine", json={"source_artifact_id": 99999, "instruction": "x"}).status_code == 400)
    check("28 poprawka modelem tylko-do-generowania -> 400", c.post(f"/api/characters/{cid}/refine", json={"source_artifact_id": src, "instruction": "x", "edit_model": "krea-2-turbo"}).status_code == 400)
    end = time.time() + 120
    while time.time() < end:
        js = {j["id"]: j for j in c.get(f"/api/jobs?character_id={cid}").json()}
        if all(js[i]["status"] in ("done", "failed") for i in r.json()["jobs"]):
            break
        time.sleep(0.5)
    refined = [a for a in c.get(f"/api/artifacts?character_id={cid}").json() if (a["label"] or "").startswith("poprawka:")]
    check("29 poprawka: wyniki w galerii z etykieta", len(refined) == 2, [a["label"] for a in refined][:1])

    # ---------- poza z referencji ----------
    cid = c.post("/api/characters", json={"name": "P", "archetype": "adult dancer", "adult_fictional": True}).json()["id"]
    r = c.get(f"/api/characters/{cid}/poses").json()
    check("30 lista pozy: presety szkieletow dostepne, biblioteka pusta", "klek" in r["presets"] and r["poses"] == [])
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (5, 5, 5)).save(b, "PNG")
    c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"}, files={"file": ("f.png", b.getvalue(), "image/png")})
    pa = c.post(f"/api/characters/{cid}/poses", data={"preset": "siedzi"})
    check("31 poza ze szkieletu (preset)", pa.status_code == 200 and pa.json()["label"] == "poza:szkielet siedzi", pa.text[:90])
    pb = c.post(f"/api/characters/{cid}/poses", data={"name": "wojownik"}, files={"file": ("w.jpg", b.getvalue(), "image/png")})
    check("32 poza z pliku obrazu", pb.status_code == 200 and pb.json()["label"] == "poza:wojownik")
    check("33 zly preset / brak danych / zly plik -> 400",
          c.post(f"/api/characters/{cid}/poses", data={"preset": "nie-ma"}).status_code == 400
          and c.post(f"/api/characters/{cid}/poses", data={}).status_code == 400
          and c.post(f"/api/characters/{cid}/poses", files={"file": ("w.png", b"zepsute", "image/png")}).status_code == 400)
    pc = c.post(f"/api/characters/{cid}/poses", data={"points": json.dumps({"nose": [0.5, 0.2], "neck": [0.5, 0.3]})})
    check("34 wlasny szkielet wymaga >=8 punktow", pc.status_code == 400)
    check("35 biblioteka pozy zawiera 2 wpisy", len(c.get(f"/api/characters/{cid}/poses").json()["poses"]) == 2)
    sh = c.post("/api/shots", json={"character_id": cid, "az": 0, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9", "action": "kneels",
                                    "use_refs": True}).json()["id"]
    r = c.post(f"/api/shots/{sh}/generate", json={"kind": "image", "pose_artifact_id": pa.json()["id"]})
    pj = json.loads(db.one("SELECT params, model FROM jobs WHERE id=?", (r.json()["jobs"][0],))["params"]) if r.status_code == 200 else {}
    check("36 generowanie z poza: kanon + poza jako referencje, model Qwen", r.status_code == 200 and r.json()["pose"] == pa.json()["id"]
          and pj["ref_artifact_ids"] == [pa.json()["id"]] and len(pj["ref_ids"]) == 1
          and db.one("SELECT model FROM jobs WHERE id=?", (r.json()["jobs"][0],))["model"] == "qwen", r.text[:120])
    check("37 prompt pozy: role obrazow (1. kanon, 2. poza)", "second image" in pj.get("prompt", "") and "first image" in pj.get("prompt", ""))
    check("38 poza modelem Krea -> 400",
          c.post(f"/api/shots/{sh}/generate", json={"kind": "image", "pose_artifact_id": pa.json()["id"], "edit_model": "krea-identity-edit"}).status_code == 400)
    check("39 poza bedaca nieistniejacym obrazem -> 400",
          c.post(f"/api/shots/{sh}/generate", json={"kind": "image", "pose_artifact_id": 99999}).status_code == 400)
    c2 = c.post("/api/characters", json={"name": "Q", "archetype": "adult", "adult_fictional": True}).json()["id"]
    sh2 = c.post("/api/shots", json={"character_id": c2, "fmt": "16:9", "use_refs": False}).json()["id"]
    check("40 poza bez kanonu postaci -> 409",
          c.post(f"/api/shots/{sh2}/generate", json={"kind": "image", "pose_artifact_id": pa.json()["id"]}).status_code == 409)

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
