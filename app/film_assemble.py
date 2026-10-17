"""Montaz koncowy filmu: klipy w kolejnosci planu + normalizacja dzwieku + podklad + lektor + napisy (SRT / wypalone)."""
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path

from . import audio, config, db, film as F, stitch as st

log = logging.getLogger("assemble")


class AssembleError(Exception):
    pass


def libass_available() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(len(parts) > 1 and parts[1] == "subtitles" for parts in (l.split() for l in r.stdout.splitlines()))


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(entries: list[tuple[float, float, str]]) -> str:
    """entries: (start, end, tekst). Kolejnosc rosnaca, brak nakladania (koniec przycinany do poczatku nastepnego)."""
    out, n = [], 0
    for i, (a, b, text) in enumerate(entries):
        if not text.strip():
            continue
        nxt = entries[i + 1][0] if i + 1 < len(entries) else None
        if nxt is not None and b > nxt - 0.05:
            b = max(a + 0.4, nxt - 0.05)
        n += 1
        out.append(f"{n}\n{_ts(a)} --> {_ts(max(b, a + 0.4))}\n{text.strip()}\n")
    return "\n".join(out)


def burn(video: Path, srt: Path, out: Path):
    """Wypala napisy filtrem subtitles (libass). Uruchamiane w katalogu pliku, zeby uniknac problemow ze sciezkami Windows."""
    style = "FontSize=22,Outline=2,Shadow=0,MarginV=36,Alignment=2"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video.name, "-vf",
                        f"subtitles={srt.name}:force_style='{style}'", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", out.name], capture_output=True, text=True, cwd=str(video.parent))
    if r.returncode:
        raise AssembleError("ffmpeg (napisy): " + r.stderr[-300:])


def assemble(film_id: int, fade: float = 0.4, audio_mode: str = "normalize", bed_db: float = -20.0,
             subtitles: str = "sidecar", allow_partial: bool = False, voice_pad: float = 0.3) -> dict:
    film = F.get_film_row(film_id)
    shots = F.ordered_shots(film_id)
    if not shots:
        raise AssembleError("Film nie ma ujec")
    missing = [s["title"] or f"#{s['id']}" for s in shots if not s["clip_artifact_id"]]
    if missing and not allow_partial:
        raise AssembleError(f"Brak klipow dla ujec: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}. "
                            "Dokoncz produkcje albo zezwol na montaz czesciowy.")
    have = [s for s in shots if s["clip_artifact_id"]]
    if len(have) < 2:
        raise AssembleError("Do montazu potrzebne sa co najmniej 2 klipy")
    paths, voices, caps, idx_of = [], [], [], {}
    for i, s in enumerate(have):
        a = db.one("SELECT path FROM artifacts WHERE id=?", (s["clip_artifact_id"],))
        paths.append(config.DATA / a["path"])
        idx_of[s["id"]] = i
    bed = None
    if film["music_artifact_id"]:
        a = db.one("SELECT path FROM artifacts WHERE id=?", (film["music_artifact_id"],))
        bed = config.DATA / a["path"] if a else None
    for s in have:
        if s["speech_artifact_id"]:
            a = db.one("SELECT path FROM artifacts WHERE id=?", (s["speech_artifact_id"],))
            if a:
                voices.append((config.DATA / a["path"], idx_of[s["id"]]))

    shot_row = next((s["shot_row_id"] for s in have if s["shot_row_id"]), None)
    if shot_row is None:
        raise AssembleError("Brak wiersza ujecia (film nie byl produkowany przez program)")
    jid = db.run("INSERT INTO jobs(shot_id,kind,provider,model,params,status,idem_key,safe_filter,created,started) "
                 "VALUES(?,?,?,?,?,'running',?,1,?,?)",
                 (shot_row, "film", "local", "ffmpeg", json.dumps({"film_id": film_id, "fade": fade, "audio_mode": audio_mode}),
                  f"film-{film_id}-{int(db.now())}", db.now(), db.now()))
    out_rel = Path("outputs") / f"film_{film_id}_{jid}.mp4"
    out = config.DATA / out_rel
    try:
        info = st.assemble(paths, out, fade=fade, audio_mode=audio_mode, bed=bed, bed_db=bed_db, voices=voices,
                           voice_pad=voice_pad)
        starts = info["starts"]
        # napisy: kazda kwestia startuje przy swoim klipie (+ voice_pad); dlugosc z nagrania albo z dlugosci tekstu
        entries = []
        for i, s in enumerate(have):
            text = (s["dialogue"] or "").strip()
            if not text:
                continue
            clip_dur = st.probe(paths[i])["duration"]
            dur = None
            if s["speech_artifact_id"]:
                a = db.one("SELECT path FROM artifacts WHERE id=?", (s["speech_artifact_id"],))
                try:
                    dur = audio.duration(config.DATA / a["path"]) if a else None
                except audio.AudioError:
                    dur = None
            dur = dur or min(clip_dur - voice_pad, 1.5 + len(text) / 14)
            a0 = starts[i] + voice_pad
            entries.append((a0, a0 + dur, text))
        srt_rel = None
        if subtitles in ("sidecar", "burn") and entries:
            srt_rel = Path("outputs") / f"film_{film_id}_{jid}.srt"
            (config.DATA / srt_rel).write_text(build_srt(entries), encoding="utf-8")
            if subtitles == "burn":
                if libass_available():
                    burned = out.with_name(out.stem + "_sub.mp4")
                    burn(out, config.DATA / srt_rel, burned)
                    burned.replace(out)
                    info["subtitles"] = "wypalone"
                else:
                    info["subtitles"] = "sidecar (brak filtra subtitles/libass w ffmpeg)"
            else:
                info["subtitles"] = "sidecar"
        else:
            info["subtitles"] = "brak"
    except Exception as e:  # noqa: BLE001
        db.run("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?", (db.now(), str(e), jid))
        raise
    aid = db.run("INSERT INTO artifacts(job_id,shot_id,kind,path,label,created) VALUES(?,?,?,?,?,?)",
                 (jid, shot_row, "video", out_rel.as_posix(), "film: " + film["title"][:60], db.now()))
    db.run("UPDATE jobs SET status='done', finished=? WHERE id=?", (db.now(), jid))
    db.run("UPDATE films SET final_artifact_id=?, srt_path=?, updated=? WHERE id=?",
           (aid, srt_rel.as_posix() if srt_rel else None, db.now(), film_id))
    return {"artifact_id": aid, "path": out_rel.as_posix(), "srt": srt_rel.as_posix() if srt_rel else None,
            "clips": len(have), "missing": missing, **{k: info[k] for k in ("duration", "audio_mode", "subtitles") if k in info},
            "mixed_lufs": info.get("mixed_lufs"), "voices": len(voices), "bed": bool(bed)}


def start_assemble(film_id: int, **kw) -> threading.Thread:
    F.get_film_row(film_id)
    cur = db.one("SELECT assemble_state FROM films WHERE id=?", (film_id,))["assemble_state"] or ""
    if cur.startswith("assembling"):
        raise F.FilmError("Montaz juz trwa", 409)
    db.run("UPDATE films SET assemble_state='assembling' WHERE id=?", (film_id,))

    def work():
        try:
            res = assemble(film_id, **kw)
            db.run("UPDATE films SET assemble_state=? WHERE id=?", ("done: " + json.dumps(res, ensure_ascii=False), film_id))
        except Exception as e:  # noqa: BLE001
            log.exception("montaz filmu %s nie powiodl sie", film_id)
            db.run("UPDATE films SET assemble_state=? WHERE id=?", (f"error: {e}"[:400], film_id))

    t = threading.Thread(target=work, daemon=True, name=f"assemble-{film_id}")
    t.start()
    return t
