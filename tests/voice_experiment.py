"""Eksperyment spojnosci glosu na prawdziwym Sogni: python -m tests.voice_experiment
Przyblizenie obiektywne: mediana F0 (wysokosc glosu) i srodek ciezkosci widma kwestii. NIE zastepuje sluchania."""
import statistics
import subprocess
import sys
import uuid
from pathlib import Path

import numpy as np

from app import config
from app.providers.base import GenRequest
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
LINES = ["The road ahead is long, but we have walked longer ones.",
         "Do not fear the dark; it only hides what the light has not yet reached.",
         "Remember this valley, for we will not see it again."]
PASSAGE = ("The morning light spread slowly across the quiet valley, and a gentle wind moved through the tall grass. "
           "She paused for a moment, listened to the distant river, and then continued along the narrow path "
           "toward the village, where the first lanterns were already being lit.")
DESC = "A warm, low-pitched male narrator in his forties, calm and steady"


def speak(name, text, voice):
    res = p.generate(GenRequest(kind="speech", prompt=text, voice=voice, idem_key=str(uuid.uuid4())))
    data, ext = res.files[0]
    path = O / f"exp_voice_{name}.{ext}"
    path.write_bytes(data)
    return path


def decode(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32), sr


def f0_stats(path):
    x, sr = decode(path)
    n, hop = int(0.04 * sr), int(0.01 * sr)
    f0s, cents = [], []
    lo, hi = int(sr / 400), int(sr / 70)
    thr = 0.1 * float(np.max(np.abs(x)) + 1e-9)
    for i in range(0, len(x) - n, hop):
        fr = x[i:i + n]
        if np.sqrt(np.mean(fr ** 2)) < thr * 0.4:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[n - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.45:       # dzwieczne ramki
            f0s.append(sr / k)
        spec = np.abs(np.fft.rfft(fr * np.hanning(n)))
        freqs = np.fft.rfftfreq(n, 1 / sr)
        cents.append(float((spec * freqs).sum() / (spec.sum() + 1e-9)))
    return {"f0": round(statistics.median(f0s), 1) if f0s else None, "centroid": round(statistics.median(cents), 0) if cents else None,
            "dur": round(len(x) / sr, 1), "voiced_frames": len(f0s)}


def report(title, rows):
    print(f"\n== {title} ==")
    for n, st in rows:
        print(f"  {n:22s} F0 {st['f0']} Hz | centroid {st['centroid']} Hz | {st['dur']} s")
    f = [st["f0"] for _, st in rows if st["f0"]]
    if len(f) > 1:
        print(f"  rozrzut F0: {max(f) - min(f):.1f} Hz (odchylenie {statistics.pstdev(f):.1f})")
    return f


# A. glos studyjny: 3 kwestie, ten sam mowca
A = [(f"studio ryan #{i + 1}", f0_stats(speak(f"ryan{i + 1}", t, {"mode": "voice", "voice": "ryan", "language": "english"})))
     for i, t in enumerate(LINES)]
fa = report("A. glos studyjny (ryan), 3 kwestie", A)

# B. projekt raz + klon (zalecane przez dokumentacje Sogni)
ref = speak("design_ref", PASSAGE, {"mode": "design", "description": DESC, "language": "english"})
B = [("probka (design)", f0_stats(ref))]
for i, t in enumerate(LINES[:3]):
    B.append((f"klon #{i + 1}", f0_stats(speak(f"clone{i + 1}", t, {"mode": "clone", "ref_path": str(ref), "transcript": PASSAGE, "language": "english"}))))
fb = report("B. projekt raz + klon", B)

# C. projekt osobno dla kazdej kwestii (ostrzezenie w dokumentacji: za kazdym razem inny mowca)
C = [(f"design osobno #{i + 1}", f0_stats(speak(f"design{i + 1}", t, {"mode": "design", "description": DESC, "language": "english"})))
     for i, t in enumerate(LINES)]
fc = report("C. design osobno dla kazdej kwestii", C)

print("\nPODSUMOWANIE rozrzutu F0 miedzy kwestiami (mniej = spojniej):")
for lab, f in (("A studio", fa), ("B klon (kwestie)", [st['f0'] for n, st in B[1:] if st['f0']]), ("C design osobno", fc)):
    if len(f) > 1:
        print(f"  {lab:18s} {max(f) - min(f):6.1f} Hz")
