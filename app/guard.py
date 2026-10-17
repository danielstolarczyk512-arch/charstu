"""Straznik tozsamosci: podobienstwo twarzy (InsightFace buffalo_l, ArcFace) do kanonu.

Wagi modeli InsightFace sa na licencji niekomercyjnej - do uzytku osobistego. Brak twarzy (np. widok z tylu)
daje None i NIE oznacza porazki ujecia. Pomiar dotyczy tylko twarzy (nie stroju ani proporcji).
"""
import subprocess
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()
_app = None


def available() -> bool:
    try:
        import insightface  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _face_app():
    global _app
    with _lock:
        if _app is None:
            from insightface.app import FaceAnalysis
            fa = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
            fa.prepare(ctx_id=-1, det_size=(640, 640))
            _app = fa
        return _app


def embedding_bgr(img):
    """Embedding najwiekszej twarzy na obrazie BGR (numpy) albo None."""
    faces = _face_app().get(img)
    if not faces:
        return None
    f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    return f.normed_embedding


def embedding(path: Path):
    import cv2
    img = cv2.imread(str(path))
    return None if img is None else embedding_bgr(img)


def similarity(a, b) -> float | None:
    """Cosine dwoch embeddingow (lub sciezek do obrazow)."""
    ea = embedding(a) if isinstance(a, (str, Path)) else a
    eb = embedding(b) if isinstance(b, (str, Path)) else b
    if ea is None or eb is None:
        return None
    return float((ea * eb).sum())


def video_scores(video: Path, ref, n: int = 8) -> dict:
    """Podobienstwo twarzy w n rownomiernych klatkach klipu do referencji (sciezka lub embedding).
    Zwraca per-klatka liste (None = brak twarzy), srednia i minimum z klatek z twarza."""
    import cv2
    import numpy as np
    ref_e = embedding(ref) if isinstance(ref, (str, Path)) else ref
    if ref_e is None:
        return {"frames": [], "mean": None, "min": None, "reason": "brak twarzy w referencji"}
    with tempfile.TemporaryDirectory() as tmp:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True)
        dur = float(probe.stdout.strip() or 0)
        vals = []
        for i in range(n):
            f = Path(tmp) / f"{i}.png"
            t = max(0.0, (dur - 0.1) * i / (n - 1))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(f)],
                           capture_output=True)
            img = cv2.imread(str(f)) if f.exists() else None
            e = embedding_bgr(img) if img is not None else None
            vals.append(None if e is None else float(np.dot(ref_e, e)))
    got = [v for v in vals if v is not None]
    return {"frames": [None if v is None else round(v, 3) for v in vals],
            "mean": round(sum(got) / len(got), 3) if got else None,
            "min": round(min(got), 3) if got else None}


# ---------------- Duet: pomiar twarzy dla dwoch osob osobno ----------------
# NIE TESTOWANE na prawdziwych obrazach par (logika dopasowania sprawdzona testem na sztucznych wektorach).
# OGRANICZENIA: miara jest ORIENTACYJNA (jak w ETAP0_RAPORT.md: na stylizowanych twarzach nie odroznia tej samej postaci od nowej
# o tym samym opisie, a kat kamery obniza wynik); przy odwroconej twarzy (widok z tylu) detektor nie znajduje twarzy, wiec
# miara jest bezuzyteczna (None). Dwie podobne twarze (np. ta sama stylistyka) moga zostac zamienione miejscami - liczby
# nie rozstrzygaja, czy A i B nie zlaly sie w jedna osobe; to ocenia czlowiek.


def embeddings_all_bgr(img) -> list:
    """Embeddingi WSZYSTKICH wykrytych twarzy obrazu BGR, od najwiekszej (puste, gdy brak twarzy)."""
    faces = _face_app().get(img)
    faces = sorted(faces, key=lambda x: -((x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])))
    return [f.normed_embedding for f in faces]


def match_faces(embs: list, ea, eb) -> dict:
    """Dopasowuje wykryte twarze do kanonow A i B i zwraca dwie liczby (cosine) albo None.
    Jedna twarz: tylko do blizszego kanonu (drugi kanon = None). Dwie lub wiecej: najlepsze przypisanie rozlaczne
    (kazda twarz najwyzej raz), liczy sie para o najwyzszej sumie podobienstw."""
    def sim(x, y):   # iloczyn skalarny (embeddingi sa znormalizowane); dziala na numpy i na zwyklych listach
        return None if x is None or y is None else float(sum(float(p) * float(q) for p, q in zip(x, y)))
    if not embs or (ea is None and eb is None):
        return {"a": None, "b": None, "faces": len(embs)}
    if len(embs) == 1:
        sa, sb = sim(embs[0], ea), sim(embs[0], eb)
        if sa is not None and (sb is None or sa >= sb):
            return {"a": sa, "b": None, "faces": 1}
        return {"a": None, "b": sb, "faces": 1}
    best = None
    for i, fa in enumerate(embs):
        for j, fb in enumerate(embs):
            if i == j:
                continue
            sa, sb = sim(fa, ea), sim(fb, eb)
            tot = (sa if sa is not None else -1.0) + (sb if sb is not None else -1.0)
            if best is None or tot > best[0]:
                best = (tot, sa, sb)
    return {"a": best[1], "b": best[2], "faces": len(embs)}


def similarity_duet(img_path, canon_a, canon_b) -> dict:
    """Dwie liczby dla obrazu: {a, b, faces}. canon_a/canon_b = sciezki albo embeddingi (None = brak kanonu)."""
    import cv2
    img = cv2.imread(str(img_path))
    if img is None:
        return {"a": None, "b": None, "faces": 0}
    ea = embedding(canon_a) if isinstance(canon_a, (str, Path)) else canon_a
    eb = embedding(canon_b) if isinstance(canon_b, (str, Path)) else canon_b
    return match_faces(embeddings_all_bgr(img), ea, eb)


def video_scores_duet(video: Path, canon_a, canon_b, n: int = 8) -> dict:
    """Klip pary: w n klatkach dopasowanie twarzy do A i B osobno; srednia i minimum dla kazdej osoby."""
    import cv2
    ea = embedding(canon_a) if isinstance(canon_a, (str, Path)) else canon_a
    eb = embedding(canon_b) if isinstance(canon_b, (str, Path)) else canon_b
    with tempfile.TemporaryDirectory() as tmp:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True)
        dur = float(probe.stdout.strip() or 0)
        fa, fb, both = [], [], 0
        for i in range(n):
            f = Path(tmp) / f"{i}.png"
            t = max(0.0, (dur - 0.1) * i / (n - 1))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(f)],
                           capture_output=True)
            img = cv2.imread(str(f)) if f.exists() else None
            m = match_faces(embeddings_all_bgr(img), ea, eb) if img is not None else {"a": None, "b": None, "faces": 0}
            fa.append(m["a"])
            fb.append(m["b"])
            both += 1 if (m["a"] is not None and m["b"] is not None) else 0

    def agg(v):
        got = [x for x in v if x is not None]
        return (round(sum(got) / len(got), 3), round(min(got), 3)) if got else (None, None)
    (ma, mia), (mb, mib) = agg(fa), agg(fb)
    return {"frames_a": [None if x is None else round(x, 3) for x in fa], "frames_b": [None if x is None else round(x, 3) for x in fb],
            "mean_a": ma, "min_a": mia, "mean_b": mb, "min_b": mib, "frames_with_both": both, "frames": n}
