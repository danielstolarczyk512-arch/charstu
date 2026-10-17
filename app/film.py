"""Film: projekt -> sceny -> ujecia. Model danych, walidacja i stan ujec wyliczany z zadan.

Zasady: bohater jest zawsze postacia fikcyjna i dorosla (kanon w bazie); wszystkie teksty filmu przechodza przez siatke
bezpieczenstwa (slowa wskazujace na postac niepelnoletnia). Stan ujecia nie jest przechowywany - wynika z artefaktow i zadan.
"""
import json

from . import assistant, config, db

FMTS = ("16:9", "9:16")


class FilmError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _text(v, n=1200) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


def safe_texts(*texts: str):
    """Siatka bezpieczenstwa: odrzuca teksty wskazujace na postac niepelnoletnia."""
    if assistant._has_minor(*texts):
        raise FilmError(assistant.REFUSAL)


SHOT_FIELDS = ("title", "az", "el", "dist", "fov", "fmt", "action", "outfit", "dialogue", "duration", "link_next", "note")


def clean_shot(d: dict, base: dict | None = None) -> dict:
    """Normalizuje pola ujecia (zakresy kamery, format, dlugosc klipu 2-20 s)."""
    b = base or {}
    out = {
        "title": _text(d.get("title", b.get("title")), 80),
        "az": _clamp(d.get("az", b.get("az")), -180, 180, 0.0),
        "el": _clamp(d.get("el", b.get("el")), -60, 85, 5.0),
        "dist": _clamp(d.get("dist", b.get("dist")), 1.2, 8, 4.5),
        "fov": _clamp(d.get("fov", b.get("fov")), 20, 80, 35.0),
        "fmt": d.get("fmt", b.get("fmt")) if d.get("fmt", b.get("fmt")) in FMTS else "16:9",
        "action": _text(d.get("action", b.get("action")), 600),
        "outfit": _text(d.get("outfit", b.get("outfit")), 300),
        "dialogue": _text(d.get("dialogue", b.get("dialogue")), 600),
        "duration": int(_clamp(d.get("duration", b.get("duration")), 2, 20, 5)),
        "link_next": 1 if d.get("link_next", b.get("link_next")) else 0,
        "note": _text(d.get("note", b.get("note")), 300),
    }
    safe_texts(out["title"], out["action"], out["outfit"], out["dialogue"], out["note"])
    return out


# ---------------- tworzenie i edycja ----------------
def create_film(character_id: int, title: str, logline: str = "", synopsis: str = "", fmt: str = "16:9",
                music_prompt: str = "", budget_spark: float | None = None, image_model: str | None = None,
                edit_model: str | None = None) -> int:
    if not db.one("SELECT id FROM characters WHERE id=?", (character_id,)):
        raise FilmError("Nie ma takiej postaci", 404)
    if not title.strip():
        raise FilmError("Podaj tytul filmu")
    safe_texts(title, logline, synopsis, music_prompt)
    now = db.now()
    return db.run("INSERT INTO films(title,logline,synopsis,character_id,fmt,music_prompt,budget_spark,image_model,edit_model,"
                  "status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,'draft',?,?)",
                  (_text(title, 120), _text(logline, 400), _text(synopsis, 4000), character_id,
                   fmt if fmt in FMTS else "16:9", _text(music_prompt, 800),
                   config.FILM_BUDGET_SPARK if budget_spark is None else float(budget_spark),
                   image_model or None, edit_model or None, now, now))


def update_film(film_id: int, **f) -> dict:
    film = get_film_row(film_id)
    allowed = {"title": 120, "logline": 400, "synopsis": 4000, "music_prompt": 800}
    sets, args = [], []
    for k, n in allowed.items():
        if k in f and f[k] is not None:
            safe_texts(str(f[k]))
            sets.append(f"{k}=?")
            args.append(_text(f[k], n))
    if f.get("fmt") in FMTS:
        sets.append("fmt=?")
        args.append(f["fmt"])
    if f.get("budget_spark") is not None:
        sets.append("budget_spark=?")
        args.append(max(0.0, float(f["budget_spark"])))
    if f.get("auto_pick") is not None:
        sets.append("auto_pick=?")
        args.append(1 if f["auto_pick"] else 0)
    if f.get("allow_spark") is not None:   # zgoda na zuzycie Premium Spark przy modelach poza planem
        sets.append("allow_spark=?")
        args.append(1 if f["allow_spark"] else 0)
    for k in ("image_model", "edit_model"):
        if k in f:
            sets.append(f"{k}=?")
            args.append((f[k] or "").strip() or None)
    if sets:
        db.run(f"UPDATE films SET {','.join(sets)}, updated=? WHERE id=?", (*args, db.now(), film["id"]))
    return get_film_row(film_id)


def get_film_row(film_id: int) -> dict:
    f = db.one("SELECT * FROM films WHERE id=?", (film_id,))
    if not f:
        raise FilmError("Nie ma takiego filmu", 404)
    return f


def add_scene(film_id: int, title: str = "", summary: str = "", location: str = "", lighting: str = "",
              idx: int | None = None) -> int:
    get_film_row(film_id)
    safe_texts(title, summary, location, lighting)
    n = db.one("SELECT COALESCE(MAX(idx),-1)+1 n FROM scenes WHERE film_id=?", (film_id,))["n"]
    at = n if idx is None else max(0, min(idx, n))
    if at < n:
        db.run("UPDATE scenes SET idx=idx+1 WHERE film_id=? AND idx>=?", (film_id, at))
    return db.run("INSERT INTO scenes(film_id,idx,title,summary,location,lighting,created) VALUES(?,?,?,?,?,?,?)",
                  (film_id, at, _text(title, 120), _text(summary, 800), _text(location, 400), _text(lighting, 300), db.now()))


def get_scene(scene_id: int) -> dict:
    s = db.one("SELECT * FROM scenes WHERE id=?", (scene_id,))
    if not s:
        raise FilmError("Nie ma takiej sceny", 404)
    return s


def update_scene(scene_id: int, **f) -> dict:
    s = get_scene(scene_id)
    lim = {"title": 120, "summary": 800, "location": 400, "lighting": 300}
    sets, args = [], []
    for k, n in lim.items():
        if k in f and f[k] is not None:
            safe_texts(str(f[k]))
            sets.append(f"{k}=?")
            args.append(_text(f[k], n))
    if sets:
        db.run(f"UPDATE scenes SET {','.join(sets)} WHERE id=?", (*args, s["id"]))
    return get_scene(scene_id)


def _detach_jobs(shot_ids: list[int]):
    """SQLite uzywa ponownie numerow usunietych wierszy, wiec zadania usunietych ujec musza przestac na nie wskazywac
    (inaczej nowe ujecie odziedziczyloby historie prob i bledow starego)."""
    if shot_ids:
        db.run(f"UPDATE jobs SET film_shot_id=NULL WHERE film_shot_id IN ({','.join('?' * len(shot_ids))})", tuple(shot_ids))


def delete_scene(scene_id: int):
    s = get_scene(scene_id)
    _detach_jobs([r["id"] for r in db.rows("SELECT id FROM film_shots WHERE scene_id=?", (scene_id,))])
    db.run("DELETE FROM film_shots WHERE scene_id=?", (scene_id,))
    db.run("DELETE FROM scenes WHERE id=?", (scene_id,))
    db.run("UPDATE scenes SET idx=idx-1 WHERE film_id=? AND idx>?", (s["film_id"], s["idx"]))


def add_shot(scene_id: int, data: dict, idx: int | None = None) -> int:
    s = get_scene(scene_id)
    film = get_film_row(s["film_id"])
    d = clean_shot({"fmt": film["fmt"], **data})
    n = db.one("SELECT COALESCE(MAX(idx),-1)+1 n FROM film_shots WHERE scene_id=?", (scene_id,))["n"]
    at = n if idx is None else max(0, min(idx, n))
    if at < n:
        db.run("UPDATE film_shots SET idx=idx+1 WHERE scene_id=? AND idx>=?", (scene_id, at))
    return db.run("INSERT INTO film_shots(film_id,scene_id,idx,title,az,el,dist,fov,fmt,action,outfit,dialogue,duration,"
                  "link_next,note,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (film["id"], scene_id, at, d["title"], d["az"], d["el"], d["dist"], d["fov"], d["fmt"], d["action"],
                   d["outfit"], d["dialogue"], d["duration"], d["link_next"], d["note"], db.now()))


def get_shot(shot_id: int) -> dict:
    s = db.one("SELECT * FROM film_shots WHERE id=?", (shot_id,))
    if not s:
        raise FilmError("Nie ma takiego ujecia", 404)
    return s


def update_shot(shot_id: int, data: dict) -> dict:
    cur = get_shot(shot_id)
    d = clean_shot({k: v for k, v in data.items() if k in SHOT_FIELDS}, base=cur)
    # zmiana opisu/kamery uniewaznia wybrany obraz i klip? NIE - uzytkownik moze chciec zachowac; wymaga jawnego "reset".
    db.run("UPDATE film_shots SET title=?,az=?,el=?,dist=?,fov=?,fmt=?,action=?,outfit=?,dialogue=?,duration=?,link_next=?,"
           "note=? WHERE id=?", (d["title"], d["az"], d["el"], d["dist"], d["fov"], d["fmt"], d["action"], d["outfit"],
                                d["dialogue"], d["duration"], d["link_next"], d["note"], shot_id))
    if data.get("dialogue") is not None and d["dialogue"] != cur["dialogue"]:
        db.run("UPDATE film_shots SET speech_artifact_id=NULL WHERE id=?", (shot_id,))  # nowa kwestia -> nowe nagranie
    return get_shot(shot_id)


def reset_shot(shot_id: int, what: str = "all") -> dict:
    """Zeruje wybor obrazu/klipu/kwestii (np. po zmianie opisu), zeby producent wygenerowal je ponownie."""
    get_shot(shot_id)
    cols = {"image": "image_artifact_id=NULL, clip_artifact_id=NULL, failed=0, no_flf=0",
            "clip": "clip_artifact_id=NULL, failed=0, no_flf=0", "speech": "speech_artifact_id=NULL",
            "all": "image_artifact_id=NULL, clip_artifact_id=NULL, speech_artifact_id=NULL, failed=0, no_flf=0"}
    if what not in cols:
        raise FilmError("reset: image, clip, speech albo all")
    db.run(f"UPDATE film_shots SET {cols[what]} WHERE id=?", (shot_id,))
    # Reset zaczyna od zera: stare nieudane proby przestaja liczyc sie do limitu (status 'superseded').
    roles = {"image": ("image", "clip"), "clip": ("clip",), "speech": ("speech",), "all": ("image", "clip", "speech")}[what]
    db.run(f"UPDATE jobs SET status='superseded' WHERE film_shot_id=? AND status IN ('failed','retried') "
           f"AND role IN ({','.join('?' * len(roles))})", (shot_id, *roles))
    return get_shot(shot_id)


def delete_shot(shot_id: int):
    s = get_shot(shot_id)
    _detach_jobs([shot_id])
    db.run("DELETE FROM film_shots WHERE id=?", (shot_id,))
    db.run("UPDATE film_shots SET idx=idx-1 WHERE scene_id=? AND idx>?", (s["scene_id"], s["idx"]))


def move_shot(shot_id: int, scene_id: int, idx: int):
    s = get_shot(shot_id)
    tgt = get_scene(scene_id)
    if tgt["film_id"] != s["film_id"]:
        raise FilmError("Scena z innego filmu")
    db.run("UPDATE film_shots SET idx=idx-1 WHERE scene_id=? AND idx>?", (s["scene_id"], s["idx"]))
    n = db.one("SELECT COALESCE(MAX(idx),-1)+1 n FROM film_shots WHERE scene_id=? AND id!=?", (scene_id, shot_id))["n"]
    at = max(0, min(idx, n))
    db.run("UPDATE film_shots SET idx=idx+1 WHERE scene_id=? AND idx>=? AND id!=?", (scene_id, at, shot_id))
    db.run("UPDATE film_shots SET scene_id=?, idx=? WHERE id=?", (scene_id, at, shot_id))


def delete_film(film_id: int):
    get_film_row(film_id)
    _detach_jobs([r["id"] for r in db.rows("SELECT id FROM film_shots WHERE film_id=?", (film_id,))] + [-film_id])
    db.run("DELETE FROM film_shots WHERE film_id=?", (film_id,))
    db.run("DELETE FROM scenes WHERE film_id=?", (film_id,))
    db.run("DELETE FROM films WHERE id=?", (film_id,))


# ---------------- odczyt i stan ----------------
def ordered_shots(film_id: int) -> list[dict]:
    return db.rows("SELECT fs.*, sc.idx AS scene_idx FROM film_shots fs JOIN scenes sc ON sc.id=fs.scene_id "
                   "WHERE fs.film_id=? ORDER BY sc.idx, fs.idx", (film_id,))


def effective_shot(scene: dict, fs: dict) -> dict:
    """Ujecie w postaci uzywanej przez prompty: otoczenie i swiatlo sceny + akcja ujecia (spojnosc miejsca w scenie)."""
    parts = [scene.get("location"), scene.get("lighting"), fs.get("action")]
    action = ". ".join(p.strip().rstrip(".") for p in parts if p and p.strip())
    return {"az": fs["az"], "el": fs["el"], "dist": fs["dist"], "fov": fs["fov"], "fmt": fs["fmt"], "action": action,
            "outfit": fs.get("outfit") or ""}


def _art(aid: int | None) -> dict | None:
    if not aid:
        return None
    a = db.one("SELECT id, kind, path, face_score, face_min, label FROM artifacts WHERE id=?", (aid,))
    return a


def job_buckets(fs_id: int) -> dict:
    """Zadania ujecia wg roli: aktywne, nieudane (z podzialem na przejsciowe), ukonczone."""
    out: dict = {}
    for j in db.rows("SELECT id, role, status, error FROM jobs WHERE film_shot_id=? ORDER BY id", (fs_id,)):
        b = out.setdefault(j["role"] or "?", {"active": 0, "failed": 0, "done": 0, "retried": 0, "last_error": None, "ids": []})
        b["ids"].append(j["id"])
        if j["status"] == "retried":     # chwilowy blad (siec/limit) - ponowiony bez zuzycia proby
            b["retried"] += 1
        elif j["status"] in ("queued", "running"):
            b["active"] += 1
        elif j["status"] == "failed":
            b["failed"] += 1
            b["last_error"] = j["error"]
        elif j["status"] == "done":
            b["done"] += 1
    return out


def shot_state(fs: dict) -> dict:
    jobs = job_buckets(fs["id"])
    cands = db.rows("SELECT a.id, a.path, a.face_score FROM artifacts a JOIN jobs j ON j.id=a.job_id "
                    "WHERE j.film_shot_id=? AND j.role='image' AND a.kind='image' ORDER BY a.id", (fs["id"],))
    img, clip = _art(fs["image_artifact_id"]), _art(fs["clip_artifact_id"])
    act = lambda r: jobs.get(r, {}).get("active", 0) > 0  # noqa: E731
    if fs["failed"]:
        label = "błąd"
    elif clip:
        label = "klip gotowy"
    elif act("clip"):
        label = "klip w toku"
    elif img:
        label = "obraz gotowy"
    elif act("image"):
        label = "obraz w toku"
    elif cands:
        label = "wybierz obraz"
    else:
        label = "zaplanowane"
    return {"label": label, "image": img, "clip": clip, "speech": _art(fs["speech_artifact_id"]), "candidates": cands,
            "jobs": jobs}


def film_tree(film_id: int) -> dict:
    film = get_film_row(film_id)
    scenes = db.rows("SELECT * FROM scenes WHERE film_id=? ORDER BY idx", (film_id,))
    shots = db.rows("SELECT * FROM film_shots WHERE film_id=? ORDER BY scene_id, idx", (film_id,))
    by_scene: dict[int, list] = {}
    for fs in shots:
        by_scene.setdefault(fs["scene_id"], []).append({**fs, "state": shot_state(fs)})
    for sc in scenes:
        sc["shots"] = by_scene.get(sc["id"], [])
    allshots = [s for sc in scenes for s in sc["shots"]]
    total = len(allshots)
    prog = {"shots": total, "images": sum(1 for s in allshots if s["state"]["image"]),
            "clips": sum(1 for s in allshots if s["state"]["clip"]),
            "speech_needed": sum(1 for s in allshots if s["dialogue"]),
            "speech_done": sum(1 for s in allshots if s["dialogue"] and s["state"]["speech"]),
            "failed": sum(1 for s in allshots if s["failed"]),
            "bed": bool(film["music_artifact_id"]), "bed_needed": bool(film["music_prompt"])}
    film["music"] = _art(film["music_artifact_id"])
    film["final"] = _art(film["final_artifact_id"])
    return {"film": film, "scenes": scenes, "progress": prog,
            "est_seconds": sum(s["duration"] for s in allshots)}
