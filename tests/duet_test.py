"""Testy trybu Duet (dwie osoby w kadrze) bez modelu i bez konta: python -m tests.duet_test

Sprawdzaja logike: kolejnosc i budzet referencji, bramke modelu, prompty (role, liczba osob), migracje bazy, endpointy,
siatke wieku na partnerze, film z partnerem, rezysera, dopasowanie twarzy A/B na sztucznych wektorach.
NIE sprawdzaja jakosci renderu - ta jest oceniana wylacznie prawdziwymi renderami (DUET_RAPORT.md)."""
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-duet-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import assistant, config, db, director, duet, guard, models, pipeline, producer, prompts, runner  # noqa: E402
from app import film as F  # noqa: E402
from app.main import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""), flush=True)


def png(col):
    b = io.BytesIO()
    Image.new("RGB", (64, 64), col).save(b, "PNG")
    return b.getvalue()


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except Exception as e:  # noqa: BLE001
        return e


ROOT = Path(__file__).resolve().parent.parent

with TestClient(app) as c:
    def mk(name, kind="lead", **kw):
        j = {"name": name, "archetype": "adult " + name, "traits": f"{name} traits", "outfit": "plain", "style": "cinematic",
             "adult_fictional": True, "kind": kind, **kw}
        r = c.post("/api/characters", json=j)
        assert r.status_code == 200, r.text
        return r.json()

    def canon(cid, col, role="face"):
        r = c.post(f"/api/characters/{cid}/canon", files={"file": ("x.png", png(col), "image/png")}, data={"role": role})
        assert r.status_code == 200, r.text
        return r.json()

    A, B = mk("Mira"), mk("Kael", "partner")
    fa, fb = canon(A["id"], (200, 60, 60)), canon(B["id"], (60, 60, 200))
    canon(A["id"], (210, 70, 70), "body")      # sylwetka NIE moze wejsc do referencji pary (twarz ma priorytet)
    base = {"a_id": A["id"], "b_id": B["id"], "az": 20, "el": 5, "dist": 3.5, "fov": 35, "fmt": "16:9",
            "action": "in a dim bedroom", "outfit": "", "outfit_b": "", "interaction": "Mira sits on Kael's lap facing him"}
    shot = {**base, "id": 1, "partner_id": B["id"]}

    # ---- A. model danych ----
    check("A1 postac ma kind: domyslnie lead, partner zapisany", A["kind"] == "lead" and B["kind"] == "partner")
    cols = lambda t: {r["name"] for r in db.rows(f"PRAGMA table_info({t})")}  # noqa: E731
    check("A2 kolumny Duet w bazie", {"kind"} <= cols("characters") and {"partner_id", "interaction", "outfit_b"} <= cols("shots")
          and {"partner_id", "interaction"} <= cols("films") and {"interaction", "outfit_b"} <= cols("film_shots")
          and {"face_score_b", "face_min_b"} <= cols("artifacts") and "interactions" in
          {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type='table'")})

    # ---- B. kolejnosc i budzet referencji ----
    r3 = pipeline.select_refs_duet(A["id"], B["id"], shot, {"path": "interactions/x.png"}, 3)
    check("B1 [A_twarz, B_twarz] + obraz interakcji = 3 (limit Qwen); -1 = pierwszy wgrany = A",
          r3["ref_ids"] == [fa["id"], fb["id"]] and r3["ref_paths"] == ["interactions/x.png"] and r3["pose_used"], str(r3))
    r2 = pipeline.select_refs_duet(A["id"], B["id"], shot, {"path": "interactions/x.png"}, 2)
    check("B2 limit 2 (Krea/Dark Beast): tylko dwie twarze, obraz interakcji pominiety z ostrzezeniem",
          r2["ref_ids"] == [fa["id"], fb["id"]] and not r2["pose_used"] and not r2["ref_paths"]
          and any("brak slotu na referencję pozy/kąta" in w for w in r2["warnings"]), str(r2["warnings"]))
    check("B3 bez obrazu interakcji: dokladnie dwie referencje, sylwetka A nie wchodzi",
          pipeline.select_refs_duet(A["id"], B["id"], shot, None, 3)["ref_ids"] == [fa["id"], fb["id"]])
    r_art = pipeline.select_refs_duet(A["id"], B["id"], shot, {"artifact_id": 7}, 3)
    check("B4 obraz interakcji z galerii trafia jako ref_artifact_ids", r_art["ref_artifact_ids"] == [7] and r_art["pose_used"])
    C0 = mk("Nocanon", "partner")
    e = raises(pipeline.select_refs_duet, A["id"], C0["id"], shot, None, 3)
    check("B5 brak kanonu twarzy partnera: blad 409 z imieniem", isinstance(e, pipeline.PipelineError) and e.status == 409
          and "Nocanon" in str(e))
    D0 = mk("Dup", "partner")
    c.post(f"/api/characters/{D0['id']}/canon", files={"file": ("x.png", png((200, 60, 60)), "image/png")}, data={"role": "face"})
    e = raises(pipeline.select_refs_duet, A["id"], D0["id"], shot, None, 3)
    check("B6 ten sam obraz kanonu A i B: blad", isinstance(e, pipeline.PipelineError) and "ten sam obraz" in str(e))
    # kolejnosc faktycznie trafia do zadania i do GenRequest (runner): [A, B, uklad]
    pa = c.post("/api/duet/interactions", data={"name": "test pose", "description": "both people stand side by side"},
                files={"file": ("p.png", png((10, 200, 10)), "image/png")}).json()
    shid = c.post("/api/duet/shots", json=base).json()["id"]
    g = c.post(f"/api/duet/shots/{shid}/generate", json={"count": 2, "interaction_id": pa["slug"]}).json()
    job = db.one("SELECT * FROM jobs WHERE id=?", (g["jobs"][0],))
    req = runner.Runner.build_request(None, job)
    p = json.loads(job["params"])
    check("B7 job: ref_ids [A,B], ref_paths [uklad]; GenRequest.refs = [A, B, uklad] w tej kolejnosci",
          p["ref_ids"] == [fa["id"], fb["id"]] and len(p["ref_paths"]) == 1 and len(req.refs) == 3
          and req.refs[0].name == Path(fa["path"]).name and req.refs[1].name == Path(fb["path"]).name
          and req.refs[2].parent.name == "interactions", str([r.name for r in req.refs]))
    check("B8 2 warianty = 2 zadania edit modelu domyslnego (PARTNER_MODEL=qwen)", len(g["jobs"]) == 2 and job["model"] == "qwen"
          and job["kind"] == "edit" and g["pose"] is True and p["duet"] is True)

    # ---- C. bramka modelu ----
    e = raises(pipeline.plan_image_duet, A, B, shot, "qwen-2512")
    check("C1 model tylko-do-generowania odrzucony", isinstance(e, pipeline.PipelineError) and "nie jest modelem edycji" in str(e))
    e = raises(pipeline.plan_image_duet, A, B, shot, "ltx25")
    check("C2 model wideo odrzucony", isinstance(e, pipeline.PipelineError))
    models.PROFILES["test-edit-1"] = models.Profile("test-edit-1", "Test 1 ref", "edit", "delta", max_refs=1, kind="edit",
                                                    covered=True, category="Edycja z kanonem")
    e = raises(pipeline.plan_image_duet, A, B, shot, "test-edit-1")
    del models.PROFILES["test-edit-1"]
    check("C3 edycja z max_refs=1 odrzucona: wymaga max_refs >= 2", isinstance(e, pipeline.PipelineError) and "max_refs >= 2" in str(e))
    m_q = pipeline.plan_image_duet(A, B, shot, "qwen", {"path": "interactions/x.png"})
    m_k = pipeline.plan_image_duet(A, B, shot, "krea-identity-edit", {"path": "interactions/x.png"})
    m_d = pipeline.plan_image_duet(A, B, shot, "dark-beast-krea2-identity-edit")
    check("C4 Qwen (3 ref): bez ostrzezenia o slocie, obraz interakcji uzyty", not m_q[4] and m_q[2]["pose_used"])
    check("C5 Krea i Dark Beast Identity Edit (2 ref): ostrzezenie 'brak slotu na referencję pozy/kąta'",
          any("brak slotu na referencję pozy/kąta" in w.lower() for w in m_k[4]) and any("brak slotu" in w.lower() for w in m_d[4])
          and not m_k[2]["pose_used"])
    m_def = pipeline.plan_image_duet(A, B, shot, None)
    check("C6 bez podanego modelu: PARTNER_MODEL z konfiguracji", m_def[0] == config.PARTNER_MODEL == "qwen")
    e = raises(pipeline.plan_image_duet, A, A, shot, "qwen")
    check("C7 A i B musza byc rozne", isinstance(e, pipeline.PipelineError))
    e = raises(pipeline.plan_image_duet, A, B, shot, "gpt-image-2")
    check("C8 edycja poza planem: gate modelu odrzuca (to model generowania)", isinstance(e, pipeline.PipelineError))

    # ---- D. prompty ----
    pr = m_q[1]
    low = pr.lower()
    check("D1 'Exactly two people' jest, 'only one person' nie ma", "Exactly two people are visible: Mira and Kael." in pr
          and "only one person" not in low)
    check("D2 role zwiazane z numerem referencji i imieniem",
          "first reference image shows Mira" in pr and "second reference image shows Kael" in pr
          and "third reference image shows only the arrangement of the two bodies" in pr)
    check("D3 partner nigdy 'the character'; brak zaimkow plci", "the character" not in low and " her " not in low and " his " not in low
          and "she " not in low and " he " not in low.replace("the ", " "))
    check("D4 kto co robi: interakcja z imionami w prompcie", "Mira sits on Kael's lap facing him" in pr)
    p_out = prompts.duet_prompt(A, B, {**shot, "outfit_b": "fully nude"}, 2)
    check("D5 strój pusty = jak w referencji; 'fully nude' bez 'wearing'", "Mira keeps the outfit from the first reference image" in p_out
          and "Kael is fully nude." in p_out and "wearing fully nude" not in p_out)
    p_posed = prompts.duet_prompt(A, B, shot, 3, pose_ref=True)
    check("D5b z obrazem ukladu: strój z karty slowami (przeciek ubran z obrazu pozy), bez zdania 'keeps the outfit'",
          "Mira wears plain as in the first reference image, not the clothes of the people in the third reference image" in p_posed
          and "keeps the outfit" not in p_posed)
    p_nopose = prompts.duet_prompt(A, B, shot, 2, pose_ref=False)
    check("D6 bez obrazu interakcji brak zdania o 3. obrazie", "third reference" not in p_nopose)
    same = prompts.duet_prompt({"name": "aa"}, {"name": "aa"}, shot, 2)
    check("D7 te same imiona: etykiety rozne", "aa (first reference)" in same and "aa (second reference)" in same)
    vp = prompts.video_prompt(A, shot, B, shot["interaction"])
    check("D8 klip pary: liczba mnoga, obie osoby, niezmienny strój wymuszony gdy interakcja go nie zmienia",
          "Mira and Kael" in vp and "both people keep their own faces, hairstyles and outfits" in vp and "the character" not in vp.lower())
    vp2 = prompts.video_prompt(A, shot, B, "Mira slowly undresses Kael")
    check("D9 interakcja o zmianie ubrania: brak wymuszania stroju", "faces and hairstyles throughout" in vp2 and "outfits" not in vp2)
    check("D10 bez partnera video_prompt dziala jak dawniej ('The character', jeden strój)",
          "The character" in prompts.video_prompt(A, {**shot, "action": "stands"}) and "keeps the same face" in prompts.video_prompt(A, shot))

    # ---- E. migracja bazy (idempotentna, bez utraty danych) ----
    tmp = tempfile.mkdtemp(prefix="studio-mig-")
    con = sqlite3.connect(Path(tmp) / "studio.db")
    con.executescript("""
      CREATE TABLE characters(id INTEGER PRIMARY KEY, name TEXT NOT NULL, archetype TEXT, traits TEXT, outfit TEXT, style TEXT,
                              adult_fictional INTEGER NOT NULL, created REAL);
      CREATE TABLE shots(id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL, az REAL, el REAL, dist REAL, fov REAL, fmt TEXT,
                         action TEXT, prompt TEXT, created REAL);
      CREATE TABLE films(id INTEGER PRIMARY KEY, title TEXT NOT NULL, character_id INTEGER NOT NULL, created REAL, updated REAL);
      CREATE TABLE film_shots(id INTEGER PRIMARY KEY, film_id INTEGER NOT NULL, scene_id INTEGER NOT NULL, idx INTEGER NOT NULL);
      INSERT INTO characters VALUES(1,'Stara','adult x','t','o','s',1,1.0);
      INSERT INTO shots(id,character_id,az,action) VALUES(5,1,10,'old action');
      INSERT INTO films(id,title,character_id) VALUES(3,'Stary film',1);
    """)
    con.commit()
    con.close()
    code = ("import os;os.environ['STUDIO_DATA']=%r;os.environ['PROVIDER']='mock';"
            "import app.db as d;print(d.one('SELECT kind FROM characters WHERE id=1')['kind'], d.one('SELECT interaction,partner_id "
            "FROM shots WHERE id=5')['interaction']==\"\", d.one('SELECT title FROM films WHERE id=3')['title'])") % tmp
    out1 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    out2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)   # drugi raz: idempotentnie
    check("E1 migracja starej bazy: dane zostaja, kind='lead', interaction='' (dwa uruchomienia bez bledu)",
          out1.returncode == 0 and out2.returncode == 0 and out1.stdout.strip() == "lead True Stary film"
          and out1.stdout == out2.stdout, (out1.stdout + out1.stderr + out2.stderr)[-300:])

    # ---- F. endpointy API ----
    lib = c.get("/api/duet/interactions").json()
    names = {x["name"] for x in lib}
    want = {"standing embrace", "kiss", "spooning", "missionary", "cowgirl", "doggy", "side by side", "sitting on lap",
            "against wall", "oral"}
    check("F1 biblioteka interakcji: min. 10 wbudowanych pozycji z opisami po angielsku", want <= names
          and all(x["description"] for x in lib if x["builtin"]) and (config.DATA / "interactions").is_dir())
    seed_again = duet.seed_interactions()
    check("F2 zasianie idempotentne (brak duplikatow)", len(c.get("/api/duet/interactions").json()) == len(lib))
    check("F3 wlasna pozycja z obrazem: plik w data/interactions", pa["image_path"].startswith("interactions/")
          and (config.DATA / pa["image_path"]).is_file() and pa["builtin"] == 0)
    r = c.post("/api/duet/interactions", data={"name": "test pose", "description": "dup"})
    check("F4 duplikat nazwy: 409", r.status_code == 409)
    r = c.post("/api/duet/interactions", data={"name": "x", "description": "a teen girl and a man"})
    check("F5 siatka wieku obejmuje interakcje", r.status_code == 400)
    r = c.delete("/api/duet/interactions/kiss")
    check("F6 wbudowanej pozycji nie usuwa sie (tylko obraz)", r.status_code == 200 and any(x["slug"] == "kiss"
          for x in c.get("/api/duet/interactions").json()))
    r = c.delete(f"/api/duet/interactions/{pa['slug']}")
    check("F7 wlasna pozycja usunieta", r.status_code == 200 and not any(x["slug"] == pa["slug"] for x in c.get("/api/duet/interactions").json()))
    pl = c.post("/api/duet/plan", json={**base, "edit_model": "krea-identity-edit"}).json()
    check("F8 /api/duet/plan: prompt, kolejnosc, ostrzezenie slotu, covered, prompt klipu",
          "Exactly two people" in pl["prompt"] and pl["refs"] == [fa["id"], fb["id"]] and pl["covered"] is True
          and any("brak slotu" in w.lower() for w in pl["warnings"]) and "Mira and Kael" in pl["video_prompt"])
    r = c.post("/api/duet/plan", json={**base, "edit_model": "z-turbo"})
    check("F9 /api/duet/plan na modelu generowania: 400", r.status_code == 400)
    r = c.post("/api/duet/plan", json={**base, "interaction": "two teens kiss"})
    check("F10 /api/duet/plan: siatka wieku na interakcji", r.status_code == 400)
    r = c.post("/api/duet/shots", json={**base, "outfit_b": "child costume"})
    check("F11 /api/duet/shots: siatka wieku na stroju partnera", r.status_code == 400)
    r = c.post("/api/characters", json={"name": "X", "archetype": "teenage girl", "adult_fictional": True, "kind": "partner"})
    check("F12 siatka wieku obejmuje partnera przy tworzeniu", r.status_code == 400)
    sh = c.get(f"/api/duet/shots?a={A['id']}&b={B['id']}").json()
    check("F13 lista ujec pary", sh and all(x["partner_id"] == B["id"] for x in sh))
    over = c.post(f"/api/duet/shots/{shid}/generate", json={"count": 4})
    check("F14 limit prob na ujecie (MAX_ATTEMPTS_PER_SHOT) respektowany", over.status_code in (200, 409))
    r = c.delete(f"/api/characters/{B['id']}")
    check("F15 partnera uzywanego w ujeciach nie mozna usunac (409): SQLite uzywa ponownie numerow", r.status_code == 409)

    # klip z ujecia pary (mock): prompt w liczbie mnogiej; proporcje startu i konca sprawdza check_flf
    import time
    for _ in range(60):
        arts = c.get(f"/api/duet/artifacts?a={A['id']}&b={B['id']}").json()
        if len(arts) >= 2:
            break
        time.sleep(0.5)
    check("F16 wyniki pary widoczne w /api/duet/artifacts", len(arts) >= 2 and "face_score_b" in arts[0])
    vsh = c.post("/api/duet/shots", json=base).json()["id"]   # osobne ujecie: limit prob shid zuzyty w F14
    v = c.post(f"/api/duet/shots/{vsh}/video", json={"source_artifact_id": arts[0]["id"]})
    vj = db.one("SELECT params FROM jobs WHERE id=?", (v.json()["jobs"][0],))
    check("F17 klip z ujecia pary: prompt pary (liczba mnoga)", v.status_code == 200
          and "Mira and Kael" in json.loads(vj["params"])["prompt"] and "both people" in json.loads(vj["params"])["prompt"])
    v2 = c.post(f"/api/duet/shots/{vsh}/video", json={"source_artifact_id": arts[0]["id"], "end_artifact_id": arts[1]["id"]})
    check("F18 klip start->koniec dla pary (te same proporcje)", v2.status_code == 200)
    r = c.post("/api/duet/partner-canon", json={"partner_id": C0["id"]})
    check("F19 minimalny kanon partnera: 2 ujecia (twarz, sylwetka)", r.status_code == 200 and len(r.json()["items"]) == 2
          and {i["role"] for i in r.json()["items"]} == {"face", "body"}, r.text[:200])
    r = c.post("/api/duet/partner-canon", json={"partner_id": B["id"]})
    check("F20 partner z kanonem twarzy: brakuje tylko sylwetki (1 ujecie, z referencja)", r.status_code == 200
          and [i["role"] for i in r.json()["items"]] == ["body"])

    # ---- G. siatka _MINOR na partnerze, film, rezyser ----
    check("G1 _has_minor lapie postac partnera w tekstach ujecia", assistant._has_minor("Kael, a teenage knight"))
    e = raises(F.create_film, A["id"], "Film", "", "", "16:9", "", None, None, None, B["id"], "two kids hug")
    check("G2 film z partnerem: interakcja przechodzi siatke wieku", isinstance(e, F.FilmError))
    fid = F.create_film(A["id"], "Duet film", partner_id=B["id"], interaction="Mira and Kael embrace")
    film = F.get_film_row(fid)
    check("G3 film ma partner_id i interakcje", film["partner_id"] == B["id"] and film["interaction"].startswith("Mira"))
    e = raises(F.create_film, A["id"], "X", partner_id=A["id"])
    check("G4 film: partner rozny od bohatera", isinstance(e, F.FilmError))
    sc = F.add_scene(fid, "S1", "", "a room", "warm light")
    fs = F.add_shot(sc, {"action": "they dance", "interaction": "", "outfit_b": "a white shirt", "duration": 12})
    check("G5 ujecie filmu niesie outfit_b i interakcje (puste -> z filmu)", F.get_shot(fs)["outfit_b"] == "a white shirt"
          and F.effective_shot(F.get_scene(sc), F.get_shot(fs), film)["interaction"] == "Mira and Kael embrace"
          and F.effective_shot(F.get_scene(sc), F.get_shot(fs), film)["partner_id"] == B["id"])
    e = raises(F.add_shot, sc, {"action": "x", "interaction": "teens hug"})
    check("G6 siatka wieku na interakcji ujecia filmu", isinstance(e, F.FilmError))
    res = producer.request_image(fs, 2)
    jb = db.one("SELECT * FROM jobs WHERE id=?", (res["jobs"][0],))
    jp = json.loads(jb["params"])
    check("G7 producent: ujecie filmu z partnerem idzie sciezka Duet (refs A,B, prompt pary)",
          jp.get("duet") and jp["ref_ids"] == [fa["id"], fb["id"]] and "Exactly two people" in jp["prompt"]
          and "Kael is wearing a white shirt" in jp["prompt"], jp["prompt"][:120])
    clip_shot = db.one("SELECT * FROM shots WHERE id=?", (jb["shot_id"],))
    check("G8 wiersz shots z filmu ma partnera i interakcje (klip dostanie prompt pary)", clip_shot["partner_id"] == B["id"]
          and clip_shot["interaction"] == "Mira and Kael embrace")

    def fake_chat(provider, msgs, timeout=70, attempts=2):
        return {"shots": [{"title": "t", "az": 0, "el": 5, "dist": 2.0, "fov": 35, "action": "they kiss", "interaction": "Mira kisses Kael",
                           "outfit": "", "outfit_b": "", "dialogue": "", "duration": 14, "link_next": False}]}, ""
    real = assistant.chat_json
    assistant.chat_json = fake_chat
    outline = {"title": "T", "synopsis": "s", "scenes": [{"title": "s", "summary": "x", "location": "room", "lighting": "dim"}]}
    d_duet = director.plan_scene(None, {**film}, A, outline, 0, 1, partner=B)
    d_solo = director.plan_scene(None, {**film}, A, outline, 0, 1)
    assistant.chat_json = real
    check("G9 rezyser: z partnerem czas do 15 s (14 zostaje), bez partnera nadal do 8 s",
          d_duet[0]["duration"] == 14 and d_solo[0]["duration"] == 8)
    check("G10 rezyser przenosi interakcje i strój B do ujecia", d_duet[0]["interaction"] == "Mira kisses Kael")
    check("G11 prompt rezysera z partnerem zawiera zasady Duet (dwie osoby, 4-15 s)", "DWIE osoby" in director.DUET_RULES
          and "4-15" in director.DUET_RULES)

    # ---- H. dopasowanie twarzy A/B (guard) ----
    ea, eb = [1.0, 0, 0], [0, 1.0, 0]
    near_a, near_b, near_a2 = [0.9, 0.1, 0], [0.1, 0.9, 0], [0.8, 0.5, 0]
    m = guard.match_faces([near_a, near_b], ea, eb)
    check("H1 dwie twarze: kazda do bliższego kanonu, dwie liczby", m["a"] > 0.8 and m["b"] > 0.8 and m["faces"] == 2, str(m))
    m = guard.match_faces([near_b, near_a], ea, eb)
    check("H2 kolejnosc wykrytych twarzy nie ma znaczenia", m["a"] > 0.8 and m["b"] > 0.8)
    m = guard.match_faces([near_a], ea, eb)
    check("H3 jedna twarz: dostaje blizszy kanon, drugi None", m["a"] is not None and m["b"] is None and m["faces"] == 1)
    m = guard.match_faces([near_a, near_a2], ea, eb)
    check("H4 dwie twarze podobne do A: rozlaczne przypisanie (obie liczby, jedna twarz do jednej osoby)",
          m["a"] is not None and m["b"] is not None and m["faces"] == 2)
    m = guard.match_faces([], ea, eb)
    check("H5 brak twarzy (np. widok z tylu): None/None", m["a"] is None and m["b"] is None and m["faces"] == 0)
    # zapis dwoch liczb w bazie dla artefaktu pary
    art = arts[0]
    real_av, real_sim, real_fg = guard.available, guard.similarity_duet, config.FACE_GUARD
    guard.available = lambda: True
    guard.similarity_duet = lambda path, ca, cb: {"a": 0.41, "b": 0.33, "faces": 2}
    config.FACE_GUARD = True
    res = runner.measure_artifact(art["id"])
    row = db.one("SELECT face_score, face_score_b FROM artifacts WHERE id=?", (art["id"],))
    check("H6 pomiar pary zapisuje dwie liczby (A i B osobno)", res and abs(row["face_score"] - 0.41) < 1e-9
          and abs(row["face_score_b"] - 0.33) < 1e-9, str(row))
    guard.available, guard.similarity_duet, config.FACE_GUARD = real_av, real_sim, real_fg

    # ---- J. etap E5: ref_slot_b, naga sylwetka w kanonie, frame_guard, anatomia, migracja ----
    r_pf = pipeline.select_refs_duet(A["id"], B["id"], shot, None, 3, "partner_face")
    check("J1 ref_slot_b=partner_face (domyslne): [A_twarz, B_twarz] jak dotad", r_pf["ref_ids"] == [fa["id"], fb["id"]]
          and r_pf["slot_b"] == "partner_face")
    r_fb = pipeline.select_refs_duet(A["id"], B["id"], shot, None, 3, "lead_body")
    check("J2 lead_body bez body_nude: cofniecie do partner_face z ostrzezeniem",
          r_fb["ref_ids"] == [fa["id"], fb["id"]] and r_fb["slot_b"] == "partner_face"
          and any("body_nude" in w for w in r_fb["warnings"]), str(r_fb["warnings"]))
    nb = canon(A["id"], (90, 90, 90), "body_nude")
    r_lb = pipeline.select_refs_duet(A["id"], B["id"], shot, {"path": "interactions/x.png"}, 3, "lead_body")
    check("J3 lead_body z body_nude: [A_twarz, A_naga_sylwetka] + uklad; twarz B nie zajmuje slotu",
          r_lb["ref_ids"] == [fa["id"], nb["id"]] and r_lb["slot_b"] == "lead_body" and r_lb["ref_paths"] == ["interactions/x.png"]
          and not r_lb["warnings"])
    r_lb2 = pipeline.select_refs_duet(A["id"], C0["id"], shot, None, 2, "lead_body")
    check("J4 lead_body: partner bez kanonu twarzy nie blokuje (opisany slowami), limit 2 = dwie referencje A",
          r_lb2["ref_ids"] == [fa["id"], nb["id"]])
    e = raises(pipeline.select_refs_duet, A["id"], B["id"], shot, None, 3, "partner_face")
    check("J5 partner_face po dodaniu body_nude nadal tylko twarze (sylwetki nie wchodza)",
          e is None and pipeline.select_refs_duet(A["id"], B["id"], shot, None, 3)["ref_ids"] == [fa["id"], fb["id"]])
    p_lb = prompts.duet_prompt(A, B, shot, 2, slot_b="lead_body")
    check("J6 prompt lead_body: 2. obraz = cialo A, partner opisany slowami i nie znika z promptu",
          "second reference image shows Mira's body" in p_lb and "Kael has no reference image" in p_lb
          and "Kael traits" not in p_lb or "Kael has no reference image" in p_lb)
    check("J7 prompt lead_body nie przypisuje B zadnej referencji ('second reference image shows Kael')",
          "second reference image shows Kael" not in p_lb and "Exactly two people are visible: Mira and Kael." in p_lb)
    gd = prompts.frame_guard()
    pp = prompts.duet_prompt(A, B, shot, 2)
    vv = prompts.video_prompt(A, shot, B, "Mira and Kael stand together")
    check("J8 frame_guard w prompcie obrazu i klipu pary: 'nobody else', 'Two pairs of legs', 'not merged'",
          all(x in pp and x in vv for x in ("nobody else", "Two pairs of legs", "not merged")) and gd in pp and gd in vv)
    solo = prompts.image_prompt(A, {**shot, "outfit": ""}, with_refs=True, style="delta") + prompts.video_prompt(A, shot)
    check("J9 frame_guard nie wystepuje w promptach jednej postaci", "nobody else" not in solo and "pairs of legs" not in solo)
    anat = "Their hands are joined and their foreheads touch."
    pa2 = prompts.duet_prompt(A, B, shot, 2, interaction="Mira smiles at Kael", anatomy=anat)
    check("J10 anatomy doklejona po opisie interakcji", pa2.index("Mira smiles at Kael") < pa2.index(anat))
    lib2 = {x["slug"]: x for x in c.get("/api/duet/interactions").json()}
    check("J11 kolumna anatomy: pozycje bez scen jednoznacznie seksualnych maja fraze, pozostale puste do wypelnienia w UI",
          all(lib2[s]["anatomy"] for s in ("standing-embrace", "kiss", "side-by-side", "sitting-on-lap", "against-wall"))
          and all(lib2[s]["anatomy"] == "" for s in ("spooning", "missionary", "cowgirl", "doggy", "oral")))
    pr = c.patch("/api/duet/interactions/spooning", json={"anatomy": anat})
    check("J12 anatomia edytowalna przez API (PATCH) i zapisana", pr.status_code == 200 and pr.json()["anatomy"] == anat)
    duet.seed_interactions()
    check("J13 ponowny zasiew nie nadpisuje frazy wpisanej przez uzytkownika",
          {x["slug"]: x for x in c.get("/api/duet/interactions").json()}["spooning"]["anatomy"] == anat)
    pr = c.patch("/api/duet/interactions/spooning", json={"anatomy": "two teens"})
    check("J14 siatka wieku obejmuje anatomie", pr.status_code == 400)
    own = c.post("/api/duet/interactions", data={"name": "wlasna poza", "description": "two adults stand apart", "anatomy": anat})
    check("J15 wlasna pozycja z anatomia (pole w formularzu)", own.status_code == 200 and own.json()["anatomy"] == anat)
    plj = c.post("/api/duet/plan", json={**base, "interaction_id": "kiss", "ref_slot_b": "lead_body"}).json()
    check("J16 /api/duet/plan: anatomia pozycji w prompcie, slot_b, cofniecie przy braku body_nude u A (A ma body_nude: lead_body)",
          lib2["kiss"]["anatomy"] in plj["prompt"] and plj["slot_b"] == "lead_body" and plj["refs"] == [fa["id"], nb["id"]])
    shs = c.post("/api/duet/shots", json={**base, "ref_slot_b": "lead_body"}).json()
    sh0 = c.post("/api/duet/shots", json=base).json()
    check("J17 ujecie zapamietuje ref_slot_b; domyslnie partner_face", shs["ref_slot_b"] == "lead_body" and sh0["ref_slot_b"] == "partner_face")
    gg = c.post(f"/api/duet/shots/{shs['id']}/generate", json={"count": 1, "interaction_id": "kiss"}).json()
    jp = json.loads(db.one("SELECT params FROM jobs WHERE id=?", (gg["jobs"][0],))["params"])
    check("J18 generate bierze slot z ujecia; job: refs [A_twarz, A_naga_sylwetka], prompt z anatomia",
          jp["ref_ids"] == [fa["id"], nb["id"]] and gg["slot_b"] == "lead_body" and lib2["kiss"]["anatomy"] in jp["prompt"])
    check("J19 /api/coverage zna role body_nude", c.get(f"/api/coverage?character_id={A['id']}").json().get("body_nude") is True
          and c.get(f"/api/coverage?character_id={B['id']}").json().get("body_nude") is False)

    # migracja ref_slot_b i anatomy: stara baza bez tych kolumn
    tmp2 = tempfile.mkdtemp(prefix="studio-mig2-")
    con = sqlite3.connect(Path(tmp2) / "studio.db")
    con.executescript("""
      CREATE TABLE characters(id INTEGER PRIMARY KEY, name TEXT NOT NULL, archetype TEXT, traits TEXT, outfit TEXT, style TEXT,
                              adult_fictional INTEGER NOT NULL, created REAL);
      CREATE TABLE shots(id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL, az REAL, el REAL, dist REAL, fov REAL, fmt TEXT,
                         action TEXT, prompt TEXT, created REAL, partner_id INTEGER, interaction TEXT, outfit_b TEXT);
      CREATE TABLE interactions(id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL,
                                image_path TEXT, builtin INTEGER DEFAULT 0, created REAL);
      INSERT INTO characters VALUES(1,'S','adult x','t','o','s',1,1.0);
      INSERT INTO shots(id,character_id,partner_id,interaction) VALUES(7,1,2,'old');
      INSERT INTO interactions(slug,name,description,builtin) VALUES('kiss','kiss','d',1);
    """)
    con.commit()
    con.close()
    code2 = ("import os;os.environ['STUDIO_DATA']=%r;os.environ['PROVIDER']='mock';import app.db as d;"
             "s=d.one('SELECT ref_slot_b,interaction FROM shots WHERE id=7');i=d.one('SELECT anatomy FROM interactions');"
             "print(s['ref_slot_b'],s['interaction'],repr(i['anatomy']))") % tmp2
    o1 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, cwd=ROOT)
    o2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, cwd=ROOT)
    check("J20 migracja: istniejace ujecie dostaje ref_slot_b='partner_face' (zachowuje sie jak dotad), anatomy='' ; powtorka bez bledu",
          o1.returncode == 0 and o2.returncode == 0 and o1.stdout.strip() == "partner_face old ''" and o1.stdout == o2.stdout,
          (o1.stdout + o1.stderr + o2.stderr)[-300:])

    # ---- I. sciezka jednej postaci bez zmian ----
    sg = c.post("/api/shots", json={"character_id": A["id"], "az": 40, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9",
                                    "action": "stands", "outfit": ""})
    check("I1 jedna postac: ujecie nadal bez partnera", sg.status_code == 200 and sg.json().get("partner_id") is None)
    pj = c.post("/api/preview", json={"character_id": A["id"], "az": 40, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9",
                                      "action": "stands", "outfit": "", "use_refs": True, "edit_model": "qwen"}).json()
    check("I2 jedna postac: prompt z 'Only one person is visible in the frame.'", "Only one person is visible in the frame." in pj["image_prompt"]
          and "Exactly two" not in pj["image_prompt"])

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
