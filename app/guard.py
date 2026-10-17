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
