"""Duet: dwie osoby w jednym kadrze (odpowiednik film.py dla okna "Duet"). Biblioteka interakcji, minimalny kanon partnera,
ujecia pary i walidacja tekstow.

STATUS WERYFIKACJI (patrz DUET_RAPORT.md): logika (referencje, prompty, baza, endpointy) sprawdzona testami bez modelu
(tests/duet_test.py). Jakosc renderu par, trzymanie dwoch tozsamosci i trafianie w interakcje NIE byly wtedy zmierzone -
wyniki prawdziwych renderow sa wylacznie w DUET_RAPORT.md. Pozycje biblioteki interakcji to opisy tekstowe po angielsku
bez obrazow; obraz ukladu cial dodaje uzytkownik (wylacznie wygenerowany lub rysunek - nie zdjecia prawdziwych osob).
Zasada niezmienna: postacie wylacznie fikcyjne i dorosle (18+); teksty przechodza przez siatke assistant._MINOR.
"""
import io
import re
import time

from . import assistant, config, db, pipeline

INTERACTIONS_DIR = config.DATA / "interactions"
INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)


class DuetError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# Start biblioteki: nazwa, krotki opis po angielsku (ulozenie cial, bez imion - imiona dopisuje uzytkownik w polu opisu).
BUILTIN = [
    ("standing embrace", "both people stand facing each other, arms wrapped around each other's backs, bodies close together"),
    ("kiss", "both people stand close facing each other, lips pressed together in a kiss, one hand resting on the other's cheek"),
    ("spooning", "both people lie on their sides facing the same direction, one behind the other, the person behind has an arm "
                 "wrapped around the other's waist"),
    ("missionary", "one person lies on their back, the other lies on top facing them between their legs, bodies pressed together"),
    ("cowgirl", "one person lies on their back, the other sits astride on top facing them, hands resting on their chest"),
    ("doggy", "one person is on hands and knees, the other kneels behind them holding their hips"),
    ("side by side", "both people lie on their sides facing each other, bodies pressed together, legs intertwined"),
    ("sitting on lap", "one person sits on a chair, the other sits on their lap facing them, arms around the neck"),
    ("against wall", "one person stands with their back against a wall, the other presses close facing them, bodies together"),
    ("oral", "one person stands or sits, the other kneels in front of them with their head lowered between their hips"),
]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:40]


def seed_interactions():
    """Idempotentne zasianie wbudowanych pozycji (nie nadpisuje obrazu ani opisu dodanego przez uzytkownika)."""
    for name, desc in BUILTIN:
        if not db.one("SELECT 1 FROM interactions WHERE slug=?", (slugify(name),)):
            db.run("INSERT INTO interactions(slug,name,description,image_path,builtin,created) VALUES(?,?,?,NULL,1,?)",
                   (slugify(name), name, desc, db.now()))


def safe_texts(*texts: str):
    """Siatka bezpieczenstwa (obejmuje tez partnera i interakcje): teksty wskazujace na postac niepelnoletnia sa odrzucane."""
    if assistant._has_minor(*texts):
        raise DuetError(assistant.REFUSAL)


def list_interactions() -> list[dict]:
    rows = db.rows("SELECT * FROM interactions ORDER BY builtin DESC, id")
    for r in rows:
        r["image_url"] = ("/files/" + r["image_path"]) if r["image_path"] else None
    return rows


def get_interaction(ref) -> dict:
    r = db.one("SELECT * FROM interactions WHERE id=?", (ref,)) if str(ref).isdigit() \
        else db.one("SELECT * FROM interactions WHERE slug=?", (slugify(str(ref)),))
    if not r:
        raise DuetError("Nie ma takiej pozycji w bibliotece interakcji", 404)
    return r


def _save_image(slug: str, data: bytes) -> str:
    """Zapisuje obraz ukladu cial jako PNG w data/interactions i zwraca sciezke wzgledna wobec data/."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001
        raise DuetError("Nie da sie odczytac obrazu (dozwolone: png, jpg, webp)")
    im.thumbnail((1600, 1600))
    rel = f"interactions/{slug}_{int(time.time() * 1000)}.png"
    im.save(config.DATA / rel, "PNG")
    return rel


def add_interaction(name: str, description: str, image: bytes | None = None) -> dict:
    name, description = (name or "").strip()[:60], (description or "").strip()[:300]
    if not name or not description:
        raise DuetError("Podaj nazwe i krotki opis po angielsku")
    safe_texts(name, description)
    slug = slugify(name)
    if not slug:
        raise DuetError("Nazwa musi zawierac litery lub cyfry")
    if db.one("SELECT 1 FROM interactions WHERE slug=?", (slug,)):
        raise DuetError("Pozycja o takiej nazwie juz istnieje", 409)
    rel = _save_image(slug, image) if image else None
    db.run("INSERT INTO interactions(slug,name,description,image_path,builtin,created) VALUES(?,?,?,?,0,?)",
           (slug, name, description, rel, db.now()))
    return get_interaction(slug)


def set_interaction_image(ref, image: bytes) -> dict:
    r = get_interaction(ref)
    db.run("UPDATE interactions SET image_path=? WHERE id=?", (_save_image(r["slug"], image), r["id"]))
    return get_interaction(r["id"])


def delete_interaction(ref):
    r = get_interaction(ref)
    if r["builtin"]:
        db.run("UPDATE interactions SET image_path=NULL WHERE id=?", (r["id"],))   # wbudowanej pozycji nie usuwamy: tylko obraz
        return
    db.run("DELETE FROM interactions WHERE id=?", (r["id"],))


def resolve_pose(interaction_ref=None, pose_artifact_id: int | None = None) -> dict | None:
    """Obraz ukladu cial dla ujecia: z biblioteki interakcji (plik) albo z galerii (artefakt); None = bez obrazu."""
    if interaction_ref:
        r = get_interaction(interaction_ref)
        if r["image_path"]:
            return {"path": r["image_path"]}
    if pose_artifact_id:
        a = db.one("SELECT kind FROM artifacts WHERE id=?", (pose_artifact_id,))
        if not a or a["kind"] != "image":
            raise DuetError("Obraz interakcji musi byc obrazem z galerii")
        return {"artifact_id": pose_artifact_id}
    return None


def character(cid: int) -> dict:
    c = db.one("SELECT * FROM characters WHERE id=?", (cid,))
    if not c:
        raise DuetError("Nie ma takiej postaci", 404)
    return c


def create_pair_shot(a_id: int, b_id: int, data: dict) -> dict:
    """Ujecie pary: wiersz `shots` z partner_id, interakcja i strojami obu osob. Teksty przechodza przez siatke wieku."""
    a, b = character(a_id), character(b_id)
    if a["id"] == b["id"]:
        raise DuetError("Postac A i partner B musza byc roznymi postaciami")
    texts = [data.get(k) or "" for k in ("action", "outfit", "outfit_b", "interaction")]
    safe_texts(*texts, a["name"] or "", b["name"] or "", b["archetype"] or "", b["traits"] or "", b["outfit"] or "")
    fmt = data.get("fmt") if data.get("fmt") in ("16:9", "9:16") else "16:9"
    shot = {"az": float(data.get("az", 0)), "el": float(data.get("el", 5)), "dist": float(data.get("dist", 3.5)),
            "fov": float(data.get("fov", 35)), "fmt": fmt, "action": texts[0][:600], "outfit": texts[1][:300],
            "outfit_b": texts[2][:300], "interaction": texts[3][:600], "partner_id": b["id"]}
    sid = pipeline.new_shot(a["id"], shot, "")
    return db.one("SELECT * FROM shots WHERE id=?", (sid,))


# Minimalny kanon partnera: 2 ujecia (twarz, sylwetka), a nie 8 jak w arkuszu postaci. Tekst bez zaimkow plci.
PARTNER_CANON = [
    ("face", "Twarz", 0, 5, 1.8, "a calm neutral expression, looking at the camera"),
    ("body", "Sylwetka", 0, 5, 5.0, "stands in a relaxed neutral pose, arms at the sides"),
]


def submit_partner_canon(partner: dict, image_model: str | None = None, edit_model: str | None = None,
                         fmt: str = "16:9", allow_spark: bool = False) -> list[dict]:
    """Zleca brakujace obrazy minimalnego kanonu partnera. Bez zadnego kanonu: generowanie z opisu karty (kazdy obraz = inna
    twarz, wiec to tylko kandydaci - zatwierdz ten, ktory ma byc kanonem twarzy, a sylwetke wygeneruj ponownie z niego).
    Z kanonem twarzy: sylwetka powstaje edycja z tej twarzy. Wyniki laduja w galerii z etykieta 'arkusz:<rola>:<nazwa>'."""
    have = {r["role"] for r in db.rows("SELECT role FROM canon_assets WHERE character_id=? AND approved=1", (partner["id"],))}
    out = []
    for role, name, az, el, dist, action in PARTNER_CANON:
        if role in have:
            continue
        use_refs = bool(have)   # jest jakis kanon (np. wgrana twarz) -> edycja z niego
        shot = {"az": az, "el": el, "dist": dist, "fov": 35, "fmt": fmt, "action": action, "outfit": ""}
        sid = pipeline.new_shot(partner["id"], shot, "")
        shot["id"] = sid
        r = pipeline.submit_image(shot, partner, image_model, edit_model, use_refs, 1, label=f"arkusz:{role}:{name}",
                                  allow_spark=allow_spark)
        out.append({"name": name, "role": role, **r})
    return out


def pair_shots(a_id: int | None = None, b_id: int | None = None) -> list[dict]:
    sql, args = "SELECT * FROM shots WHERE partner_id IS NOT NULL", []
    if a_id:
        sql += " AND character_id=?"
        args.append(a_id)
    if b_id:
        sql += " AND partner_id=?"
        args.append(b_id)
    return db.rows(sql + " ORDER BY id DESC LIMIT 100", tuple(args))
