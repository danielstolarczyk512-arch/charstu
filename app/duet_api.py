"""API okna "Duet" (odpowiednik films_api.py): biblioteka interakcji, minimalny kanon partnera, ujecia i generowanie par,
klipy z ujecia pary. Sklejka i pomiar korzystaja z istniejacych /api/stitch i /api/artifacts/{id}/measure.
NIE TESTOWANE prawdziwym renderem do czasu weryfikacji opisanej w DUET_RAPORT.md (testy bez modelu: tests/duet_test.py)."""
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import config, db, duet, models, pipeline, prompts

router = APIRouter()


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (duet.DuetError, pipeline.PipelineError) as e:
        raise HTTPException(e.status, str(e))


class PairShotIn(BaseModel):
    a_id: int
    b_id: int
    az: float = 0
    el: float = 5
    dist: float = 3.5
    fov: float = 35
    fmt: str = "16:9"
    action: str = ""
    outfit: str = ""          # strój A (puste = jak w kanonie)
    outfit_b: str = ""        # strój B (puste = jak w kanonie)
    interaction: str = ""     # opis interakcji po angielsku (idzie do promptu)


class PlanIn(PairShotIn):
    edit_model: str | None = None
    interaction_id: str | None = None      # pozycja biblioteki (id albo slug)
    pose_artifact_id: int | None = None


class GenIn(BaseModel):
    count: int = 2                         # 2-4 warianty: trafienia w scenach par sa rzadkie
    edit_model: str | None = None
    interaction_id: str | None = None
    pose_artifact_id: int | None = None
    interaction: str | None = None         # nadpisuje opis zapisany w ujeciu
    outfit: str | None = None
    outfit_b: str | None = None
    allow_spark: bool = False


class VideoIn(BaseModel):
    source_artifact_id: int
    end_artifact_id: int | None = None     # klip start -> koniec
    duration: int | None = None
    video_model: str | None = None
    allow_spark: bool = False


class CanonIn(BaseModel):
    partner_id: int
    image_model: str | None = None
    edit_model: str | None = None
    fmt: str = "16:9"
    allow_spark: bool = False


@router.get("/api/duet/config")
def duet_config():
    prof = models.PROFILES.get(config.PARTNER_MODEL)
    return {"partner_model": config.PARTNER_MODEL, "max_refs": config.DUET_MAX_REFS,
            "interaction_default": config.INTERACTION_DEFAULT, "partner_max_refs": prof.max_refs if prof else None,
            "pose_warning": pipeline.DUET_POSE_WARNING}


# ---------------- biblioteka interakcji ----------------
@router.get("/api/duet/interactions")
def list_interactions():
    return duet.list_interactions()


@router.post("/api/duet/interactions")
async def add_interaction(name: str = Form(""), description: str = Form(""), file: UploadFile | None = File(None)):
    """Wlasna pozycja biblioteki: nazwa, opis po angielsku i opcjonalny obraz ukladu cial (nie wgrywaj zdjec prawdziwych osob)."""
    data = None
    if file is not None and file.filename:
        if Path(file.filename).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(400, "Dozwolone: png, jpg, webp")
        data = await file.read()
    return _wrap(duet.add_interaction, name, description, data)


@router.post("/api/duet/interactions/{ref}/image")
async def set_image(ref: str, file: UploadFile = File(...)):
    if Path(file.filename or "x.png").suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Dozwolone: png, jpg, webp")
    return _wrap(duet.set_interaction_image, ref, await file.read())


@router.delete("/api/duet/interactions/{ref}")
def delete_interaction(ref: str):
    _wrap(duet.delete_interaction, ref)
    return {"ok": True}


# ---------------- minimalny kanon partnera ----------------
@router.post("/api/duet/partner-canon")
def partner_canon(p: CanonIn):
    """Twarz + sylwetka partnera (2 ujecia, nie 8). Wyniki w galerii; zatwierdzasz je do kanonu (rola face / body)."""
    partner = _wrap(duet.character, p.partner_id)
    return {"items": _wrap(duet.submit_partner_canon, partner, p.image_model, p.edit_model,
                           p.fmt if p.fmt in ("16:9", "9:16") else "16:9", p.allow_spark)}


# ---------------- ujecia pary ----------------
def _shot_and_pose(g: PlanIn):
    a, b = _wrap(duet.character, g.a_id), _wrap(duet.character, g.b_id)
    shot = {**g.model_dump(), "partner_id": b["id"]}
    return a, b, shot, _wrap(duet.resolve_pose, g.interaction_id, g.pose_artifact_id)


@router.post("/api/duet/plan")
def plan(g: PlanIn):
    """Podglad bez zlecania: prompt, referencje (kolejnosc A, B, uklad), ostrzezenia o modelu i pokrycie planem."""
    a, b, shot, pose = _shot_and_pose(g)
    _wrap(duet.safe_texts, g.action, g.outfit, g.outfit_b, g.interaction)
    model, prompt, refs, prof, warnings = _wrap(pipeline.plan_image_duet, a, b, shot, g.edit_model, pose, g.interaction,
                                                g.outfit, g.outfit_b)
    return {"model": model, "prompt": prompt, "refs": refs["ref_ids"], "pose_used": refs["pose_used"], "warnings": warnings,
            "max_refs": prof.max_refs, "covered": models.covered(model),
            "video_prompt": prompts.video_prompt(a, shot, b, g.interaction)}


@router.post("/api/duet/shots")
def create_shot(g: PairShotIn):
    return _wrap(duet.create_pair_shot, g.a_id, g.b_id, g.model_dump())


@router.get("/api/duet/shots")
def list_shots(a: int | None = None, b: int | None = None):
    return duet.pair_shots(a, b)


@router.post("/api/duet/shots/{sid}/generate")
def generate(sid: int, g: GenIn):
    shot = db.one("SELECT * FROM shots WHERE id=? AND partner_id IS NOT NULL", (sid,))
    if not shot:
        raise HTTPException(404, "Nie ma takiego ujecia pary")
    count = max(1, min(g.count, 4))
    used = pipeline.attempts_used(sid)
    if used + count > config.MAX_ATTEMPTS_PER_SHOT:
        raise HTTPException(409, f"Limit prób dla ujęcia: {config.MAX_ATTEMPTS_PER_SHOT} (użyto {used}). Utwórz nowe ujęcie.")
    a, b = _wrap(duet.character, shot["character_id"]), _wrap(duet.character, shot["partner_id"])
    interaction = g.interaction if g.interaction is not None else (shot["interaction"] or "")
    outfit_a = g.outfit if g.outfit is not None else (shot["outfit"] or "")
    outfit_b = g.outfit_b if g.outfit_b is not None else (shot["outfit_b"] or "")
    _wrap(duet.safe_texts, interaction, outfit_a, outfit_b, shot["action"] or "")
    pose = _wrap(duet.resolve_pose, g.interaction_id, g.pose_artifact_id)
    label = "duet" + (f":{g.interaction_id}" if g.interaction_id else "")
    return _wrap(pipeline.submit_image_duet, shot, a, b, g.edit_model, count, pose, interaction, outfit_a, outfit_b,
                 g.allow_spark, label)


@router.post("/api/duet/shots/{sid}/video")
def video(sid: int, v: VideoIn):
    """Klip z obrazu pary (i2v) albo klip start->koniec (H3, te same proporcje obrazow). Prompt w liczbie mnogiej."""
    shot = db.one("SELECT * FROM shots WHERE id=? AND partner_id IS NOT NULL", (sid,))
    if not shot:
        raise HTTPException(404, "Nie ma takiego ujecia pary")
    a = _wrap(duet.character, shot["character_id"])
    used = pipeline.attempts_used(sid)
    if used + 1 > config.MAX_ATTEMPTS_PER_SHOT:
        raise HTTPException(409, f"Limit prób dla ujęcia: {config.MAX_ATTEMPTS_PER_SHOT} (użyto {used}).")
    return _wrap(pipeline.submit_video, shot, a, v.source_artifact_id, v.end_artifact_id, v.duration, None, None,
                 v.allow_spark, v.video_model)


@router.get("/api/duet/artifacts")
def pair_artifacts(a: int, b: int):
    """Wyniki wszystkich ujec pary A+B z dwiema miarami twarzy (A: face_score/min, B: face_score_b/min_b; orientacyjne)."""
    return db.rows(
        "SELECT a.*, s.az, s.el, s.dist, s.fov, s.fmt, s.interaction, s.id AS shot_id FROM artifacts a "
        "JOIN shots s ON s.id=a.shot_id WHERE s.character_id=? AND s.partner_id=? ORDER BY a.id DESC LIMIT 120", (a, b))
