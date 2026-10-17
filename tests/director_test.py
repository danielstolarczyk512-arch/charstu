"""Testy rezysera AI z odpowiedziami modelu podstawionymi (bez sieci): python -m tests.director_test
Test z prawdziwym modelem jest osobno (tests/director_live.py)."""
import os
import tempfile
import time
from types import SimpleNamespace

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-director-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app import assistant, db, director, film as F, producer  # noqa: E402
from app.main import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


OUTLINE = {"title": "Ostatnia droga", "logline": "Lowczyni opuszcza dolinę.", "synopsis": "Fabula w kilku zdaniach.",
           "music_prompt": "calm strings, 70 BPM, D minor, instrumental, no vocals",
           "scenes": [{"title": "Klif", "summary": "Swit na klifie", "location": "mossy sea cliff", "lighting": "dawn light"},
                      {"title": "Las", "summary": "Marsz przez las", "location": "misty pine forest", "lighting": "overcast"}]}
SCENE = {"shots": [
    {"title": "Przod", "az": 0, "el": 5, "dist": 4.5, "fov": 35, "action": "stands at the edge", "dialogue": "The road is long.", "duration": 5, "link_next": True},
    {"title": "Tyl", "az": 400, "el": 5, "dist": 4.5, "fov": 35, "action": "turns away", "dialogue": "", "duration": 30, "link_next": True}]}
CALLS = []


def fake_chat(provider, msgs, timeout=70, attempts=2):
    CALLS.append(msgs[0]["content"][:30])
    if "ZARYS" in msgs[0]["content"]:
        return FAKE["outline"], ""
    return FAKE["scene"], ""


FAKE = {"outline": OUTLINE, "scene": SCENE}
assistant.chat_json = fake_chat
check("0 wspolne reguly (kamera + granice) wyciagniete z promptu asystenta",
      "TWARDE GRANICE" in assistant.SHARED_RULES and "az (stopnie" in assistant.SHARED_RULES and "Nie twierdz" not in assistant.SHARED_RULES)

with TestClient(app) as c:
    producer.provider = SimpleNamespace(_call=lambda *a, **k: None)   # udaje dostawce z modelem jezykowym
    cid = c.post("/api/characters", json={"name": "A", "archetype": "adult huntress", "adult_fictional": True}).json()["id"]
    fid = c.post("/api/films", json={"character_id": cid, "title": "Roboczy", "fmt": "16:9"}).json()["film"]["id"]

    check("1 pusty pomysl -> 400", c.post(f"/api/films/{fid}/plan", json={"idea": " "}).status_code == 400)
    check("2 pomysl z niepelnoletnia -> 400", c.post(f"/api/films/{fid}/plan", json={"idea": "film o 14 year old girl"}).status_code == 400)
    r = c.post(f"/api/films/{fid}/plan", json={"idea": "Lowczyni zegna sie z dolina", "scenes": 2, "shots_per_scene": 2})
    check("3 plan startuje w tle", r.status_code == 200 and (r.json()["film"]["plan_state"] or "").startswith("planning"), r.json()["film"]["plan_state"])
    end = time.time() + 30
    while time.time() < end and not db.one("SELECT plan_state FROM films WHERE id=?", (fid,))["plan_state"] in ("done",) \
            and not (db.one("SELECT plan_state FROM films WHERE id=?", (fid,))["plan_state"] or "").startswith("error"):
        time.sleep(0.2)
    t = c.get(f"/api/films/{fid}").json()
    check("4 plan zakonczony", t["film"]["plan_state"] == "done", t["film"]["plan_state"])
    check("5 tytul, opis i podklad z zarysu", t["film"]["title"] == "Ostatnia droga" and "70 BPM" in t["film"]["music_prompt"])
    check("6 dwie sceny z miejscem i swiatlem", [s["location"] for s in t["scenes"]] == ["mossy sea cliff", "misty pine forest"])
    shots = [s for sc in t["scenes"] for s in sc["shots"]]
    check("7 ujecia obu scen (2 x 2)", len(shots) == 4 and CALLS.count(CALLS[0]) == 1, [len(sc["shots"]) for sc in t["scenes"]])
    s1 = t["scenes"][0]["shots"]
    check("8 zakresy przyciete (az 400 -> 180, czas 30 -> 8)", s1[1]["az"] == 180 and s1[1]["duration"] == 8, (s1[1]["az"], s1[1]["duration"]))
    check("9 link_next tylko gdy jest nastepne ujecie sceny", s1[0]["link_next"] == 1 and s1[1]["link_next"] == 0, (s1[0]["link_next"], s1[1]["link_next"]))
    check("10 format ujec z filmu", all(s["fmt"] == "16:9" for s in shots))
    r = c.post(f"/api/films/{fid}/plan", json={"idea": "inny pomysl"})
    check("11 film z scenami bez replace -> 409", r.status_code == 409, r.text[:80])

    FAKE["outline"] = {**OUTLINE, "title": "Nowy", "scenes": OUTLINE["scenes"][:1]}
    r = c.post(f"/api/films/{fid}/plan", json={"idea": "inny pomysl", "scenes": 1, "shots_per_scene": 2, "replace": True})
    time.sleep(1.5)
    t = c.get(f"/api/films/{fid}").json()
    check("12 replace zastepuje sceny", t["film"]["plan_state"] == "done" and len(t["scenes"]) == 1 and t["film"]["title"] == "Nowy",
          (t["film"]["plan_state"], len(t["scenes"])))

    # siatka bezpieczenstwa na wyjsciu modelu
    FAKE["scene"] = {"shots": [{"title": "x", "action": "a teenage girl stands", "duration": 5}]}
    c.post(f"/api/films/{fid}/plan", json={"idea": "inny", "scenes": 1, "shots_per_scene": 1, "replace": True})
    time.sleep(1.5)
    t = c.get(f"/api/films/{fid}").json()
    check("13 model zwrocil niepelnoletnia -> plan konczy sie bledem", (t["film"]["plan_state"] or "").startswith("error"), t["film"]["plan_state"])
    FAKE["scene"] = SCENE
    FAKE["outline"] = {"refused": True, "reply": "Nie mogę."}
    c.post(f"/api/films/{fid}/plan", json={"idea": "cos", "replace": True})
    time.sleep(1.2)
    check("14 odmowa modelu -> blad planu z komunikatem", "Nie mogę" in (db.one("SELECT plan_state FROM films WHERE id=?", (fid,))["plan_state"] or ""))
    FAKE["outline"] = None
    assistant.chat_json = lambda *a, **k: (None, "to nie json")
    c.post(f"/api/films/{fid}/plan", json={"idea": "cos", "replace": True})
    time.sleep(1.2)
    check("15 model bez JSON -> czytelny blad", "poprawnego zarysu" in (db.one("SELECT plan_state FROM films WHERE id=?", (fid,))["plan_state"] or ""))
    producer.provider = SimpleNamespace()   # brak _call (jak mock)
    check("16 bez modelu jezykowego -> 409", c.post(f"/api/films/{fid}/plan", json={"idea": "cos", "replace": True}).status_code == 409)

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
