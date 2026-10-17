"""Plansza klatek gotowego filmu: python -m tests.film_sheet <plik.mp4> <wyjscie.png> [n]"""
import sys
import tempfile
from pathlib import Path

from PIL import Image

from app import stitch

src, out = Path(sys.argv[1]), Path(sys.argv[2])
n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
d = stitch.probe(src)["duration"]
with tempfile.TemporaryDirectory() as tmp:
    ims = []
    for i in range(n):
        f = Path(tmp) / f"{i}.png"
        stitch.frame_at(src, (d - 0.2) * (i + 0.5) / n, f)
        im = Image.open(f).convert("RGB")
        im.thumbnail((480, 270))
        ims.append(im)
cols = 4
rows = (n + cols - 1) // cols
w, h = ims[0].size
sheet = Image.new("RGB", (w * cols, h * rows))
for i, im in enumerate(ims):
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(out)
print("zapisano", out, f"({d:.1f} s)")
