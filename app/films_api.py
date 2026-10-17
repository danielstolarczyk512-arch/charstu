"""API filmow: CRUD projektu/scen/ujec, wybor obrazu, zlecanie zadan, sterowanie produkcja, montaz."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import config, db, film as F, pipeline, producer

router = APIRouter()


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (F.FilmError, pipeline.PipelineError) as e:
        raise HTTPException(e.status, str(e))


class FilmIn(BaseModel):
    character_id: int
    title: str
    logline: str = ""
    synopsis: str = ""
    fmt: str = "16:9"
    music_prompt: str = ""
    budget_spark: float | None = None
    image_model: str | None = None
    edit_model: str | None = None


class FilmPatch(BaseModel):
    title: str | None = None
    logline: str | None = None
    synopsis: str | None = None
    fmt: str | None = None
    music_prompt: str | None = None
    budget_spark: float | None = None
    auto_pick: bool | None = None
    allow_spark: bool | None = None
    image_model: str | None = None
    edit_model: str | None = None


class SceneIn(BaseModel):
    title: str = ""
    summary: str = ""
    location: str = ""
    lighting: str = ""
    idx: int | None = None


class ScenePatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    location: str | None = None
    lighting: str | None = None


class ShotIn(BaseModel):
    title: str = ""
    az: float = 0
    el: float = 5
    dist: float = 4.5
    fov: float = 35
    fmt: str | None = None
    action: str = ""
    outfit: str = ""
    dialogue: str = ""
    duration: int = 5
    link_next: bool = False
    note: str = ""
    idx: int | None = None


class MoveIn(BaseModel):
    scene_id: int
    idx: int = 0


class ResetIn(BaseModel):
    what: str = "all"


class PickIn(BaseModel):
    artifact_id: int


class RunIn(BaseModel):
    role: str            # image | clip | speech
    count: int = 1


@router.get("/api/films")
def list_films():
    out = []
    for f in db.rows("SELECT * FROM films ORDER BY id DESC"):
        t = F.film_tree(f["id"])
        out.append({**{k: f[k] for k in ("id", "title", "logline", "character_id", "status", "fmt", "note", "updated")},
                    "progress": t["progress"], "est_seconds": t["est_seconds"]})
    return out


@router.post("/api/films")
def create_film(f: FilmIn):
    fid = _wrap(F.create_film, f.character_id, f.title, f.logline, f.synopsis, f.fmt, f.music_prompt, f.budget_spark,
                f.image_model, f.edit_model)
    return F.film_tree(fid)


@router.get("/api/films/{fid}")
def get_film(fid: int):
    t = _wrap(F.film_tree, fid)
    t["estimate"] = producer.estimate_remaining(fid)
    spent, source = producer.spent_since_start(t["film"])
    t["spent"] = {"spark": round(spent, 1), "source": source}
    return t


@router.patch("/api/films/{fid}")
def patch_film(fid: int, p: FilmPatch):
    _wrap(F.update_film, fid, **p.model_dump(exclude_unset=True))
    return F.film_tree(fid)


@router.delete("/api/films/{fid}")
def delete_film(fid: int):
    _wrap(F.delete_film, fid)
    return {"ok": True}


@router.post("/api/films/{fid}/scenes")
def add_scene(fid: int, s: SceneIn):
    _wrap(F.add_scene, fid, s.title, s.summary, s.location, s.lighting, s.idx)
    return F.film_tree(fid)


@router.patch("/api/scenes/{sid}")
def patch_scene(sid: int, p: ScenePatch):
    sc = _wrap(F.update_scene, sid, **p.model_dump(exclude_unset=True))
    return F.film_tree(sc["film_id"])


@router.delete("/api/scenes/{sid}")
def delete_scene(sid: int):
    sc = _wrap(F.get_scene, sid)
    _wrap(F.delete_scene, sid)
    return F.film_tree(sc["film_id"])


@router.post("/api/scenes/{sid}/shots")
def add_shot(sid: int, s: ShotIn):
    sc = _wrap(F.get_scene, sid)
    data = s.model_dump(exclude={"idx"})
    if data["fmt"] is None:
        data.pop("fmt")
    _wrap(F.add_shot, sid, data, s.idx)
    return F.film_tree(sc["film_id"])


@router.patch("/api/film-shots/{fsid}")
def patch_shot(fsid: int, data: dict):
    fs = _wrap(F.update_shot, fsid, data)
    return F.film_tree(fs["film_id"])


@router.delete("/api/film-shots/{fsid}")
def delete_shot(fsid: int):
    fs = _wrap(F.get_shot, fsid)
    _wrap(F.delete_shot, fsid)
    return F.film_tree(fs["film_id"])


@router.post("/api/film-shots/{fsid}/move")
def move_shot(fsid: int, m: MoveIn):
    fs = _wrap(F.get_shot, fsid)
    _wrap(F.move_shot, fsid, m.scene_id, m.idx)
    return F.film_tree(fs["film_id"])


@router.post("/api/film-shots/{fsid}/reset")
def reset_shot(fsid: int, r: ResetIn):
    fs = _wrap(F.reset_shot, fsid, r.what)
    return F.film_tree(fs["film_id"])


@router.post("/api/film-shots/{fsid}/pick")
def pick_image(fsid: int, p: PickIn):
    fs = _wrap(F.get_shot, fsid)
    ok = db.one("SELECT a.id FROM artifacts a JOIN jobs j ON j.id=a.job_id WHERE a.id=? AND a.kind='image' AND "
                "j.film_shot_id=?", (p.artifact_id, fsid))
    if not ok:
        raise HTTPException(400, "To nie jest obraz tego ujecia")
    db.run("UPDATE film_shots SET image_artifact_id=?, clip_artifact_id=NULL, failed=0 WHERE id=?", (p.artifact_id, fsid))
    return F.film_tree(fs["film_id"])


@router.post("/api/film-shots/{fsid}/generate")
def run_shot(fsid: int, r: RunIn):
    """Reczne zlecenie jednego zadania ujecia (poza automatycznym producentem)."""
    fs = _wrap(F.get_shot, fsid)
    if r.role == "image":
        _wrap(producer.request_image, fsid, max(1, min(r.count, 4)))
    elif r.role == "clip":
        _wrap(producer.request_clip, fsid)
    elif r.role == "speech":
        if not _wrap(producer.request_speech, fsid):
            raise HTTPException(400, "Brak kwestii do nagrania (albo jest po polsku - Qwen3-TTS nie obsluguje polskiego)")
    else:
        raise HTTPException(400, "role: image, clip albo speech")
    return F.film_tree(fs["film_id"])


class PlanIn(BaseModel):
    idea: str
    scenes: int = 4
    shots_per_scene: int = 3
    replace: bool = False


@router.post("/api/films/{fid}/plan")
def plan(fid: int, p: PlanIn):
    """Rezyser AI planuje film w tle (zarys -> sceny -> ujecia). Postep: film.plan_state."""
    from . import director
    _wrap(director.start_plan, producer.provider, fid, p.idea, p.scenes, p.shots_per_scene, p.replace)
    return F.film_tree(fid)


class AssembleIn(BaseModel):
    fade: float = 0.4
    audio_mode: str = "normalize"     # keep | normalize | mute
    bed_db: float = -20.0
    subtitles: str = "sidecar"        # none | sidecar | burn
    allow_partial: bool = False


@router.post("/api/films/{fid}/assemble")
def assemble(fid: int, a: AssembleIn):
    """Montaz filmu w tle. Postep i wynik: film.assemble_state ('assembling' | 'done: {...}' | 'error: ...')."""
    from . import film_assemble
    if a.audio_mode not in ("keep", "normalize", "mute") or a.subtitles not in ("none", "sidecar", "burn"):
        raise HTTPException(400, "audio_mode: keep|normalize|mute; subtitles: none|sidecar|burn")
    _wrap(film_assemble.start_assemble, fid, fade=max(0.0, min(2.0, a.fade)), audio_mode=a.audio_mode,
          bed_db=a.bed_db, subtitles=a.subtitles, allow_partial=a.allow_partial)
    return F.film_tree(fid)


@router.post("/api/films/{fid}/produce")
def produce(fid: int):
    _wrap(producer.start, fid)
    t = F.film_tree(fid)
    t["estimate"] = producer.estimate_remaining(fid)
    return t


@router.post("/api/films/{fid}/pause")
def pause(fid: int):
    _wrap(producer.pause, fid)
    return F.film_tree(fid)
