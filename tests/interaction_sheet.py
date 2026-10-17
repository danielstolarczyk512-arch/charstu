"""Arkusz obrazow pozycji biblioteki interakcji: jeden obraz na pozycje, generowany modelem z planu i podlaczany jako domyslny
obraz pozycji (data/interactions, pole interactions.image_path). Uzycie (program musi dzialac, STUDIO_URL domyslnie localhost:8000):
  python -m tests.interaction_sheet                 wszystkie pozycje
  python -m tests.interaction_sheet kiss            tylko jedna pozycja (powtorzenie wyrzuconej)
Zmienne: DUET_SHEET_MODEL (domyslnie qwen-2512; model z planu), DUET_SHEET_STYLE (dopisek do promptu, domyslnie neutralny:
"plain studio background, full body, both heads clearly visible").
Prompt powstaje WYLACZNIE z opisu i frazy anatomii pozycji zapisanych w bazie (edytujesz je w oknie Duet), wiec zakres tresci
obrazu ustawiasz tam i w DUET_SHEET_STYLE - skrypt niczego od siebie nie dopisuje. Obrazy maja byc wygenerowane (nie zdjecia
prawdziwych osob). Obraz mozna potem podmienic w oknie Duet ("Dodaj pozycje" / obraz pozycji) albo przez API.
STATUS: skrypt NIE byl uruchamiany w ramach etapu E5 (nie renderowalem scen jednoznacznie seksualnych); logika zlecania jest ta
sama co w tests/duet_live.py (komenda `pose`), ktora dzialala na ubranych parach. Hipoteza "obraz pozycji z nagoscia przenosi
nagosc na wynik" jest NIEZWERYFIKOWANA."""
import os
import sys
import time

import httpx

B = os.getenv("STUDIO_URL", "http://localhost:8000")
MODEL = os.getenv("DUET_SHEET_MODEL", "qwen-2512")
STYLE = os.getenv("DUET_SHEET_STYLE", "plain studio background, full body, both heads clearly visible")
c = httpx.Client(base_url=B, timeout=120)


def wait(job_ids, timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        jobs = {j["id"]: j for j in c.get("/api/jobs").json()}
        if all(i in jobs and jobs[i]["status"] in ("done", "failed") for i in job_ids):
            return [jobs[i] for i in job_ids]
        time.sleep(4)
    raise TimeoutError("zadanie nie skonczylo sie w czasie")


def holder() -> int:
    """Postac pomocnicza 'Poza' (generowanie obrazu bez kanonu); tworzona raz."""
    for ch in c.get("/api/characters").json():
        if ch["name"] == "Poza":
            return ch["id"]
    r = c.post("/api/characters", json={"name": "Poza", "archetype": "two adult people", "traits": "neutral faces",
                                        "outfit": "", "style": "photographic", "adult_fictional": True})
    r.raise_for_status()
    return r.json()["id"]


def make(item: dict, cid: int):
    text = ", ".join(t.strip().rstrip(".") for t in (item["description"], item.get("anatomy") or "", STYLE) if t and t.strip())
    sid = c.post("/api/shots", json={"character_id": cid, "az": 0, "el": 5, "dist": 6.0, "fov": 35, "fmt": "16:9",
                                     "action": text, "outfit": ""}).json()["id"]
    r = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": MODEL, "count": 1})
    r.raise_for_status()
    (job,) = wait(r.json()["jobs"])
    if job["status"] != "done":
        print(item["slug"], "BLAD:", job["error"])
        return
    art = [x for x in c.get(f"/api/artifacts?character_id={cid}").json() if x["shot_id"] == sid][0]
    data = httpx.get(B + "/files/" + art["path"], timeout=60).content
    up = c.post(f"/api/duet/interactions/{item['slug']}/image", files={"file": (item["slug"] + ".png", data, "image/png")})
    print(item["slug"], "obraz pozycji ustawiony" if up.status_code == 200 else f"blad wgrania {up.status_code}")


def main(a):
    items = c.get("/api/duet/interactions").json()
    if a:
        items = [i for i in items if i["slug"] == a[0] or i["name"] == a[0]]
        if not items:
            raise SystemExit("Nie ma takiej pozycji: " + a[0])
    cid = holder()
    for it in items:
        make(it, cid)


if __name__ == "__main__":
    main(sys.argv[1:])
