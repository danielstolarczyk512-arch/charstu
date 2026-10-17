"""Kolejka zadan: limity wspolbieznosci, trwaly stan w SQLite, natychmiastowy zapis wynikow."""
import hashlib
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, db, models
from .providers.base import GenRequest, Provider

log = logging.getLogger("runner")


def save_atomic(data: bytes, dest: Path) -> str:
    """Zapis przez plik tymczasowy; zwraca sha256. Rekord w bazie powstaje dopiero po tym."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return hashlib.sha256(data).hexdigest()


class Runner:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.pools = {
            "image": ThreadPoolExecutor(config.MAX_IMAGE_JOBS, thread_name_prefix="img"),
            "video": ThreadPoolExecutor(config.MAX_VIDEO_JOBS, thread_name_prefix="vid"),
            "audio": ThreadPoolExecutor(2, thread_name_prefix="aud"),
        }

    def enqueue(self, job_id: int):
        job = db.one("SELECT kind FROM jobs WHERE id=?", (job_id,))
        pool = self.pools["video" if job["kind"] == "video" else "audio" if job["kind"] in ("music", "speech") else "image"]
        pool.submit(self._run, job_id)

    def resume_pending(self):
        db.run("UPDATE jobs SET status='failed', error='przerwane restartem' WHERE kind='stitch' AND status='running'")
        for j in db.rows("SELECT id FROM jobs WHERE status IN ('queued','running') AND kind!='stitch'"):
            db.run("UPDATE jobs SET status='queued' WHERE id=?", (j["id"],))
            self.enqueue(j["id"])

    def build_request(self, job: dict) -> GenRequest:
        p = json.loads(job["params"])
        refs = [config.DATA / r["path"] for r in
                (db.one("SELECT path FROM canon_assets WHERE id=?", (i,)) for i in p.get("ref_ids", [])) if r]
        for aid in p.get("ref_artifact_ids") or []:   # referencje z galerii (np. poprawianie wybranego obrazu)
            ra = db.one("SELECT path FROM artifacts WHERE id=?", (aid,))
            if ra:
                refs.append(config.DATA / ra["path"])
        for rp in p.get("ref_paths") or []:   # referencje z plikow w data/ (np. obraz z biblioteki interakcji), po artefaktach
            full = (config.DATA / rp).resolve()
            if config.DATA.resolve() in full.parents and full.is_file():
                refs.append(full)
        src = None
        if p.get("source_artifact_id"):
            a = db.one("SELECT path FROM artifacts WHERE id=?", (p["source_artifact_id"],))
            src = config.DATA / a["path"] if a else None
        voice = dict(p.get("voice") or {})
        if voice.get("ref_artifact_id"):   # klon glosu: sciezka do nagrania wzorcowego
            ra = db.one("SELECT path FROM artifacts WHERE id=?", (voice["ref_artifact_id"],))
            voice["ref_path"] = str(config.DATA / ra["path"]) if ra else None
        end = None
        if p.get("end_artifact_id"):
            e = db.one("SELECT path FROM artifacts WHERE id=?", (p["end_artifact_id"],))
            end = config.DATA / e["path"] if e else None
        return GenRequest(
            kind=job["kind"], prompt=p["prompt"], fmt=p.get("fmt", "16:9"), model=job["model"] or None,
            refs=refs, source_image=src, end_image=end, voice=voice, duration=p.get("duration", config.VIDEO_DURATION),
            idem_key=job["idem_key"], safe_filter=bool(job["safe_filter"]), resume_id=job["workflow_id"],
            billing_mode=job_billing(job))

    def _run(self, job_id: int):
        job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("queued", "running"):
            return
        db.run("UPDATE jobs SET status='running', started=? WHERE id=?", (db.now(), job_id))
        try:
            req = self.build_request(job)
            res = self.provider.generate(
                req, on_remote_id=lambda rid: db.run("UPDATE jobs SET workflow_id=? WHERE id=?", (rid, job_id)))
            new_ids: list[int] = []
            for n, (data, ext) in enumerate(res.files):
                rel = Path("outputs") / f"job{job_id}_{n}.{ext}"
                sha = save_atomic(data, config.DATA / rel)
                kind = ("video" if ext in ("mp4", "webm", "mov") else
                        "audio" if ext in ("mp3", "wav", "flac", "m4a", "ogg") else "image")
                pj = json.loads(job["params"] or "{}")
                aid = db.run("INSERT INTO artifacts(job_id,shot_id,kind,path,sha256,label,created) VALUES(?,?,?,?,?,?,?)",
                             (job_id, job["shot_id"], kind, rel.as_posix(), sha, pj.get("label"), db.now()))
                new_ids.append(aid)
                if kind == "audio" and pj.get("adopt_voice_for"):
                    # zaprojektowana probka glosu -> klon z dokladnym transkryptem (spojny glos w kazdej kwestii)
                    ch = pj["adopt_voice_for"]
                    db.run("UPDATE characters SET voice=? WHERE id=?",
                           (json.dumps({"mode": "clone", "ref_artifact_id": aid, "transcript": pj["text"],
                                        "language": pj.get("language", "english")}), ch))
            db.run("UPDATE jobs SET status='done', finished=?, error=NULL WHERE id=?", (db.now(), job_id))
            for aid in new_ids:  # pomiar po oznaczeniu zadania jako gotowe; blad pomiaru nie psuje wyniku
                if db.one("SELECT kind FROM artifacts WHERE id=?", (aid,))["kind"] != "audio":
                    measure_artifact(aid, req.source_image)
        except Exception as e:  # noqa: BLE001 - blad zapisujemy przy zadaniu
            log.exception("job %s failed", job_id)
            db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
                   (db.now(), f"{type(e).__name__}: {e}", job_id))


def job_billing(job: dict) -> str:
    """billing_mode zadania: model poza planem -> "tokens" (Premium Spark), inaczej wartosc z konfiguracji.
    Glos (qwen3-tts-*) i zadania bez modelu ida wg konfiguracji (nie sa w rejestrze pod tymi nazwami)."""
    if job["kind"] in ("speech", "music") or not job["model"]:
        return config.SOGNI_BILLING_MODE
    return models.billing_for(job["model"], config.SOGNI_BILLING_MODE)


def canon_face_path(character_id: int) -> Path | None:
    a = db.one("SELECT path FROM canon_assets WHERE character_id=? AND approved=1 AND role='face' "
               "ORDER BY id LIMIT 1", (character_id,))
    return config.DATA / a["path"] if a else None


def measure_artifact(artifact_id: int, source: Path | None = None) -> dict | None:
    """Pomiar twarzy (InsightFace) i zapis w bazie. Obraz: podobienstwo do kanonu (twarz).
    Klip: srednia/minimum z 8 klatek wzgledem kadru zrodlowego (trend dryfu), a bez zrodla - wzgledem kanonu.
    Miara ORIENTACYJNA: na stylizowanych twarzach nie odroznia tej samej postaci od nowej o tym samym opisie,
    a kat kamery silnie obniza wynik. Nigdy nie rzuca wyjatku."""
    if not config.FACE_GUARD:
        return None
    try:
        from . import guard
        if not guard.available():
            return None
        a = db.one("SELECT a.*, s.character_id, s.partner_id FROM artifacts a JOIN shots s ON s.id=a.shot_id WHERE a.id=?",
                   (artifact_id,))
        if not a:
            return None
        if a["partner_id"]:   # ujecie pary: dwie liczby, kazda twarz dopasowana do blizszego kanonu (A albo B)
            return _measure_duet(a)
        path = config.DATA / a["path"]
        canon = canon_face_path(a["character_id"])
        if a["kind"] == "video":
            if source is None:  # np. pomiar na zadanie: kadr zrodlowy bierzemy z parametrow zadania
                job = db.one("SELECT params FROM jobs WHERE id=?", (a["job_id"],))
                sid = json.loads(job["params"]).get("source_artifact_id") if job else None
                src = db.one("SELECT path FROM artifacts WHERE id=?", (sid,)) if sid else None
                source = config.DATA / src["path"] if src else None
            ref = source or canon
            if not ref:
                return None
            r = guard.video_scores(path, ref, n=8)
            note = {"vs": "kadr zrodlowy" if source else "kanon", "frames": r["frames"]}
            score, low = r["mean"], r["min"]
        else:
            if not canon or canon.resolve() == path.resolve():
                return None
            score, low = guard.similarity(canon, path), None
            note = {"vs": "kanon (twarz)"}
        if score is None:
            note["reason"] = "brak wykrytej twarzy (np. widok z tylu)"
        db.run("UPDATE artifacts SET face_score=?, face_min=?, face_note=? WHERE id=?",
               (score, low, json.dumps(note), artifact_id))
        return {"score": score, "min": low, **note}
    except Exception:  # noqa: BLE001
        log.exception("pomiar twarzy nie powiodl sie dla artefaktu %s", artifact_id)
        return None


def _measure_duet(a: dict) -> dict | None:
    """Pomiar pary (guard.match_faces): A -> face_score/face_min, B -> face_score_b/face_min_b. Miara orientacyjna."""
    from . import guard
    def canon(cid):   # jak pipeline._face_asset: twarz, a przy braku - widok z przodu/3-4/sylwetka (wgrany obraz bez pelnego kanonu)
        for role in ("face", "front", "three_quarter", "body"):
            r = db.one("SELECT path FROM canon_assets WHERE character_id=? AND approved=1 AND role=? ORDER BY id LIMIT 1", (cid, role))
            if r:
                return config.DATA / r["path"]
        return None
    ca, cb = canon(a["character_id"]), canon(a["partner_id"])
    if not (ca or cb):
        return None
    path = config.DATA / a["path"]
    if a["kind"] == "video":
        r = guard.video_scores_duet(path, ca, cb, n=8)
        sa, la, sb, lb = r["mean_a"], r["min_a"], r["mean_b"], r["min_b"]
        note = {"vs": "kanon A i B (para)", "frames_a": r["frames_a"], "frames_b": r["frames_b"],
                "frames_with_both": r["frames_with_both"]}
    else:
        r = guard.similarity_duet(path, ca, cb)
        sa, la, sb, lb = r["a"], None, r["b"], None
        note = {"vs": "kanon A i B (para)", "faces": r["faces"]}
    if sa is None and sb is None:
        note["reason"] = "brak wykrytej twarzy (np. widok z tylu)"
    db.run("UPDATE artifacts SET face_score=?, face_min=?, face_score_b=?, face_min_b=?, face_note=? WHERE id=?",
           (sa, la, sb, lb, json.dumps(note), a["id"]))
    return {"score": sa, "min": la, "score_b": sb, "min_b": lb, **note}


def new_idem_key() -> str:
    return str(uuid.uuid4())
