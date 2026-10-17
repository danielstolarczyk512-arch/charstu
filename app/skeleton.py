"""Szkielet pozy w stylu OpenPose (18 punktow COCO, kolorowe konczyny na czarnym tle) - obraz referencyjny pozy.

Punkty w ukladzie znormalizowanym 0..1 (x w prawo, y w dol) w kadrze o danych proporcjach. Nazwy wg COCO:
nose, neck, rsho, relb, rwri, lsho, lelb, lwri, rhip, rkne, rank, lhip, lkne, lank, reye, leye, rear, lear.
UWAGA: "r"/"l" to prawa/lewa strona POSTACI (nie ekranu).
"""
from PIL import Image, ImageDraw

LIMBS = [("neck", "rsho"), ("neck", "lsho"), ("rsho", "relb"), ("relb", "rwri"), ("lsho", "lelb"), ("lelb", "lwri"),
         ("neck", "rhip"), ("rhip", "rkne"), ("rkne", "rank"), ("neck", "lhip"), ("lhip", "lkne"), ("lkne", "lank"),
         ("neck", "nose"), ("nose", "reye"), ("reye", "rear"), ("nose", "leye"), ("leye", "lear")]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
          (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255),
          (255, 0, 170)]
NAMES = ["nose", "neck", "rsho", "relb", "rwri", "lsho", "lelb", "lwri", "rhip", "rkne", "rank", "lhip", "lkne", "lank",
         "reye", "leye", "rear", "lear"]


def render(points: dict[str, tuple[float, float]], size: tuple[int, int] = (1280, 720), thickness: int = 14) -> Image.Image:
    """Rysuje szkielet. Brakujace punkty (np. oczy/uszy) sa pomijane razem z konczynami, ktore ich wymagaja."""
    w, h = size
    img = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(img)
    px = {k: (v[0] * w, v[1] * h) for k, v in points.items() if v is not None}
    for (a, b), col in zip(LIMBS, COLORS):
        if a in px and b in px:
            d.line([px[a], px[b]], fill=tuple(int(c * 0.6) for c in col), width=thickness)
    r = thickness * 0.7
    for k, (x, y) in px.items():
        i = NAMES.index(k) if k in NAMES else 0
        d.ellipse([x - r, y - r, x + r, y + r], fill=COLORS[min(i, len(COLORS) - 1)])
    return img


def validate(points: dict) -> dict[str, tuple[float, float]]:
    """Czysci wejscie z interfejsu: tylko znane punkty, liczby w 0..1."""
    out = {}
    for k, v in (points or {}).items():
        if k in NAMES and isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                x, y = float(v[0]), float(v[1])
            except (TypeError, ValueError):
                continue
            out[k] = (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))
    return out


# Gotowe pozy (stojaca postac ok. 70% wysokosci kadru, srodek ok. x=0.5).
def _stand(cx=0.5, top=0.12):
    return {"nose": (cx, top + 0.03), "neck": (cx, top + 0.11), "rsho": (cx - 0.05, top + 0.12), "lsho": (cx + 0.05, top + 0.12),
            "relb": (cx - 0.06, top + 0.27), "lelb": (cx + 0.06, top + 0.27), "rwri": (cx - 0.06, top + 0.42), "lwri": (cx + 0.06, top + 0.42),
            "rhip": (cx - 0.03, top + 0.42), "lhip": (cx + 0.03, top + 0.42), "rkne": (cx - 0.035, top + 0.62), "lkne": (cx + 0.035, top + 0.62),
            "rank": (cx - 0.035, top + 0.84), "lank": (cx + 0.035, top + 0.84),
            "reye": (cx - 0.012, top + 0.02), "leye": (cx + 0.012, top + 0.02), "rear": (cx - 0.025, top + 0.03), "lear": (cx + 0.025, top + 0.03)}


def _p(**over):
    base = _stand()
    base.update(over)
    return base


PRESETS = {
    "stoi": _stand(),
    "rece_w_gore": _p(relb=(0.43, 0.2), lelb=(0.57, 0.2), rwri=(0.45, 0.07), lwri=(0.55, 0.07)),
    "rece_skrzyzowane": _p(relb=(0.45, 0.33), lelb=(0.55, 0.33), rwri=(0.54, 0.27), lwri=(0.46, 0.27)),
    "T": _p(relb=(0.38, 0.24), lelb=(0.62, 0.24), rwri=(0.27, 0.24), lwri=(0.73, 0.24)),
    "klek": {"nose": (0.5, 0.3), "neck": (0.5, 0.38), "rsho": (0.45, 0.39), "lsho": (0.55, 0.39), "relb": (0.43, 0.52),
             "lelb": (0.58, 0.5), "rwri": (0.46, 0.62), "lwri": (0.62, 0.62), "rhip": (0.47, 0.62), "lhip": (0.54, 0.62),
             "rkne": (0.40, 0.78), "lkne": (0.60, 0.74), "rank": (0.34, 0.9), "lank": (0.58, 0.92),
             "reye": (0.488, 0.285), "leye": (0.512, 0.285), "rear": (0.475, 0.3), "lear": (0.525, 0.3)},
    "siedzi": {"nose": (0.5, 0.3), "neck": (0.5, 0.38), "rsho": (0.45, 0.4), "lsho": (0.55, 0.4), "relb": (0.43, 0.54),
               "lelb": (0.57, 0.54), "rwri": (0.47, 0.62), "lwri": (0.53, 0.62), "rhip": (0.47, 0.64), "lhip": (0.53, 0.64),
               "rkne": (0.42, 0.74), "lkne": (0.58, 0.74), "rank": (0.42, 0.92), "lank": (0.58, 0.92),
               "reye": (0.488, 0.285), "leye": (0.512, 0.285), "rear": (0.475, 0.3), "lear": (0.525, 0.3)},
    "biegnie": {"nose": (0.5, 0.18), "neck": (0.5, 0.26), "rsho": (0.45, 0.27), "lsho": (0.55, 0.27), "relb": (0.4, 0.38),
                "lelb": (0.62, 0.34), "rwri": (0.43, 0.46), "lwri": (0.68, 0.27), "rhip": (0.47, 0.5), "lhip": (0.53, 0.5),
                "rkne": (0.38, 0.62), "lkne": (0.6, 0.64), "rank": (0.42, 0.78), "lank": (0.7, 0.8),
                "reye": (0.488, 0.165), "leye": (0.512, 0.165), "rear": (0.475, 0.18), "lear": (0.525, 0.18)},
    "luk": {"nose": (0.5, 0.15), "neck": (0.5, 0.23), "rsho": (0.45, 0.24), "lsho": (0.55, 0.24), "relb": (0.58, 0.24),
            "lelb": (0.72, 0.24), "rwri": (0.47, 0.25), "lwri": (0.84, 0.24), "rhip": (0.47, 0.5), "lhip": (0.53, 0.5),
            "rkne": (0.44, 0.7), "lkne": (0.56, 0.7), "rank": (0.42, 0.9), "lank": (0.58, 0.9),
            "reye": (0.488, 0.135), "leye": (0.512, 0.135), "rear": (0.475, 0.15), "lear": (0.525, 0.15)},
}
