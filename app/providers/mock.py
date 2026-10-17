"""Dostawca testowy: obrazy zastepcze i klip z ffmpeg. Nie wymaga konta ani sieci."""
import hashlib
import io
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

from PIL import Image, ImageDraw

from .base import GenRequest, GenResult, Provider, ProviderError


def _size(fmt: str):
    return (1024, 576) if fmt == "16:9" else (576, 1024)


def _frame(req: GenRequest, shade: int, label: str) -> Image.Image:
    w, h = _size(req.fmt)
    digest = hashlib.sha256((req.prompt + str(shade)).encode()).digest()
    base = (40 + digest[0] // 3, 40 + digest[1] // 3, 60 + digest[2] // 3)
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2
    d.ellipse([cx - 40, cy - 190, cx + 40, cy - 110], fill=(190, 190, 190))
    d.rounded_rectangle([cx - 70, cy - 100, cx + 70, cy + 70], 20, fill=(150, 150, 150))
    d.rectangle([cx - 55, cy + 70, cx - 10, cy + 200], fill=(130, 130, 130))
    d.rectangle([cx + 10, cy + 70, cx + 55, cy + 200], fill=(130, 130, 130))
    text = f"[MOCK {req.kind}] " + req.prompt
    d.multiline_text((16, 12), "\n".join(textwrap.wrap(text, 60)[:8]), fill=(235, 235, 235))
    d.text((16, h - 24), label, fill=(235, 235, 235))
    return img


class MockProvider(Provider):
    name = "mock"

    def generate(self, req: GenRequest, on_remote_id=None) -> GenResult:
        time.sleep(1.0)
        rid = "mock-" + hashlib.sha1(req.idem_key.encode()).hexdigest()[:10]
        if on_remote_id:
            on_remote_id(rid)
        if req.kind in ("image", "edit"):
            buf = io.BytesIO()
            _frame(req, 0, f"refs={len(req.refs)} filter={req.safe_filter}").save(buf, "PNG")
            return GenResult([(buf.getvalue(), "png")], rid, {"mock": True})
        if not shutil.which("ffmpeg"):
            raise ProviderError("Brak ffmpeg w PATH (potrzebny do klipu testowego).")
        if req.kind in ("music", "speech"):   # dzwiek testowy: ton o dlugosci zaleznej od tekstu/zadania
            secs = max(10, req.duration) if req.kind == "music" else max(2, min(20, len(req.prompt) // 12))
            freq = 220 if req.kind == "music" else 440 + (len(req.voice.get("voice", "")) * 20)
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "a.wav"
                r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                    f"sine=frequency={freq}:duration={secs}", "-af", "volume=0.3", str(out)],
                                   capture_output=True, text=True)
                if r.returncode:
                    raise ProviderError("ffmpeg: " + r.stderr[-300:])
                return GenResult([(out.read_bytes(), "wav")], rid, {"mock": True})
        with tempfile.TemporaryDirectory() as tmp:
            n = max(24, req.duration * 8)
            for i in range(n):
                _frame(req, i, f"klatka {i + 1}/{n}").save(Path(tmp) / f"f{i:04d}.png")
            out = Path(tmp) / "out.mp4"
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "8", "-i",
                 str(Path(tmp) / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
                capture_output=True, text=True)
            if r.returncode:
                raise ProviderError("ffmpeg: " + r.stderr[-300:])
            return GenResult([(out.read_bytes(), "mp4")], rid, {"mock": True})

    def estimate(self, req: GenRequest) -> dict:
        return {"supported": True, "estimatedCapacity": 0, "note": "mock"}
