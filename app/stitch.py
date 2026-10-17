"""Sklejanie klipow (ffmpeg) z normalizacja rozmiaru, FPS, formatu pikseli i audio + metryki skoku na granicach."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from . import audio


class StitchError(Exception):
    pass


def _need(tool: str):
    if not shutil.which(tool):
        raise StitchError(f"Brak {tool} w PATH")


def probe(path: Path) -> dict:
    _need("ffprobe")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise StitchError(f"ffprobe: {r.stderr[-200:]}")
    j = json.loads(r.stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    if not v:
        raise StitchError(f"{path.name}: brak strumienia wideo")
    return {"width": v["width"], "height": v["height"], "duration": float(j["format"]["duration"]),
            "has_audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def stitch(paths: list[Path], out: Path, fade: float = 0.0, fps: int = 24, size: tuple[int, int] | None = None,
           audio_mode: str = "keep") -> dict:
    """Skleja klipy. fade=0 -> twarde ciecie; fade>0 -> przenikanie obrazu i dzwieku (sekundy)."""
    _need("ffmpeg")
    if len(paths) < 2:
        raise StitchError("Potrzebne co najmniej 2 klipy")
    infos = [probe(p) for p in paths]
    w, h = size or (infos[0]["width"], infos[0]["height"])
    w, h = w - w % 2, h - h % 2
    fade = max(0.0, fade)
    if fade and any(i["duration"] <= fade * 2 for i in infos):
        raise StitchError("Przenikanie dluzsze niz polowa klipu")
    if audio_mode not in ("keep", "normalize", "mute"):
        raise StitchError("audio_mode: keep, normalize albo mute")
    lufs: list[float | None] = [None] * len(paths)
    measured: list[dict | None] = [None] * len(paths)
    if audio_mode == "normalize":
        for k, (p, info) in enumerate(zip(paths, infos)):
            if info["has_audio"]:
                measured[k] = audio.loudness(p)
                lufs[k] = measured[k]["lufs"]

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in paths:
        cmd += ["-i", str(p)]
    parts, vlab, alab = [], [], []
    for i, info in enumerate(infos):
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
        # dzwiek klipu: keep / normalize (do -16 LUFS; klipy bez uzytecznego dzwieku -> cisza) / mute;
        # brak audio w klipie -> cisza o tej samej dlugosci, zeby nie rozjechac synchronizacji
        parts.append(audio.clip_audio_chain(i, info["has_audio"], info["duration"], audio_mode, lufs[i]))
        vlab.append(f"[v{i}]")
        alab.append(f"[a{i}]")

    if fade <= 0:
        parts.append("".join(f"{v}{a}" for v, a in zip(vlab, alab)) + f"concat=n={len(paths)}:v=1:a=1[v][a]")
        total = sum(i["duration"] for i in infos)
    else:
        cur_v, cur_a, elapsed = "v0", "a0", infos[0]["duration"]
        for i in range(1, len(paths)):
            off = elapsed - fade
            parts.append(f"[{cur_v}][v{i}]xfade=transition=fade:duration={fade}:offset={off:.3f}[xv{i}]")
            parts.append(f"[{cur_a}][a{i}]acrossfade=d={fade}[xa{i}]")
            cur_v, cur_a = f"xv{i}", f"xa{i}"
            elapsed = off + infos[i]["duration"]
        parts.append(f"[{cur_v}]null[v]")
        parts.append(f"[{cur_a}]anull[a]")
        total = elapsed

    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise StitchError("ffmpeg: " + r.stderr[-500:])
    res = probe(out)
    starts, t = [], 0.0   # poczatki klipow na osi czasu (do ustawiania kwestii lektora)
    for info in infos:
        starts.append(round(t, 3))
        t += info["duration"] - fade
    return {"duration": res["duration"], "expected": round(total, 2), "width": res["width"], "height": res["height"],
            "clips": len(paths), "fade": fade, "audio_mode": audio_mode, "starts": starts,
            "clip_lufs": [None if m is None else m["lufs"] for m in measured]}


def assemble(paths: list[Path], out: Path, fade: float = 0.0, audio_mode: str = "keep", bed: Path | None = None,
             bed_db: float = -20.0, voices: list[tuple[Path, int]] | None = None, voice_pad: float = 0.3,
             duck: bool = True) -> dict:
    """Sklejka + sciezka dzwiekowa: normalizacja/wyciszenie dzwieku klipow, podklad (wyciszany pod lektorem)
    i kwestie lektora. voices: lista (plik audio, numer klipu); kwestia startuje `voice_pad` s po poczatku klipu."""
    if not bed and not voices:
        return stitch(paths, out, fade, audio_mode=audio_mode)
    base = out.with_suffix(".base.mp4")
    info = stitch(paths, base, fade, audio_mode=audio_mode)
    try:
        placed = [(p, info["starts"][min(ci, len(paths) - 1)] + voice_pad) for p, ci in (voices or [])]
        lu = audio.mix(base, out, info["duration"], bed=bed, bed_db=bed_db, voices=placed, duck=duck)
    except audio.AudioError as e:
        raise StitchError(str(e)) from e
    finally:
        base.unlink(missing_ok=True)
    info.update({"mixed_lufs": lu["lufs"], "mixed_peak": lu["peak"], "voices": len(voices or []), "bed": bool(bed),
                 "duration": probe(out)["duration"]})
    return info


def frame_at(path: Path, t: float, dest: Path):
    """Klatka w czasie t. Gdy t wypada za ostatnia klatka (np. klip o niskim FPS, nominalny koniec dalej niz ostatnia
    klatka), probuje wczesniejszych czasow."""
    _need("ffmpeg")
    last_err = ""
    for tt in (t, t - 0.12, t - 0.25, t - 0.5, 0.0):
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(tt, 0):.3f}", "-i", str(path),
                            "-frames:v", "1", str(dest)], capture_output=True, text=True)
        if r.returncode == 0 and dest.exists():
            return
        last_err = r.stderr[-200:]
    raise StitchError("Nie udalo sie wyciagnac klatki: " + last_err)


def boundary_jump(a: Path, b: Path) -> dict:
    """Skala skoku miedzy ostatnia klatka A i pierwsza klatka B (0 = identyczne, 255 = maksymalny).
    To miara wizualna (kolor/kompozycja), NIE miara tozsamosci twarzy."""
    with tempfile.TemporaryDirectory() as tmp:
        fa, fb = Path(tmp) / "a.png", Path(tmp) / "b.png"
        frame_at(a, probe(a)["duration"] - 0.1, fa)
        frame_at(b, 0.0, fb)
        ia = Image.open(fa).convert("RGB").resize((160, 90))
        ib = Image.open(fb).convert("RGB").resize((160, 90))
        diff = ImageChops.difference(ia, ib)
        mad = sum(ImageStat.Stat(diff).mean) / 3
        ma, mb = ImageStat.Stat(ia).mean, ImageStat.Stat(ib).mean
        color = sum(abs(x - y) for x, y in zip(ma, mb)) / 3
    return {"pixel_diff": round(mad, 1), "color_shift": round(color, 1)}


def face_similarity(a_img: Path, b_img: Path) -> float | None:
    """Podobienstwo twarzy (cosine) przez InsightFace, jesli jest zainstalowany; inaczej None.
    Uwaga: wagi modeli InsightFace sa na licencji niekomercyjnej. Dziala zle dla widokow z tylu."""
    from . import guard
    return guard.similarity(a_img, b_img) if guard.available() else None


def contact_sheet(path: Path, out: Path, n: int = 5, width: int = 480):
    """Plansza klatek rownomiernie z calego klipu do przegladu dryfu tozsamosci."""
    d = probe(path)["duration"]
    with tempfile.TemporaryDirectory() as tmp:
        imgs = []
        for i in range(n):
            f = Path(tmp) / f"{i}.png"
            frame_at(path, (d - 0.15) * i / (n - 1), f)
            im = Image.open(f).convert("RGB")
            imgs.append(im.resize((width, int(im.height * width / im.width))))
    sheet = Image.new("RGB", (sum(i.width for i in imgs), max(i.height for i in imgs)))
    x = 0
    for im in imgs:
        sheet.paste(im, (x, 0))
        x += im.width
    sheet.save(out)
