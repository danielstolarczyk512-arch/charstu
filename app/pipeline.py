"""Wspolna logika zlecania obrazow, klipow i dzwieku (uzywana przez API HTTP i przez producenta filmu)."""
import json
import re

from . import config, db, models, prompts
from .camera import describe
from .runner import new_idem_key

runner = None  # ustawiane przez main.lifespan

ANGLE_ROLE = {"front view": "front", "three-quarter view": "three_quarter",
              "side profile view": "profile", "rear three-quarter view": "three_quarter", "back view": "back"}
_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class PipelineError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def select_refs(character_id: int, shot: dict) -> list[int]:
    """Kolejnosc: twarz, sylwetka, widok kierunkowy pasujacy do kata. Limit MAX_REFS."""
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    want = next((r for k, r in ANGLE_ROLE.items() if cam.startswith(k)), None)
    assets = db.rows("SELECT * FROM canon_assets WHERE character_id=? AND approved=1", (character_id,))
    picked: list[int] = []
    seen: set[str] = set()  # ten sam plik zatwierdzony pod dwiema rolami liczy sie raz (limit referencji modelu)
    for role in ("face", "body", want):
        a = next((x for x in assets if x["role"] == role and x["id"] not in picked
                  and (x["sha256"] or str(x["id"])) not in seen), None)
        if a:
            picked.append(a["id"])
            seen.add(a["sha256"] or str(a["id"]))
    return picked[:config.MAX_REFS]


def plan_image(c: dict, shot: dict, image_model: str | None, edit_model: str | None, use_refs: bool):
    """Wybiera operacje i model oraz buduje prompt w stylu oczekiwanym przez ten model.
    Z referencjami (kanon) -> edycja modelem edycji; bez -> generowanie modelem generowania."""
    refs = select_refs(c["id"], shot) if use_refs else []
    op = "edit" if refs else "generate"
    model = ((edit_model if refs else image_model) or (config.EDIT_MODEL if refs else config.IMAGE_MODEL)).strip()
    if not _MODEL_ID.match(model):
        raise PipelineError(f"Niepoprawny identyfikator modelu: {model[:40]!r}")
    known = models.PROFILES.get(model)
    if known and known.op != op:  # Sogni: model tylko-do-generowania nie przyjmuje edycji (i odwrotnie)
        raise PipelineError(f"{known.label} obsluguje tylko {'generowanie' if known.op == 'generate' else 'edycje'}; "
                            f"wybierz inny model dla operacji: {'edycja z kanonem' if refs else 'generowanie bez kanonu'}.")
    prof = models.get(model, op)
    if refs and prof.max_refs:
        refs = refs[:prof.max_refs]
    prompt = prompts.image_prompt(c, shot, with_refs=bool(refs), style=prof.style, n_refs=len(refs))
    return ("edit" if refs else "image"), model, prompt, refs, prof


def check_flf(source_id: int | None, end_id: int | None):
    """Klip start->koniec: oba obrazy musza istniec i miec te same proporcje (kwadratowy start + kadr 16:9 dal
    w tescie klip z przycieta glowa na poczatku)."""
    from PIL import Image
    if not source_id or not end_id:
        raise PipelineError("Klip start->koniec wymaga obrazu startowego i koncowego")
    sizes = []
    for aid in (source_id, end_id):
        a = db.one("SELECT path, kind FROM artifacts WHERE id=?", (aid,))
        if not a or a["kind"] != "image":
            raise PipelineError(f"Artefakt {aid} nie jest obrazem")
        with Image.open(config.DATA / a["path"]) as im:
            sizes.append(im.size)
    (w1, h1), (w2, h2) = sizes
    if abs(w1 / h1 - w2 / h2) > 0.05:
        raise PipelineError(f"Obrazy maja rozne proporcje ({w1}x{h1} i {w2}x{h2}); klip zostalby przyciety. "
                            "Wygeneruj oba w tym samym formacie (np. 16:9).")


def attempts_used(shot_id: int) -> int:
    return db.one("SELECT COUNT(*) n FROM jobs WHERE shot_id=?", (shot_id,))["n"]


def submit_job(shot_id: int, kind: str, model: str, params: dict, film_shot_id: int | None = None,
               role: str | None = None) -> int:
    """Wstawia zadanie do bazy i kolejki. Limit prob na ujecie sprawdza wywolujacy."""
    jid = db.run(
        "INSERT INTO jobs(shot_id,kind,provider,model,params,status,idem_key,safe_filter,created,film_shot_id,role) "
        "VALUES(?,?,?,?,?,'queued',?,?,?,?,?)",
        (shot_id, kind, config.PROVIDER, model, json.dumps(params), new_idem_key(),
         int(config.SAFE_CONTENT_FILTER), db.now(), film_shot_id, role))
    runner.enqueue(jid)
    return jid


POSE_MODEL = "qwen"   # Krea Identity Edit nie przenosi pozy z drugiego obrazu (testy), Qwen tak


def plan_pose(c: dict, shot: dict, pose_artifact_id: int, edit_model: str | None):
    """Poza z referencji: kanon (1 obraz, twarz) + obraz pozy z galerii; model musi przyjmowac >=2 referencji."""
    a = db.one("SELECT kind FROM artifacts WHERE id=?", (pose_artifact_id,))
    if not a or a["kind"] != "image":
        raise PipelineError("Poza musi byc obrazem z galerii (dodaj ja przez 'Pozy')")
    refs = select_refs(c["id"], shot)[:1]
    if not refs:
        raise PipelineError("Poza z referencji wymaga kanonu postaci (zatwierdz obraz twarzy/sylwetki).", 409)
    model = (edit_model or POSE_MODEL).strip()
    if not _MODEL_ID.match(model):
        raise PipelineError(f"Niepoprawny identyfikator modelu: {model[:40]!r}")
    prof = models.get(model, "edit")
    known = models.PROFILES.get(model)
    if (known and known.op != "edit") or "krea" in model or (prof.max_refs and prof.max_refs < 2):
        raise PipelineError(f"Model {model} nie przenosi pozy z obrazu referencyjnego - uzyj modelu Qwen Image Edit ({POSE_MODEL}).")
    return model, prompts.pose_prompt(c, shot), refs


def submit_image(shot: dict, c: dict, image_model=None, edit_model=None, use_refs=True, count=1,
                 film_shot_id=None, role=None, label=None, pose_artifact_id=None) -> dict:
    if pose_artifact_id:
        model, prompt, refs = plan_pose(c, shot, pose_artifact_id, edit_model)
        params = {"prompt": prompt, "fmt": shot["fmt"], "ref_ids": refs, "ref_artifact_ids": [pose_artifact_id],
                  "label": label or "poza"}
        ids = [submit_job(shot["id"], "edit", model, params, film_shot_id, role) for _ in range(count)]
        return {"jobs": ids, "kind": "edit", "refs": refs, "pose": pose_artifact_id}
    kind, model, prompt, refs, _ = plan_image(c, shot, image_model, edit_model, use_refs)
    params = {"prompt": prompt, "fmt": shot["fmt"], "ref_ids": refs if kind == "edit" else []}
    if label:
        params["label"] = label
    ids = [submit_job(shot["id"], kind, model, params, film_shot_id, role) for _ in range(count)]
    return {"jobs": ids, "kind": kind, "refs": refs}


# Arkusz postaci: widoki (kat/wysokosc/dystans) i miny z kanonu. Etykieta "arkusz:<rola>:<opis>" podpowiada rolę kanonu.
SHEET_ITEMS = [
    ("front", "Przód", 0, 5, 5.0, "stands in a relaxed neutral pose, arms at her sides"),
    ("three_quarter", "Trzy czwarte", 40, 5, 5.0, "stands in a relaxed neutral pose, arms at her sides"),
    ("profile", "Profil", 90, 5, 5.0, "stands in a relaxed neutral pose, arms at her sides"),
    ("back", "Tył", 180, 5, 5.0, "stands in a relaxed neutral pose, arms at her sides"),
    ("face", "Twarz", 0, 5, 1.8, "a calm neutral expression, looking at the camera"),
    ("face", "Uśmiech", 15, 5, 1.8, "a soft gentle smile"),
    ("face", "Powaga", 15, 5, 1.8, "a serious determined expression"),
    ("face", "Zdziwienie", 15, 5, 1.8, "a surprised expression, eyes wide open"),
]


def submit_sheet(c: dict, fmt: str = "16:9", edit_model=None, only: list[str] | None = None) -> list[dict]:
    """Zlecenia arkusza postaci z kanonu. Wymaga kanonu (edycja zachowuje tozsamosc)."""
    out = []
    for role, name, az, el, dist, action in SHEET_ITEMS:
        if only and name not in only and role not in only:
            continue
        shot = {"az": az, "el": el, "dist": dist, "fov": 35, "fmt": fmt, "action": action, "outfit": ""}
        sid = new_shot(c["id"], shot, "")
        shot["id"] = sid
        r = submit_image(shot, c, None, edit_model, True, 1, label=f"arkusz:{role}:{name}")
        out.append({"name": name, "role": role, **r})
    return out


def submit_refine(c: dict, source_artifact_id: int, instruction: str, count: int = 1, edit_model=None) -> dict:
    """Poprawka istniejacego obrazu: zmienia opisana cecha, reszta zostaje (poza, kadr, tlo, swiatlo, twarz)."""
    from PIL import Image
    a = db.one("SELECT path, kind FROM artifacts WHERE id=?", (source_artifact_id,))
    if not a or a["kind"] != "image":
        raise PipelineError("Poprawiac mozna tylko obraz z galerii")
    ins = (instruction or "").strip()
    if not ins or len(ins) > 400:
        raise PipelineError("Opis poprawki: 1-400 znakow (angielski dziala najlepiej)")
    from . import assistant
    if assistant._has_minor(ins):
        raise PipelineError(assistant.REFUSAL)
    model = (edit_model or config.EDIT_MODEL).strip()
    if not _MODEL_ID.match(model):
        raise PipelineError(f"Niepoprawny identyfikator modelu: {model[:40]!r}")
    known = models.PROFILES.get(model)
    if known and known.op != "edit":
        raise PipelineError(f"{known.label} obsluguje tylko generowanie - do poprawek wybierz model edycji.")
    with Image.open(config.DATA / a["path"]) as im:
        w, h = im.size
    ratios = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4}
    fmt = min(ratios, key=lambda k: abs(ratios[k] - w / h))
    sid = new_shot(c["id"], {"fmt": fmt, "action": ins[:120]}, "")
    params = {"prompt": prompts.refine_prompt(ins), "fmt": fmt, "ref_ids": [], "ref_artifact_ids": [source_artifact_id],
              "label": "poprawka: " + ins[:60]}
    ids = [submit_job(sid, "edit", model, params) for _ in range(max(1, min(count, 4)))]
    return {"jobs": ids, "kind": "edit", "fmt": fmt}


def submit_video(shot: dict, c: dict, source_artifact_id: int | None, end_artifact_id: int | None = None,
                 duration: int | None = None, film_shot_id=None, role=None) -> dict:
    model = config.VIDEO_MODEL
    if end_artifact_id:
        check_flf(source_artifact_id, end_artifact_id)
        model = config.FLF_MODEL
    params = {"prompt": prompts.video_prompt(c, shot), "fmt": shot["fmt"], "source_artifact_id": source_artifact_id,
              "end_artifact_id": end_artifact_id,
              "duration": duration or (config.FLF_DURATION if end_artifact_id else config.VIDEO_DURATION)}
    return {"jobs": [submit_job(shot["id"], "video", model, params, film_shot_id, role)], "kind": "video", "refs": []}


def new_shot(character_id: int, shot: dict, prompt: str = "") -> int:
    return db.run("INSERT INTO shots(character_id,az,el,dist,fov,fmt,action,outfit,prompt,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (character_id, shot.get("az", 0), shot.get("el", 5), shot.get("dist", 4.5), shot.get("fov", 35),
                   shot.get("fmt", "16:9"), shot.get("action", ""), shot.get("outfit", ""), prompt, db.now()))
