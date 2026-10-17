"""Testy dzwieku na prawdziwych klipach i syntetycznym podkladzie: python -m tests.audio_test
(wymaga ffmpeg i klipow w data/outputs z Etapu 0)."""
import math
import subprocess
import tempfile
from pathlib import Path

from app import audio, stitch

O = Path("data/outputs")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


def ff(*args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])


tmp = Path(tempfile.mkdtemp(prefix="audio-test-"))
clips = [O / "job20_0.mp4", O / "job21_0.mp4", O / "job22_0.mp4"]
check("0 klipy testowe istnieja", all(c.exists() for c in clips))

# --- A. czyste funkcje ---
check("A1 gain: cichy klip jest wzmacniany do celu", abs(audio.clip_gain_db(-38.0) - 22.0) < 1e-6)
check("A2 gain: klip ponizej progu ciszy -> None", audio.clip_gain_db(-57.0) is None and audio.clip_gain_db(float("-inf")) is None)
check("A3 gain: ograniczony do +24 dB", audio.clip_gain_db(-45.0) == 24.0 or audio.clip_gain_db(-45.0) < 24.0)
check("A4 gain: glosny klip jest sciszany (min -20)", audio.clip_gain_db(-2.0) == -14.0)
check("A5 lancuch normalize dla ciszy = anullsrc", "anullsrc" in audio.clip_audio_chain(0, True, 5.0, "normalize", -60.0))
check("A6 lancuch mute = anullsrc", "anullsrc" in audio.clip_audio_chain(1, True, 5.0, "mute", -20.0))
check("A7 lancuch normalize ma volume + limiter", "volume=" in audio.clip_audio_chain(2, True, 5.0, "normalize", -30.0)
      and "alimiter" in audio.clip_audio_chain(2, True, 5.0, "normalize", -30.0))

# --- B. sklejanie z trybami dzwieku ---
before = [audio.loudness(c)["lufs"] for c in clips]
spread_before = max(before) - min(before)
for mode in ("keep", "normalize", "mute"):
    out = tmp / f"st_{mode}.mp4"
    info = stitch.stitch(clips, out, fade=0.5, audio_mode=mode)
    check(f"B1 sklejka audio_mode={mode} ma poprawna dlugosc", abs(info["duration"] - info["expected"]) < 0.15,
          f"{info['duration']} vs {info['expected']}")
    lu = audio.loudness(out)
    print(f"     {mode:9s} -> {lu['lufs']:.1f} LUFS, szczyt {lu['peak']:.1f} dBTP")
    if mode == "normalize":
        mean_before = sum(before) / len(before)
        check("B2 normalize: calosc glosniejsza niz oryginal (>= +10 LU)", lu["lufs"] > mean_before + 10,
              f"{lu['lufs']:.1f} LUFS vs srednia przed {mean_before:.1f}")
        check("B3 normalize: brak przesterowania (szczyt <= -0.5 dBTP)", lu["peak"] <= -0.5, lu["peak"])
    if mode == "mute":
        check("B4 mute: cisza", math.isinf(lu["lufs"]) or lu["lufs"] < -70, lu["lufs"])
check("B5 pomiar zwraca poczatki klipow", len(info["starts"]) == 3 and info["starts"][0] == 0.0)

# --- C. miks podkladu i lektora (syntetyczny podklad: ton + szum, synthetic voice: krotki ton) ---
bed = tmp / "bed.mp3"
ff("-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.05",
   "-filter_complex", "[0][1]amix=inputs=2:normalize=0", str(bed))
voice = tmp / "voice.wav"
ff("-f", "lavfi", "-i", "sine=frequency=500:duration=2.0", "-af", "volume=0.5", str(voice))
base = tmp / "st_normalize.mp4"
dur = stitch.probe(base)["duration"]
mixed = tmp / "mixed.mp4"
lu = audio.mix(base, mixed, dur, bed=bed, bed_db=-20, voices=[(voice, 1.0), (voice, 6.0)], duck=True)
mi = stitch.probe(mixed)
check("C1 miks: dlugosc zachowana", abs(mi["duration"] - dur) < 0.15, f"{mi['duration']} vs {dur}")
check("C2 miks: wideo bez zmian (wymiary)", (mi["width"], mi["height"]) == (1344, 768))
check("C3 miks: docelowa glosnosc ok. -16 LUFS (+-2)", abs(lu["lufs"] + 16) <= 2.0, f"{lu['lufs']:.1f}")
check("C4 miks: szczyt <= -1 dBTP", lu["peak"] <= -0.9, lu["peak"])
only_bed = tmp / "only_bed.mp4"
lu2 = audio.mix(base, only_bed, dur, bed=bed, bed_db=-20, voices=None)
check("C5 miks tylko z podkladem dziala", abs(lu2["lufs"] + 16) <= 2.0, f"{lu2['lufs']:.1f}")
try:
    audio.mix(base, tmp / "x.mp4", dur)
    check("C6 miks bez niczego -> blad", False)
except audio.AudioError:
    check("C6 miks bez niczego -> blad", True)

print(f"\nWYNIK: {sum(results)}/{len(results)} (rozrzut glosnosci klipow przed: {spread_before:.1f} LU)")
raise SystemExit(0 if all(results) else 1)
