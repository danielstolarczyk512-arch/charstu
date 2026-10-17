"""Testy montazu filmu (mock + ffmpeg): python -m tests.film_assemble_test"""
import io
import json
import os
import tempfile
import time

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-asm-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import audio, config, db, film_assemble as FA, stitch as st  # noqa: E402
from app.main import app, state  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail else ""), flush=True)


# --- A. SRT ---
srt = FA.build_srt([(1.0, 3.0, "First line."), (2.9, 5.0, "Second line."), (8.0, 8.1, ""), (9.0, 9.2, "Short")])
blocks = [b for b in srt.strip().split("\n\n")]
check("A1 SRT: numeracja i format czasu", blocks[0].startswith("1\n00:00:01,000 --> 00:00:02,850"), blocks[0].replace("\n", " | "))
check("A2 SRT: pusty tekst pominiety, minimalna dlugosc 0,4 s", len(blocks) == 3 and "00:00:09,000 --> 00:00:09,400" in blocks[2], len(blocks))
check("A3 SRT: koniec przyciety do poczatku nastepnego (brak nakladania)", "00:00:02,850" in blocks[0])
check("A4 znaczniki czasu > 1 h", FA._ts(3725.5) == "01:02:05,500")
print("     libass dostepny:", FA.libass_available())

with TestClient(app) as c:
    state["producer"].interval = 0.3
    cid = c.post("/api/characters", json={"name": "A", "archetype": "adult hunter", "adult_fictional": True}).json()["id"]
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (9, 9, 9)).save(b, "PNG")
    c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"}, files={"file": ("f.png", b.getvalue(), "image/png")})
    fid = c.post("/api/films", json={"character_id": cid, "title": "Montaz", "music_prompt": "calm strings, instrumental"}).json()["film"]["id"]
    sc = c.post(f"/api/films/{fid}/scenes", json={"title": "S", "location": "cliff", "lighting": "dawn"}).json()["scenes"][0]["id"]
    for i, d in enumerate(("The road is long.", "", "We will not see it again.")):
        c.post(f"/api/scenes/{sc}/shots", json={"title": f"s{i}", "action": f"stands {i}", "dialogue": d, "duration": 5})

    r = c.post(f"/api/films/{fid}/assemble", json={})
    time.sleep(1.0)
    state_txt = db.one("SELECT assemble_state FROM films WHERE id=?", (fid,))["assemble_state"]
    check("B1 montaz bez klipow -> blad z lista brakujacych ujec", state_txt.startswith("error") and "Brak klipow" in state_txt, state_txt[:90])
    check("B2 zly parametr -> 400", c.post(f"/api/films/{fid}/assemble", json={"audio_mode": "x"}).status_code == 400)

    c.post(f"/api/films/{fid}/produce")
    end = time.time() + 240
    while time.time() < end and c.get(f"/api/films/{fid}").json()["film"]["status"] not in ("ready", "needs_attention"):
        time.sleep(0.5)
    check("B3 produkcja zakonczona", c.get(f"/api/films/{fid}").json()["film"]["status"] == "ready")

    def run_assemble(**kw):
        db.run("UPDATE films SET assemble_state=NULL WHERE id=?", (fid,))
        r = c.post(f"/api/films/{fid}/assemble", json=kw)
        assert r.status_code == 200, r.text
        end = time.time() + 180
        while time.time() < end:
            s = db.one("SELECT assemble_state FROM films WHERE id=?", (fid,))["assemble_state"] or ""
            if s.startswith(("done", "error")):
                return s
            time.sleep(0.4)
        return "timeout"

    s = run_assemble(fade=0.3, audio_mode="normalize", subtitles="sidecar")
    check("B4 montaz sidecar zakonczony", s.startswith("done"), s[:120])
    res = json.loads(s[6:])
    out = config.DATA / res["path"]
    check("B5 plik filmu istnieje, 3 klipy, podklad i 2 kwestie", out.exists() and res["clips"] == 3 and res["bed"] and res["voices"] == 2, res)
    exp = 3 * 5 - 2 * 0.3
    check("B6 dlugosc = suma klipow - przenikania", abs(st.probe(out)["duration"] - exp) < 0.4, f"{st.probe(out)['duration']:.2f} vs {exp:.2f}")
    check("B7 glosnosc ok. -16 LUFS", res["mixed_lufs"] is not None and abs(res["mixed_lufs"] + 16) <= 3, res["mixed_lufs"])
    tree = c.get(f"/api/films/{fid}").json()
    check("B8 film zapamietuje wynik (final + srt)", tree["film"]["final"]["id"] == res["artifact_id"] and tree["film"]["srt_path"], tree["film"]["srt_path"])
    srt_txt = (config.DATA / res["srt"]).read_text(encoding="utf-8")
    check("B9 SRT: dwie kwestie, pierwsza przy poczatku klipu + 0,3 s", srt_txt.count("-->") == 2 and "00:00:00,300" in srt_txt, srt_txt.replace("\n", " | ")[:140])
    check("B10 napisy w kolejnosci i z tekstem", "The road is long." in srt_txt and "We will not see it again." in srt_txt)

    s = run_assemble(fade=0.0, audio_mode="mute", subtitles="none")
    res2 = json.loads(s[6:]) if s.startswith("done") else {}
    check("B11 montaz bez napisow, tryb mute (podklad + lektor zostaja)", s.startswith("done") and res2.get("subtitles") == "brak" and res2.get("srt") is None, s[:100])

    if FA.libass_available():
        s = run_assemble(subtitles="burn")
        res3 = json.loads(s[6:]) if s.startswith("done") else {}
        check("B12 napisy wypalone (libass)", s.startswith("done") and res3.get("subtitles") == "wypalone", s[:120])
    else:
        s = run_assemble(subtitles="burn")
        res3 = json.loads(s[6:]) if s.startswith("done") else {}
        check("B12 brak libass -> czytelny fallback do sidecar", s.startswith("done") and "sidecar" in res3.get("subtitles", ""), res3.get("subtitles"))

    # montaz czesciowy: usuwamy klip jednego ujecia
    first = tree["scenes"][0]["shots"][1]
    db.run("UPDATE film_shots SET clip_artifact_id=NULL WHERE id=?", (first["id"],))
    s = run_assemble(subtitles="none")
    check("B13 brak klipu bez allow_partial -> blad", s.startswith("error") and "Brak klipow" in s, s[:100])
    s = run_assemble(subtitles="none", allow_partial=True)
    res4 = json.loads(s[6:]) if s.startswith("done") else {}
    check("B14 allow_partial: 2 klipy, lista pominietych", res4.get("clips") == 2 and len(res4.get("missing", [])) == 1, res4.get("missing"))

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
