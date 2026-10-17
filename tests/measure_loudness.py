"""Pomiar glosnosci klipow (EBU R128 przez ffmpeg loudnorm): python -m tests.measure_loudness plik1.mp4 plik2.mp4 ..."""
import json
import re
import subprocess
import sys


def loudness(path: str) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
                        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return {"error": r.stderr[-200:]}
    j = json.loads(m.group(0))
    return {"LUFS": float(j["input_i"]), "peak_dBTP": float(j["input_tp"]), "LRA": float(j["input_lra"])}


if __name__ == "__main__":
    rows = [(p, loudness(p)) for p in sys.argv[1:]]
    for p, d in rows:
        print(f"{p.split('/')[-1].split(chr(92))[-1]:28s}", d)
    lufs = [d["LUFS"] for _, d in rows if "LUFS" in d]
    if len(lufs) > 1:
        print(f"\nrozrzut glosnosci: {max(lufs) - min(lufs):.1f} LU (min {min(lufs):.1f}, max {max(lufs):.1f})")
