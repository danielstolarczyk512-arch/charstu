"""Plansza porownawcza wynikow wielu modeli: python -m tests.make_sheet out.png etykieta=job_id ..."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

O = Path("data/outputs")
out = O / sys.argv[1]
items = [a.rsplit("=", 1) for a in sys.argv[2:]]
W, H, cols = 480, 270, 4
rows = (len(items) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, (H + 18) * rows), (30, 30, 30))
d = ImageDraw.Draw(sheet)
for i, (name, job) in enumerate(items):
    p = O / f"job{job}_0.png"
    im = Image.open(p).convert("RGB")
    size = im.size
    im.thumbnail((W, H))
    x, y = (i % cols) * W, (i // cols) * (H + 18)
    sheet.paste(im, (x, y + 18))
    d.text((x + 4, y + 3), f"{name}  {size[0]}x{size[1]}", fill=(255, 255, 255))
sheet.save(out)
print("zapisano", out)
