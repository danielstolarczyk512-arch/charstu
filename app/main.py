import json
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, films_api, models, pipeline, producer, prompts, skeleton
from .camera import describe
from .providers.base import GenRequest
from .providers.factory import make_provider
from .runner import Runner, new_idem_key, save_atomic

STATIC = config.ROOT / "static"
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["provider"] = make_provider()
    state["runner"] = Runner(state["provider"])
    pipeline.runner = state["runner"]
    producer.provider = state["provider"]
    state["runner"].resume_pending()
    state["producer"] = producer.Producer()
    state["producer"].start()
    yield
    state["producer"].stop()


app = FastAPI(title="Character Studio", lifespan=lifespan)
app.include_router(films_api.router)


class CharacterIn(BaseModel):
    name: str
    archetype: str = ""
    traits: str = ""
    outfit: str = ""
    style: str = ""
    adult_fictional: bool = False


class ShotIn(BaseModel):
    character_id: int
    az: float = 40
    el: float = 5
    dist: float = 4
    fov: float = 35
    fmt: str = "16:9"
    action: str = ""
    outfit: str = ""     # opcjonalnie: strój tylko w tym ujęciu (puste = strój postaci/kanonu)
    image_model: str | None = None   # model generowania (bez kanonu); puste = domyslny z .env
    edit_model: str | None = None    # model edycji (z kanonem); puste = domyslny z .env
    use_refs: bool = True            # False = sam opis, bez referencji z kanonu


class GenIn(BaseModel):
    kind: str = "image"          # image | video
    image_model: str | None = None
    edit_model: str | None = None
    use_refs: bool = True
    count: int = 1
    source_artifact_id: int | None = None
    end_artifact_id: int | None = None   # klip start -> koniec (wymaga source_artifact_id)
    duration: int | None = None
    pose_artifact_id: int | None = None  # poza z referencji (obraz z biblioteki pozy), tylko obrazy


def _character(cid: int) -> dict:
    c = db.one("SELECT * FROM characters WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "Nie ma takiej postaci")
    return c


@app.get("/api/config")
def get_config():
    return {"provider": config.PROVIDER, "safe_content_filter": config.SAFE_CONTENT_FILTER,
            "billing_mode": config.SOGNI_BILLING_MODE, "max_attempts_per_shot": config.MAX_ATTEMPTS_PER_SHOT,
            "image_model": config.IMAGE_MODEL, "edit_model": config.EDIT_MODEL, "video_model": config.VIDEO_MODEL}


@app.get("/api/characters")
def list_characters():
    return db.rows("SELECT * FROM characters ORDER BY id DESC")


@app.post("/api/characters")
def create_character(c: CharacterIn):
    if not c.adult_fictional:
        raise HTTPException(400, "Postać musi być fikcyjna i dorosła (18+). Zaznacz potwierdzenie.")
    if not c.name.strip():
        raise HTTPException(400, "Podaj imię postaci")
    cid = db.run(
        "INSERT INTO characters(name,archetype,traits,outfit,style,adult_fictional,created) VALUES(?,?,?,?,?,1,?)",
        (c.name.strip(), c.archetype, c.traits, c.outfit, c.style, db.now()))
    return _character(cid)


class CharacterPatch(BaseModel):
    name: str | None = None
    archetype: str | None = None
    traits: str | None = None
    outfit: str | None = None
    style: str | None = None


def _safe_char_texts(*texts):
    from . import assistant
    if assistant._has_minor(*texts):
        raise HTTPException(400, assistant.REFUSAL)


@app.patch("/api/characters/{cid}")
def patch_character(cid: int, p: CharacterPatch):
    """Edycja karty postaci (po zmianie opisu istniejace obrazy zostaja, nowe ujecia uzyja nowego opisu)."""
    c = _character(cid)
    data = p.model_dump(exclude_unset=True)
    merged = {**c, **{k: (v or "").strip() for k, v in data.items() if v is not None}}
    if not merged["name"].strip():
        raise HTTPException(400, "Imie postaci nie moze byc puste")
    _safe_char_texts(*[merged[k] for k in ("name", "archetype", "traits", "outfit", "style")])
    if "adult" not in (merged["archetype"] or "").lower():  # ta sama zasada co w asystencie: archetyp zawsze dorosly
        merged["archetype"] = ("adult " + (merged["archetype"] or "")).strip()
    db.run("UPDATE characters SET name=?,archetype=?,traits=?,outfit=?,style=? WHERE id=?",
           (merged["name"], merged["archetype"], merged["traits"], merged["outfit"], merged["style"], cid))
    return _character(cid)


@app.delete("/api/characters/{cid}")
def delete_character(cid: int):
    _character(cid)
    if db.one("SELECT 1 FROM films WHERE character_id=?", (cid,)):
        raise HTTPException(409, "Postac ma filmy - usun je najpierw")
    db.run("DELETE FROM outfits WHERE character_id=?", (cid,))
    db.run("DELETE FROM canon_assets WHERE character_id=?", (cid,))
    db.run("DELETE FROM characters WHERE id=?", (cid,))
    return {"ok": True}


class SheetIn(BaseModel):
    fmt: str = "16:9"
    edit_model: str | None = None
    only: list[str] | None = None


class RefineIn(BaseModel):
    source_artifact_id: int
    instruction: str
    count: int = 1
    edit_model: str | None = None


@app.post("/api/characters/{cid}/sheet")
def character_sheet(cid: int, s: SheetIn):
    """Arkusz postaci: 4 widoki + 4 miny z kanonu (8 obrazow). Wyniki w galerii; najlepsze zatwierdzasz do kanonu."""
    c = _character(cid)
    if not db.one("SELECT 1 FROM canon_assets WHERE character_id=? AND approved=1", (cid,)):
        raise HTTPException(409, "Arkusz wymaga kanonu: dodaj albo zatwierdz przynajmniej jeden obraz twarzy/sylwetki.")
    try:
        return {"items": pipeline.submit_sheet(c, s.fmt if s.fmt in ("16:9", "9:16") else "16:9", s.edit_model, s.only)}
    except pipeline.PipelineError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/characters/{cid}/refine")
def refine_image(cid: int, r: RefineIn):
    """Poprawka wybranego obrazu z galerii: zmienia opisana cecha, reszta zostaje."""
    c = _character(cid)
    try:
        return pipeline.submit_refine(c, r.source_artifact_id, r.instruction, r.count, r.edit_model)
    except pipeline.PipelineError as e:
        raise HTTPException(e.status, str(e))


class OutfitIn(BaseModel):
    name: str
    description: str


@app.get("/api/characters/{cid}/outfits")
def list_outfits(cid: int):
    _character(cid)
    return db.rows("SELECT * FROM outfits WHERE character_id=? ORDER BY id", (cid,))


@app.post("/api/characters/{cid}/outfits")
def add_outfit(cid: int, o: OutfitIn):
    """Szafa: nazwany strój (opis po angielsku) do wyboru w ujęciach Studia i filmu."""
    _character(cid)
    name, desc = o.name.strip()[:60], o.description.strip()[:300]
    if not name or not desc:
        raise HTTPException(400, "Podaj nazwe i opis stroju")
    _safe_char_texts(name, desc)
    oid = db.run("INSERT INTO outfits(character_id,name,description,created) VALUES(?,?,?,?)", (cid, name, desc, db.now()))
    return db.one("SELECT * FROM outfits WHERE id=?", (oid,))


@app.delete("/api/outfits/{oid}")
def delete_outfit(oid: int):
    db.run("DELETE FROM outfits WHERE id=?", (oid,))
    return {"ok": True}


def _add_pose(cid: int, data: bytes, name: str) -> dict:
    """Biblioteka pozy = obrazy w galerii z etykieta 'poza:<nazwa>' (z uploadu albo szkieletu)."""
    from . import pipeline as pl
    sid = pl.new_shot(cid, {"fmt": "16:9", "action": "pose reference"}, "")
    rel = Path("outputs") / f"pose_{cid}_{int(db.now() * 1000)}.png"
    sha = save_atomic(data, config.DATA / rel)
    aid = db.run("INSERT INTO artifacts(job_id,shot_id,kind,path,sha256,label,created) VALUES(0,?,?,?,?,?,?)",
                 (sid, "image", rel.as_posix(), sha, "poza:" + name[:60], db.now()))
    return db.one("SELECT * FROM artifacts WHERE id=?", (aid,))


@app.get("/api/characters/{cid}/poses")
def list_poses(cid: int):
    _character(cid)
    return {"presets": sorted(skeleton.PRESETS),
            "poses": db.rows("SELECT a.* FROM artifacts a JOIN shots s ON s.id=a.shot_id WHERE s.character_id=? "
                             "AND a.label LIKE 'poza:%' ORDER BY a.id DESC", (cid,))}


@app.post("/api/characters/{cid}/poses")
async def add_pose(cid: int, name: str = Form(""), preset: str = Form(""), points: str = Form(""),
                   file: UploadFile | None = File(None)):
    """Dodaje poze: plik obrazu (ZDJECIE POZY - nie wgrywaj zdjec prawdziwych osob; liczy sie tylko poza), gotowy
    szkielet ('preset') albo wlasny szkielet ('points' = JSON punktow COCO 0..1)."""
    _character(cid)
    import io
    from PIL import Image
    if file is not None and file.filename:
        if Path(file.filename).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(400, "Dozwolone: png, jpg, webp")
        raw = await file.read()
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Nie da sie odczytac obrazu")
        im.thumbnail((1600, 1600))
        label = name.strip() or Path(file.filename).stem
    elif preset or points:
        if preset:
            pts = skeleton.PRESETS.get(preset)
            if not pts:
                raise HTTPException(400, f"Nieznany preset. Dostepne: {', '.join(sorted(skeleton.PRESETS))}")
        else:
            try:
                pts = skeleton.validate(json.loads(points))
            except ValueError:
                raise HTTPException(400, "points: niepoprawny JSON")
            if len(pts) < 8:
                raise HTTPException(400, "Szkielet wymaga co najmniej 8 punktow")
        im = skeleton.render(pts, (1280, 720))
        label = name.strip() or ("szkielet " + (preset or "wlasny"))
    else:
        raise HTTPException(400, "Podaj plik obrazu, preset albo points")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return _add_pose(cid, buf.getvalue(), label)


@app.get("/api/characters/{cid}/canon")
def list_canon(cid: int):
    return db.rows("SELECT * FROM canon_assets WHERE character_id=? ORDER BY id DESC", (cid,))


@app.post("/api/characters/{cid}/canon")
async def upload_canon(cid: int, role: str = Form("face"), tier: str = Form("main"), file: UploadFile = File(...)):
    _character(cid)
    ext = Path(file.filename or "x.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Dozwolone: png, jpg, webp")
    data = await file.read()
    rel = Path("canon") / f"c{cid}_{role}_{int(db.now())}{ext}"
    sha = save_atomic(data, config.DATA / rel)
    aid = db.run("INSERT INTO canon_assets(character_id,role,tier,path,sha256,approved,created) VALUES(?,?,?,?,?,1,?)",
                 (cid, role, tier, rel.as_posix(), sha, db.now()))
    return db.one("SELECT * FROM canon_assets WHERE id=?", (aid,))


@app.delete("/api/canon/{aid}")
def delete_canon(aid: int):
    db.run("DELETE FROM canon_assets WHERE id=?", (aid,))
    return {"ok": True}


def _plan_image(c: dict, shot: dict, image_model: str | None, edit_model: str | None, use_refs: bool):
    """Cienka nakladka HTTP na pipeline.plan_image (bledy -> HTTPException)."""
    try:
        return pipeline.plan_image(c, shot, image_model, edit_model, use_refs)
    except pipeline.PipelineError as e:
        raise HTTPException(e.status, str(e))


@app.get("/api/models")
def list_models():
    return {**models.catalog(), "defaults": {"generate": config.IMAGE_MODEL, "edit": config.EDIT_MODEL}}


@app.post("/api/preview")
def preview(s: ShotIn):
    c = _character(s.character_id)
    shot = s.model_dump()
    kind, model, prompt, refs, prof = _plan_image(c, shot, s.image_model, s.edit_model, s.use_refs)
    return {"camera": describe(s.az, s.el, s.dist, s.fov), "refs": refs, "kind": kind, "model": model,
            "style": prof.style, "image_prompt": prompt, "video_prompt": prompts.video_prompt(c, shot)}


@app.post("/api/shots")
def create_shot(s: ShotIn):
    c = _character(s.character_id)
    shot = s.model_dump()
    _, _, prompt, _, _ = _plan_image(c, shot, s.image_model, s.edit_model, s.use_refs)
    sid = db.run("INSERT INTO shots(character_id,az,el,dist,fov,fmt,action,outfit,prompt,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (s.character_id, s.az, s.el, s.dist, s.fov, s.fmt, s.action, s.outfit, prompt, db.now()))
    return db.one("SELECT * FROM shots WHERE id=?", (sid,))


@app.get("/api/shots")
def list_shots(character_id: int):
    return db.rows("SELECT * FROM shots WHERE character_id=? ORDER BY id DESC", (character_id,))


def _select_refs(character_id: int, shot: dict) -> list[int]:
    return pipeline.select_refs(character_id, shot)


@app.post("/api/shots/{sid}/generate")
def generate(sid: int, g: GenIn):
    shot = db.one("SELECT * FROM shots WHERE id=?", (sid,))
    if not shot:
        raise HTTPException(404, "Nie ma takiego ujęcia")
    if g.kind not in ("image", "video"):
        raise HTTPException(400, "kind: image albo video")
    used = pipeline.attempts_used(sid)
    count = max(1, min(g.count, 4))
    if used + count > config.MAX_ATTEMPTS_PER_SHOT:
        raise HTTPException(409, f"Limit prób dla ujęcia: {config.MAX_ATTEMPTS_PER_SHOT} (użyto {used}). "
                                 "Zmień referencje lub prompt zamiast ponawiać.")
    c = _character(shot["character_id"])
    try:
        if g.kind == "video":
            return pipeline.submit_video(shot, c, g.source_artifact_id, g.end_artifact_id, g.duration)
        return pipeline.submit_image(shot, c, g.image_model, g.edit_model, g.use_refs, count, pose_artifact_id=g.pose_artifact_id)
    except pipeline.PipelineError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/shots/{sid}/estimate")
def estimate(sid: int, g: GenIn):
    shot = db.one("SELECT * FROM shots WHERE id=?", (sid,))
    if not shot:
        raise HTTPException(404, "Nie ma takiego ujęcia")
    c = _character(shot["character_id"])
    if g.kind == "video":
        kind, prompt, model = "video", prompts.video_prompt(c, shot), None
    else:
        kind, model, prompt, _, _ = _plan_image(c, shot, g.image_model, g.edit_model, g.use_refs)
    req = GenRequest(kind=kind, prompt=prompt, fmt=shot["fmt"], model=model, safe_filter=config.SAFE_CONTENT_FILTER)
    return state["provider"].estimate(req)


@app.get("/api/jobs")
def list_jobs(character_id: int | None = None):
    sql = "SELECT j.* FROM jobs j JOIN shots s ON s.id=j.shot_id"
    args: tuple = ()
    if character_id is not None:
        sql += " WHERE s.character_id=?"
        args = (character_id,)
    return db.rows(sql + " ORDER BY j.id DESC LIMIT 60", args)


@app.get("/api/artifacts")
def list_artifacts(character_id: int):
    return db.rows(
        "SELECT a.*, s.az, s.el, s.dist, s.fov, s.fmt FROM artifacts a JOIN shots s ON s.id=a.shot_id "
        "WHERE s.character_id=? ORDER BY a.id DESC LIMIT 100", (character_id,))


@app.post("/api/artifacts/{aid}/approve")
def approve_artifact(aid: int, role: str = Form("front")):
    """Zatwierdzenie do kanonu kierunkowego (kopia pliku, nie referencja glowna)."""
    a = db.one("SELECT * FROM artifacts WHERE id=?", (aid,))
    if not a or a["kind"] != "image":
        raise HTTPException(400, "Zatwierdzać można tylko obrazy")
    shot = db.one("SELECT * FROM shots WHERE id=?", (a["shot_id"],))
    src = config.DATA / a["path"]
    rel = Path("canon") / f"c{shot['character_id']}_{role}_art{aid}{src.suffix}"
    shutil.copyfile(src, config.DATA / rel)
    db.run("UPDATE artifacts SET approved=1 WHERE id=?", (aid,))
    db.run("INSERT INTO canon_assets(character_id,role,tier,path,sha256,approved,note,created) "
           "VALUES(?,?,'directional',?,?,1,?,?)",
           (shot["character_id"], role, rel.as_posix(), a["sha256"], f"artifact {aid}", db.now()))
    return {"ok": True}


class AssistIn(BaseModel):
    message: str
    history: list[dict] = []
    character_id: int | None = None
    camera: dict = {}


@app.post("/api/assistant")
def assistant_ask(a: AssistIn):
    """Asystent proponuje pola postaci i liste ujec. Niczego nie zapisuje ani nie generuje."""
    from . import assistant
    prov = state["provider"]
    if not hasattr(prov, "_call"):
        raise HTTPException(409, "Asystent wymaga PROVIDER=sogni (model jezykowy z planu).")
    ctx: dict = {"camera": a.camera}
    if a.character_id:
        c = _character(a.character_id)
        ctx["character"] = {k: c[k] for k in ("name", "archetype", "traits", "outfit", "style")}
        ctx["canon_coverage"] = coverage(a.character_id)
    try:
        return assistant.ask(prov, a.message, a.history, ctx)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Asystent: {e}")


STUDIO_VOICES = ["serena", "vivian", "uncle_fu", "ryan", "aiden", "ono_anna", "sohee", "eric", "dylan"]
# Qwen3-TTS: jezyki z dokumentacji Sogni. Polskiego NIE ma na liscie - kwestie lektora pisz po angielsku (lub w jednym z tych).
TTS_LANGUAGES = ["auto", "english", "chinese", "japanese", "korean", "german", "french", "russian", "portuguese",
                 "spanish", "italian"]
# Stala, neutralna kwestia (ok. 15 s) do zaprojektowania glosu raz i sklonowania do kazdej kolejnej kwestii.
DESIGN_PASSAGE = ("The morning light spread slowly across the quiet valley, and a gentle wind moved through the tall grass. "
                  "She paused for a moment, listened to the distant river, and then continued along the narrow path "
                  "toward the village, where the first lanterns were already being lit.")


class VoiceIn(BaseModel):
    voice: str = "serena"            # glos studyjny (stale ten sam mowca)
    description: str = ""            # opcjonalny kierunek wykonania dla glosu studyjnego
    language: str = "english"


class DesignIn(BaseModel):
    description: str
    language: str = "english"


class SpeechIn(BaseModel):
    character_id: int
    text: str
    language: str | None = None
    label: str | None = None


class MusicIn(BaseModel):
    character_id: int
    prompt: str
    duration: int = 30
    label: str | None = None


def _audio_job(character_id: int, kind: str, params: dict, model: str, label: str) -> int:
    """Zadanie dzwiekowe (mowa/muzyka) w tej samej kolejce co obrazy; wynik laduje w galerii jako artefakt 'audio'."""
    sid = db.run("INSERT INTO shots(character_id,az,el,dist,fov,fmt,action,outfit,prompt,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (character_id, 0, 0, 0, 0, "audio", label[:120], "", params.get("text") or params.get("prompt", ""), db.now()))
    return pipeline.submit_job(sid, kind, model, {**params, "label": label})


def _voice_of(character_id: int) -> dict:
    c = _character(character_id)
    v = json.loads(c.get("voice") or "null") or {"mode": "voice", "voice": "serena", "language": "english"}
    return v


@app.get("/api/characters/{cid}/voice")
def get_voice(cid: int):
    return {**_voice_of(cid), "studio_voices": STUDIO_VOICES, "languages": TTS_LANGUAGES, "design_passage": DESIGN_PASSAGE}


@app.put("/api/characters/{cid}/voice")
def set_voice(cid: int, v: VoiceIn):
    """Ustawia glos studyjny postaci (ten sam mowca w kazdej kwestii)."""
    _character(cid)
    if v.voice not in STUDIO_VOICES:
        raise HTTPException(400, f"Glos studyjny: {', '.join(STUDIO_VOICES)}")
    if v.language not in TTS_LANGUAGES:
        raise HTTPException(400, f"Jezyk: {', '.join(TTS_LANGUAGES)}")
    voice = {"mode": "voice", "voice": v.voice, "description": v.description[:512], "language": v.language}
    db.run("UPDATE characters SET voice=? WHERE id=?", (json.dumps(voice), cid))
    return voice


@app.post("/api/characters/{cid}/voice/design")
def design_voice(cid: int, d: DesignIn):
    """Projektuje glos z opisu (JEDEN raz), a po wygenerowaniu probki program sam przelacza postac na klon tej probki
    z dokladnym transkryptem. Dzieki temu kazda kolejna kwestia ma ten sam glos (design wywolany osobno
    dla kazdej kwestii dalby za kazdym razem innego mowce - ostrzega dokumentacja Sogni)."""
    _character(cid)
    if not d.description.strip() or len(d.description) > 512:
        raise HTTPException(400, "Opis glosu: 1-512 znakow")
    if d.language not in TTS_LANGUAGES:
        raise HTTPException(400, f"Jezyk: {', '.join(TTS_LANGUAGES)}")
    params = {"text": DESIGN_PASSAGE, "prompt": DESIGN_PASSAGE, "language": d.language, "adopt_voice_for": cid,
              "voice": {"mode": "design", "description": d.description.strip(), "language": d.language}}
    return {"job": _audio_job(cid, "speech", params, "qwen3-tts-design", "probka glosu")}


@app.post("/api/speech")
def speak(s: SpeechIn):
    """Kwestia lektora glosem postaci (studyjnym albo sklonowanym z zaprojektowanej probki)."""
    _character(s.character_id)
    text = s.text.strip()
    if not text or len(text) > 600:
        raise HTTPException(400, "Tekst kwestii: 1-600 znakow")
    v = _voice_of(s.character_id)
    if s.language:
        if s.language not in TTS_LANGUAGES:
            raise HTTPException(400, f"Jezyk: {', '.join(TTS_LANGUAGES)}")
        v = {**v, "language": s.language}
    params = {"text": text, "prompt": text, "voice": v, "language": v.get("language", "english")}
    return {"job": _audio_job(s.character_id, "speech", params, "qwen3-tts-" + v.get("mode", "voice"),
                              s.label or text[:60]), "voice": v}


@app.post("/api/music")
def make_music(m: MusicIn):
    _character(m.character_id)
    if not m.prompt.strip() or len(m.prompt) > 800:
        raise HTTPException(400, "Opis muzyki: 1-800 znakow (tempo i tonacje wpisz w opisie)")
    if not 10 <= m.duration <= 300:
        raise HTTPException(400, "Dlugosc muzyki: 10-300 s")
    params = {"prompt": m.prompt.strip(), "duration": m.duration}
    return {"job": _audio_job(m.character_id, "music", params, "music3", m.label or m.prompt[:60])}


class StitchIn(BaseModel):
    artifact_ids: list[int]
    fade: float = 0.0
    audio_mode: str = "keep"             # keep | normalize | mute (dzwiek wbudowany w klipy)
    bed_artifact_id: int | None = None   # podklad muzyczny (artefakt audio)
    bed_db: float = -20.0
    voice_artifact_ids: list[int] = []   # kwestie lektora: i-ta kwestia startuje przy i-tym klipie
    duck: bool = True                    # podklad cichnie pod lektorem


def _audio_art(aid: int) -> Path:
    a = db.one("SELECT * FROM artifacts WHERE id=?", (aid,))
    if not a or a["kind"] != "audio":
        raise HTTPException(400, f"Artefakt {aid} nie jest dzwiekiem")
    return config.DATA / a["path"]


@app.post("/api/stitch")
def stitch_clips(s: StitchIn):
    """Sklejka wybranych klipow w kolejnosci podanej w artifact_ids (ffmpeg, lokalnie), z opcjonalna sciezka dzwiekowa."""
    from . import stitch as st
    arts = []
    for aid in s.artifact_ids:
        a = db.one("SELECT * FROM artifacts WHERE id=?", (aid,))
        if not a or a["kind"] != "video":
            raise HTTPException(400, f"Artefakt {aid} nie jest klipem wideo")
        arts.append(a)
    if len(arts) < 2:
        raise HTTPException(400, "Zaznacz co najmniej 2 klipy")
    if s.audio_mode not in ("keep", "normalize", "mute"):
        raise HTTPException(400, "audio_mode: keep, normalize albo mute")
    bed = _audio_art(s.bed_artifact_id) if s.bed_artifact_id else None
    voices = [(_audio_art(v), i) for i, v in enumerate(s.voice_artifact_ids)]
    shot_id = arts[0]["shot_id"]
    jid = db.run("INSERT INTO jobs(shot_id,kind,provider,model,params,status,idem_key,safe_filter,created,started) "
                 "VALUES(?,?,?,?,?,'running',?,1,?,?)",
                 (shot_id, "stitch", "local", "ffmpeg", json.dumps({"artifact_ids": s.artifact_ids, "fade": s.fade,
                                                                    "audio_mode": s.audio_mode}),
                  new_idem_key(), db.now(), db.now()))
    rel = Path("outputs") / f"stitch_{jid}.mp4"
    try:
        paths = [config.DATA / a["path"] for a in arts]
        info = st.assemble(paths, config.DATA / rel, fade=s.fade, audio_mode=s.audio_mode, bed=bed, bed_db=s.bed_db,
                           voices=voices, duck=s.duck)
        jumps = [st.boundary_jump(paths[i], paths[i + 1]) for i in range(len(paths) - 1)]
    except Exception as e:  # noqa: BLE001
        db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?", (db.now(), str(e), jid))
        raise HTTPException(500, str(e))
    db.run("INSERT INTO artifacts(job_id,shot_id,kind,path,created) VALUES(?,?,?,?,?)",
           (jid, shot_id, "video", rel.as_posix(), db.now()))
    db.run("UPDATE jobs SET status='done', finished=? WHERE id=?", (db.now(), jid))
    return {"job": jid, "path": rel.as_posix(), "info": info, "boundary_jumps": jumps}


@app.post("/api/artifacts/{aid}/measure")
def measure(aid: int):
    """Pomiar twarzy na zadanie (np. dla starszych wynikow). Pierwsze uzycie laduje model (ok. 20 s)."""
    from .runner import measure_artifact
    if not db.one("SELECT id FROM artifacts WHERE id=?", (aid,)):
        raise HTTPException(404, "Nie ma takiego artefaktu")
    r = measure_artifact(aid)
    if r is None:
        raise HTTPException(409, "Pomiar niedostepny: brak kanonu (twarz), InsightFace albo FACE_GUARD=false")
    return r


@app.get("/api/coverage")
def coverage(character_id: int):
    roles = ["face", "body", "front", "three_quarter", "profile", "back"]
    have = {r["role"] for r in db.rows(
        "SELECT role FROM canon_assets WHERE character_id=? AND approved=1", (character_id,))}
    return {r: (r in have) for r in roles}


app.mount("/files", StaticFiles(directory=config.DATA), name="files")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


class NoCacheStatic(StaticFiles):
    """Pliki interfejsu zawsze sprawdzane na serwerze (po zmianie kodu przegladarka nie trzyma starej wersji)."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", NoCacheStatic(directory=STATIC), name="static")
