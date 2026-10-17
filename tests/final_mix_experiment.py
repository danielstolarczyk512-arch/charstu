"""Prawdziwa muzyka (Sogni) + prawdziwy lektor (klon) + prawdziwe klipy: python -m tests.final_mix_experiment"""
import uuid
from pathlib import Path

from app import audio, config, stitch
from app.providers.base import GenRequest
from app.providers.sogni import SogniProvider

O = config.DATA / "outputs"
p = SogniProvider()
res = p.generate(GenRequest(kind="music", prompt="calm cinematic fantasy underscore, soft strings and harp, 70 BPM, D minor, "
                                                 "instrumental, no vocals", duration=20, idem_key=str(uuid.uuid4())))
data, ext = res.files[0]
bed = O / f"exp_music.{ext}"
bed.write_bytes(data)
print("muzyka:", ext, len(data) // 1024, "KB", audio.loudness(bed))

clips = [O / "job20_0.mp4", O / "job21_0.mp4", O / "job22_0.mp4"]
voices = [(O / f"exp_voice_clone{i + 1}.wav", i) for i in range(3)]
for name, kw in (("A_native_keep", dict(audio_mode="keep")),
                 ("B_normalize_only", dict(audio_mode="normalize")),
                 ("C_bed+voice_mute", dict(audio_mode="mute", bed=bed, voices=voices, bed_db=-18)),
                 ("D_bed+voice_normalize", dict(audio_mode="normalize", bed=bed, voices=voices, bed_db=-18))):
    out = O / f"exp_final_{name}.mp4"
    info = stitch.assemble(clips, out, fade=0.4, **kw)
    lu = audio.loudness(out)
    print(f"{name:24s} {info['duration']:.2f}s  {lu['lufs']:.1f} LUFS  peak {lu['peak']:.1f} dBTP  LRA {lu['lra']:.1f}")
