"""Dzwiek: pomiar glosnosci (EBU R128), normalizacja klipow, podklad z wyciszaniem pod glos (ducking), kwestie lektora.

Wnioski z pomiaru klipow wygenerowanych przez LTX/H3 (16.10.2026): ich wbudowany dzwiek jest bardzo cichy
(od -57 LUFS do -33 LUFS, jeden klip calkowicie niemy) i rozny miedzy klipami, wiec samo sklejenie daje skoki glosnosci
i znikanie dzwieku. Dlatego: normalizacja do celu, klipy ponizej progu traktujemy jako ciszę (wzmacnianie szumu o 40 dB
nie ma sensu), a spojnosc zapewnia wspolny podklad i lektor jednym glosem.
"""
import json
import math
import re
import subprocess
from pathlib import Path

TARGET_LUFS = -16.0        # standard dla treści online (stereo)
SILENCE_FLOOR = -50.0      # ponizej: traktujemy jako brak uzytecznego dzwieku
MAX_GAIN_DB = 24.0
MIN_GAIN_DB = -20.0
# Limiter szczytow (alimiter). UWAGA: alimiter domyslnie ma level=enabled, czyli po limitowaniu podbija sygnal z powrotem do 0 dB
# (przez to dzwiek byl glosniejszy od celu o ok. 2 dB, a szczyty dochodzily do 0 dBTP) - dlatego zawsze level=disabled.
LIMIT = 0.89               # ok. -1 dBFS


class AudioError(Exception):
    pass


def loudness(path: Path) -> dict:
    """Zintegrowana glosnosc (LUFS), szczyt (dBTP) i zakres (LRA). LUFS = -inf oznacza cyfrowa cisze."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise AudioError("Nie udalo sie zmierzyc glosnosci: " + r.stderr[-200:])
    j = json.loads(m.group(0))
    return {"lufs": float(j["input_i"]), "peak": float(j["input_tp"]), "lra": float(j["input_lra"]),
            "thresh": float(j["input_thresh"]), "offset": float(j["target_offset"])}


def duration(path: Path) -> float:
    """Dlugosc pliku audio/wideo w sekundach (ffprobe)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError as e:
        raise AudioError(f"Nie udalo sie odczytac dlugosci: {path.name}") from e


def has_signal(lufs: float) -> bool:
    return lufs is not None and not math.isinf(lufs) and lufs > SILENCE_FLOOR


def clip_gain_db(lufs: float, target: float = TARGET_LUFS) -> float | None:
    """Wzmocnienie do celu albo None, gdy klip nie ma uzytecznego dzwieku (traktujemy jako cisze)."""
    if not has_signal(lufs):
        return None
    return max(MIN_GAIN_DB, min(MAX_GAIN_DB, target - lufs))


_FMT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def clip_audio_chain(idx: int, has_audio: bool, duration: float, mode: str, lufs: float | None) -> str:
    """Fragment filter_complex dla dzwieku jednego klipu: keep | normalize | mute."""
    silence = f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.3f}[a{idx}]"
    if mode == "mute" or not has_audio:
        return silence
    if mode == "normalize":
        g = clip_gain_db(lufs) if lufs is not None else None
        if g is None:
            return silence
        return f"[{idx}:a]{_FMT},volume={g:.2f}dB,alimiter=limit={LIMIT}:level=disabled[a{idx}]"
    return f"[{idx}:a]{_FMT}[a{idx}]"


def mix(base: Path, out: Path, duration: float, bed: Path | None = None, bed_db: float = -20.0,
        voices: list[tuple[Path, float]] | None = None, duck: bool = True, target: float = TARGET_LUFS) -> dict:
    """Miksuje sciezke klipu z podkladem (zapetlonym/przycietym do dlugosci wideo, wejscie/wyjscie plynne) i kwestiami
    (kazda od wskazanej sekundy). Podklad jest wyciszany pod kwestiami. Na koniec normalizacja do `target` LUFS."""
    voices = voices or []
    if not bed and not voices:
        raise AudioError("Nic do zmiksowania")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(base)]
    n = 1
    parts = [f"[0:a]{_FMT}[base]"]
    labels = ["[base]"]
    if bed:
        cmd += ["-stream_loop", "-1", "-i", str(bed)]
        fo = max(0.0, duration - 2.0)
        parts.append(f"[{n}:a]{_FMT},atrim=0:{duration:.3f},volume={bed_db}dB,afade=t=in:d=1.5,"
                     f"afade=t=out:st={fo:.3f}:d=2[bed]")
        n += 1
    vlabels = []
    for path, at in voices:
        cmd += ["-i", str(path)]
        ms = int(max(0.0, at) * 1000)
        parts.append(f"[{n}:a]{_FMT},adelay={ms}|{ms}[v{n}]")
        vlabels.append(f"[v{n}]")
        n += 1
    if vlabels:
        parts.append("".join(vlabels) + f"amix=inputs={len(vlabels)}:normalize=0:duration=longest[vsum]")
    if bed and vlabels and duck:   # podklad cichnie, gdy mowi lektor
        parts.append("[vsum]asplit=2[vkey][vout]")
        parts.append("[bed][vkey]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=450[bedd]")
        labels += ["[bedd]", "[vout]"]
    else:
        if bed:
            labels.append("[bed]")
        if vlabels:
            labels.append("[vsum]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,"
                 f"atrim=0:{duration:.3f}[aout]")
    # Przebieg 1: sam miks do pliku tymczasowego (bez normalizacji), pomiar glosnosci.
    tmp = out.with_suffix(".mix.wav")
    cmd1 = cmd + ["-filter_complex", ";".join(parts), "-map", "[aout]", "-c:a", "pcm_f32le", str(tmp)]
    r = subprocess.run(cmd1, capture_output=True, text=True)
    if r.returncode:
        raise AudioError("ffmpeg (miks): " + r.stderr[-500:])
    try:
        # Przebieg 2: dokladne wzmocnienie do celu (jednoprzebiegowy loudnorm chybial cel o ok. 3 LU) + limiter.
        m = loudness(tmp)
        if has_signal(m["lufs"]):
            # loudnorm liniowy z wartosciami z pomiaru: trafia w cel LUFS i pilnuje szczytu rzeczywistego (true-peak) -1,5 dBTP
            ln = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['lufs']}:measured_TP={m['peak']}:measured_LRA={m['lra']}:"
                  f"measured_thresh={m['thresh']}:offset={m['offset']}:linear=true,aresample=48000")
        else:
            ln = "anull"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(base), "-i", str(tmp),
                            "-filter_complex", f"[1:a]{ln},atrim=0:{duration:.3f}[a]",
                            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart", str(out)], capture_output=True, text=True)
        if r.returncode:
            raise AudioError("ffmpeg (finalizacja): " + r.stderr[-500:])
    finally:
        tmp.unlink(missing_ok=True)
    return loudness(out)
