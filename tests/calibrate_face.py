"""Kalibracja miary podobienstwa twarzy na wynikach Etapu 0: python -m tests.calibrate_face"""
from pathlib import Path

from app import guard

O = Path("data/outputs")

print("== klipy vs WLASNY kadr zrodlowy (ta sama poza na starcie) ==")
for n, src in [("job20_0", "job13_0.png"), ("exp_vid_A_ltx_i2v", "job13_0.png"), ("job21_0", "job14_0.png"),
               ("job22_0", "job18_0.png"), ("exp_vid_C_ltx_orbit", "job5_0.png")]:
    r = guard.video_scores(O / (n + ".mp4"), O / src, n=8)
    print(f"{n:20s} mean {r['mean']}  min {r['min']}  {r['frames']}")

print("== kontrole ==")
print("kanon (job5) vs job6 (front, INNY seed, ten sam opis):", round(guard.similarity(O / "job5_0.png", O / "job6_0.png"), 3))
print("3/4 (job13) vs profil (job14), ta sama postac (edycja):", round(guard.similarity(O / "job13_0.png", O / "job14_0.png"), 3))
