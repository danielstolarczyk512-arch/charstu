"""Testy filmu (struktura + producent) na dostawcy mock: python -m tests.film_test"""
import io
import os
import tempfile
import time

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-film-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import config, db, film as F, producer  # noqa: E402
from app.main import app, state  # noqa: E402
from app.providers.base import ProviderError, SafetyRejected  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


def wait_status(c, fid, want, timeout=240):
    end = time.time() + timeout
    t = None
    while time.time() < end:
        t = c.get(f"/api/films/{fid}").json()
        if t["film"]["status"] in want:
            return t
        time.sleep(0.5)
    return t


with TestClient(app) as c:
    state["producer"].interval = 0.3
    cid = c.post("/api/characters", json={"name": "Aria", "archetype": "adult huntress", "traits": "silver braid",
                                          "outfit": "green cloak", "style": "cinematic", "adult_fictional": True}).json()["id"]
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (9, 9, 9)).save(b, "PNG")
    c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"}, files={"file": ("f.png", b.getvalue(), "image/png")})

    # ---------- A. struktura ----------
    r = c.post("/api/films", json={"character_id": cid, "title": "Test", "logline": "Lowczyni na klifie", "fmt": "16:9",
                                   "music_prompt": "calm strings, 70 BPM, instrumental"})
    check("A1 utworzenie filmu", r.status_code == 200 and r.json()["film"]["status"] == "draft")
    fid = r.json()["film"]["id"]
    check("A2 film dla nieistniejacej postaci -> 404", c.post("/api/films", json={"character_id": 999, "title": "x"}).status_code == 404)
    check("A3 pusty tytul -> 400", c.post("/api/films", json={"character_id": cid, "title": "  "}).status_code == 400)
    check("A4 siatka bezpieczenstwa: tytul z niepelnoletnia -> 400",
          c.post("/api/films", json={"character_id": cid, "title": "A teenage girl story"}).status_code == 400)

    c.post(f"/api/films/{fid}/scenes", json={"title": "Klif", "summary": "Swit", "location": "mossy sea cliff",
                                              "lighting": "soft dawn light"})
    c.post(f"/api/films/{fid}/scenes", json={"title": "Las", "summary": "Sciezka", "location": "misty pine forest", "lighting": "overcast"})
    t = c.get(f"/api/films/{fid}").json()
    s1, s2 = t["scenes"][0]["id"], t["scenes"][1]["id"]
    check("A5 dwie sceny w kolejnosci", [s["title"] for s in t["scenes"]] == ["Klif", "Las"])
    for i, (az, d) in enumerate(((0, "The road is long."), (90, ""), (180, "We will not see it again."))):
        c.post(f"/api/scenes/{s1}/shots", json={"title": f"k{i}", "az": az, "el": 5, "dist": 4.5, "action": f"stands {i}", "dialogue": d,
                                                "duration": 5, "link_next": i == 1})
    c.post(f"/api/scenes/{s2}/shots", json={"title": "l0", "action": "walks along a path", "dialogue": "Idziemy dalej do wioski."})
    check("A0 wykrywanie polskiego bez ogonkow i z ogonkami",
          producer.looks_polish("Idziemy dalej do wioski.") and producer.looks_polish("Chodź, żeby odpocząć.")
          and not producer.looks_polish("We will not see it again.") and not producer.looks_polish("The road is long."))
    t = c.get(f"/api/films/{fid}").json()
    shots = [s for sc in t["scenes"] for s in sc["shots"]]
    check("A6 cztery ujecia, poprawny podzial", [len(sc["shots"]) for sc in t["scenes"]] == [3, 1] and len(shots) == 4)
    check("A7 format ujecia dziedziczony z filmu", all(s["fmt"] == "16:9" for s in shots))
    r = c.post(f"/api/scenes/{s1}/shots", json={"title": "x", "action": "a 15 year old boy stands"})
    check("A8 siatka bezpieczenstwa: ujecie z niepelnoletnim -> 400", r.status_code == 400)
    r = c.patch(f"/api/film-shots/{shots[0]['id']}", json={"az": 999, "dist": 99, "duration": 99, "fmt": "4:3"})
    s0 = [s for sc in r.json()["scenes"] for s in sc["shots"]][0]
    check("A9 aktualizacja przycina zakresy", s0["az"] == 180 and s0["dist"] == 8 and s0["duration"] == 20 and s0["fmt"] == "16:9",
          (s0["az"], s0["dist"], s0["duration"], s0["fmt"]))
    c.patch(f"/api/film-shots/{shots[0]['id']}", json={"az": 0, "dist": 4.5, "duration": 5})
    c.post(f"/api/film-shots/{shots[2]['id']}/move", json={"scene_id": s1, "idx": 0})
    order = [s["title"] for s in c.get(f"/api/films/{fid}").json()["scenes"][0]["shots"]]
    check("A10 przeniesienie ujecia na poczatek sceny", order == ["k2", "k0", "k1"], order)
    c.post(f"/api/film-shots/{shots[2]['id']}/move", json={"scene_id": s1, "idx": 2})
    order = [s["title"] for s in c.get(f"/api/films/{fid}").json()["scenes"][0]["shots"]]
    check("A11 przywrocenie kolejnosci", order == ["k0", "k1", "k2"], order)
    check("A12 dwa wyrazy: indeksy ciagle po przenosinach", [s["idx"] for s in db.rows("SELECT idx FROM film_shots WHERE scene_id=? ORDER BY idx", (s1,))] == [0, 1, 2])
    eff = F.effective_shot(F.get_scene(s1), F.get_shot(shots[0]["id"]))
    check("A13 prompt ujecia zawiera miejsce i swiatlo sceny", "mossy sea cliff" in eff["action"] and "soft dawn light" in eff["action"])
    est = c.get(f"/api/films/{fid}").json()["estimate"]
    check("A14 szacunek: 4 obrazy, 4 klipy, 2 kwestie (polska pominieta), podklad", est["images"] == 4 and est["clips"] == 4
          and est["speech"] == 2 and est["bed"] == 1, est)

    # ---------- B. produkcja ----------
    r = c.post(f"/api/films/{fid}/produce")
    check("B1 start produkcji", r.status_code == 200 and r.json()["film"]["status"] == "producing")
    t = wait_status(c, fid, ("ready", "needs_attention"))
    fs_all = [s for sc in t["scenes"] for s in sc["shots"]]
    check("B2 film gotowy", t["film"]["status"] == "ready", (t["film"]["status"], t["film"]["note"]))
    check("B3 kazde ujecie ma obraz i klip", all(s["state"]["image"] and s["state"]["clip"] for s in fs_all),
          [s["state"]["label"] for s in fs_all])
    check("B4 kwestie nagrane (oprocz polskiej)", sum(1 for s in fs_all if s["state"]["speech"]) == 2)
    pol = next(s for s in fs_all if s["title"] == "l0")
    check("B5 polska kwestia: notatka, bez blokowania filmu", "polsk" in (pol["note"] or "") and not pol["state"]["speech"], pol["note"])
    check("B6 podklad wygenerowany", t["film"]["music"] is not None)
    linked = db.rows("SELECT params FROM jobs WHERE role='clip' AND params LIKE '%\"end_artifact_id\": %' AND params NOT LIKE '%\"end_artifact_id\": null%'")
    check("B7 ujecie z link_next dostalo klip start->koniec", len(linked) == 1, len(linked))
    imgs = db.rows("SELECT kind FROM jobs WHERE role='image'")
    check("B8 obrazy przez edycje z kanonem", all(j["kind"] == "edit" for j in imgs) and len(imgs) == 4, [j["kind"] for j in imgs])

    # ---------- C. budzet ----------
    f2 = c.post("/api/films", json={"character_id": cid, "title": "Budzet", "budget_spark": 3, "fmt": "16:9"}).json()["film"]["id"]
    sc2 = c.post(f"/api/films/{f2}/scenes", json={"title": "S", "location": "road"}).json()["scenes"][0]["id"]
    for i in range(3):
        c.post(f"/api/scenes/{sc2}/shots", json={"title": f"b{i}", "action": f"walks {i}"})
    c.post(f"/api/films/{f2}/produce")
    t = wait_status(c, f2, ("paused", "ready"))
    check("C1 budzet 3 Spark -> wstrzymanie z notatka", t["film"]["status"] == "paused" and "budzet" in (t["film"]["note"] or "").lower(),
          (t["film"]["status"], t["film"]["note"]))

    # ---------- D. chwilowy blad (limit) -> przerwa i ponowienie bez zuzycia proby ----------
    prov = state["provider"]
    orig = prov.generate
    calls = {"n": 0}

    def flaky(req, on_remote_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("HTTP 429: rate limit exceeded")
        return orig(req, on_remote_id)
    prov.generate = flaky
    f3 = c.post("/api/films", json={"character_id": cid, "title": "Limit"}).json()["film"]["id"]
    sc3 = c.post(f"/api/films/{f3}/scenes", json={"title": "S"}).json()["scenes"][0]["id"]
    c.post(f"/api/scenes/{sc3}/shots", json={"title": "x", "action": "stands"})
    c.post(f"/api/films/{f3}/produce")
    end = time.time() + 60
    pu = None
    while time.time() < end:
        row = db.one("SELECT paused_until, note FROM films WHERE id=?", (f3,))
        if row["paused_until"]:
            pu = row
            break
        time.sleep(0.3)
    check("D1 blad 429 -> film robi przerwe (paused_until)", pu is not None and "limit" in (pu["note"] or "").lower(), pu and pu["note"])
    retried = db.one("SELECT COUNT(*) n FROM jobs WHERE status='retried'")["n"]
    check("D2 zadanie oznaczone 'retried' (nie liczy sie jako proba)", retried >= 1, retried)
    db.run("UPDATE films SET paused_until=NULL WHERE id=?", (f3,))
    t = wait_status(c, f3, ("ready", "needs_attention"))
    check("D3 po przerwie produkcja konczy sie sukcesem", t["film"]["status"] == "ready", t["film"]["status"])
    prov.generate = orig

    # ---------- E. odrzucenie przez filtr -> 3 proby i ujecie wymaga uwagi ----------
    def reject(req, on_remote_id=None):
        if req.kind in ("image", "edit"):
            raise SafetyRejected("SAFETY_REJECTED (test)")
        return orig(req, on_remote_id)
    prov.generate = reject
    f4 = c.post("/api/films", json={"character_id": cid, "title": "Odrzucenie"}).json()["film"]["id"]
    sc4 = c.post(f"/api/films/{f4}/scenes", json={"title": "S"}).json()["scenes"][0]["id"]
    c.post(f"/api/scenes/{sc4}/shots", json={"title": "x", "action": "stands"})
    c.post(f"/api/films/{f4}/produce")
    t = wait_status(c, f4, ("ready", "needs_attention"))
    sh = t["scenes"][0]["shots"][0]
    nimg = db.one("SELECT COUNT(*) n FROM jobs WHERE film_shot_id=? AND role='image'", (sh["id"],))["n"]
    check("E1 odrzucenie: dokladnie 3 proby, potem 'wymaga uwagi'", t["film"]["status"] == "needs_attention" and sh["failed"] == 1 and nimg == 3,
          (t["film"]["status"], sh["failed"], nimg))
    check("E2 notatka wyjasnia przyczyne", "nieudane" in (sh["note"] or "").lower(), sh["note"])
    prov.generate = orig

    # ---------- F. reczne zadania i reset ----------
    r = c.post(f"/api/film-shots/{sh['id']}/reset", json={"what": "all"})
    check("F1 reset czysci blad", r.status_code == 200 and [s for sc in r.json()["scenes"] for s in sc["shots"]][0]["failed"] == 0)
    check("F1b reset zeruje liczniki prob (stare nieudane -> 'superseded')",
          db.one("SELECT COUNT(*) n FROM jobs WHERE film_shot_id=? AND status='failed'", (sh["id"],))["n"] == 0
          and db.one("SELECT COUNT(*) n FROM jobs WHERE film_shot_id=? AND status='superseded'", (sh["id"],))["n"] == 3)
    check("F2 reset z blednym argumentem -> 400", c.post(f"/api/film-shots/{sh['id']}/reset", json={"what": "zly"}).status_code == 400)
    check("F3 reczny klip bez obrazu -> 400", c.post(f"/api/film-shots/{sh['id']}/generate", json={"role": "clip"}).status_code == 400)
    check("F4 pick obrazu z cudzego ujecia -> 400", c.post(f"/api/film-shots/{sh['id']}/pick", json={"artifact_id": 1}).status_code == 400)
    r = c.delete(f"/api/films/{f4}")
    check("F5 usuniecie filmu", r.status_code == 200 and c.get(f"/api/films/{f4}").status_code == 404)

    # ---------- G. limit okresu probnego H3 (6 klipow/dobe UTC) -> awaryjny zwykly klip ----------
    def h3_limit(req, on_remote_id=None):
        if (req.model or "").startswith("minimax-h3"):
            raise ProviderError("Workflow czeka na uzytkownika: permission_required. You've reached the MiniMax H3 trial limit: "
                                "6 videos per UTC day. Start your paid Unlimited plan to keep creating.")
        return orig(req, on_remote_id)
    prov.generate = h3_limit
    f5 = c.post("/api/films", json={"character_id": cid, "title": "H3"}).json()["film"]["id"]
    sc5 = c.post(f"/api/films/{f5}/scenes", json={"title": "S", "location": "cliff"}).json()["scenes"][0]["id"]
    c.post(f"/api/scenes/{sc5}/shots", json={"title": "a", "action": "stands", "link_next": True})
    c.post(f"/api/scenes/{sc5}/shots", json={"title": "b", "action": "turns"})
    c.post(f"/api/films/{f5}/produce")
    t = wait_status(c, f5, ("ready", "needs_attention"))
    a = [s for sc in t["scenes"] for s in sc["shots"]][0]
    models_used = [j["model"] for j in db.rows("SELECT model FROM jobs WHERE film_shot_id=? AND role='clip'", (a["id"],))]
    check("G1 limit H3: film konczy sie sukcesem mimo limitu", t["film"]["status"] == "ready", (t["film"]["status"], t["film"]["note"]))
    check("G2 ujecie dostalo zwykly klip LTX (no_flf=1) z jawna notatka", a["no_flf"] == 1 and a["state"]["clip"] and "LTX" in (a["note"] or ""),
          (a["no_flf"], a["note"]))
    check("G3 uzyto najpierw H3, potem LTX; proba H3 nie zuzyla limitu prob",
          models_used[0].startswith("minimax-h3") and models_used[-1] == config.VIDEO_MODEL and a["failed"] == 0, models_used)
    r = c.post(f"/api/film-shots/{a['id']}/reset", json={"what": "clip"})
    check("G4 reset przywraca przejscie start->koniec (no_flf=0)", [s for sc in r.json()["scenes"] for s in sc["shots"]][0]["no_flf"] == 0)
    prov.generate = orig

    # ---------- H. inny limit dobowy -> przerwa do resetu (polnoc UTC), bez zuzycia prob ----------
    def daily(req, on_remote_id=None):
        if req.kind in ("image", "edit"):
            raise ProviderError("You've reached the daily trial limit: 40 images per UTC day.")
        return orig(req, on_remote_id)
    prov.generate = daily
    f6 = c.post("/api/films", json={"character_id": cid, "title": "Doba"}).json()["film"]["id"]
    sc6 = c.post(f"/api/films/{f6}/scenes", json={"title": "S"}).json()["scenes"][0]["id"]
    c.post(f"/api/scenes/{sc6}/shots", json={"title": "x", "action": "stands"})
    c.post(f"/api/films/{f6}/produce")
    end = time.time() + 60
    row = None
    while time.time() < end:
        row = db.one("SELECT paused_until, note, status FROM films WHERE id=?", (f6,))
        if row["paused_until"] and row["paused_until"] > time.time() + 3600:
            break
        time.sleep(0.3)
    check("H1 limit dobowy -> przerwa do resetu (> 1 h), film nadal 'producing'",
          row["paused_until"] and row["paused_until"] > time.time() + 3600 and row["status"] == "producing", row["note"])
    check("H2 notatka podaje godzine resetu UTC", "UTC" in (row["note"] or ""), row["note"])
    nfail = db.one("SELECT COUNT(*) n FROM jobs j JOIN film_shots fs ON fs.id=j.film_shot_id WHERE fs.film_id=? AND j.status='failed'", (f6,))["n"]
    check("H3 zadanie oznaczone jako ponowione (nie 'failed')", nfail == 0, nfail)
    prov.generate = orig

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
