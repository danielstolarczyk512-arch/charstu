import tempfile
from pathlib import Path

from app import stitch
from app.providers.base import GenRequest
from app.providers.mock import MockProvider

res = MockProvider().generate(GenRequest(kind="video", prompt="x", duration=5, idem_key="k"))
p = Path(tempfile.mkdtemp()) / "m.mp4"
p.write_bytes(res.files[0][0])
info = stitch.probe(p)
print("probe:", info)
for t in (0.0, info["duration"] - 0.1, info["duration"] - 0.2, info["duration"] / 2):
    d = p.with_name(f"f{t:.2f}.png")
    try:
        stitch.frame_at(p, t, d)
        print(f"t={t:.3f} OK")
    except Exception as e:
        print(f"t={t:.3f} BLAD: {e!r}")
