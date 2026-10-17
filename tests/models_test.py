"""Testy wyboru modelu i promptow per model (dostawca mock, bez konta): python -m tests.models_test"""
import io
import os
import tempfile

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-models-")
os.environ["PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import models, prompts  # noqa: E402
from app.main import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""), flush=True)


C = {"archetype": "adult huntress", "traits": "long silver braid, green eyes", "outfit": "green cloak and leather armor",
     "style": "cinematic fantasy, soft light"}
SHOT = {"az": 40, "el": 5, "dist": 4.5, "fov": 35, "action": "stands on a cliff at dawn", "outfit": ""}

# --- A. style promptow ---
out = {s: prompts.image_prompt(C, SHOT, with_refs=False, style=s) for s in ("rich_caption", "compact", "natural", "spatial")}
check("A1 cztery style bez referencji daja rozne prompty", len(set(out.values())) == 4)
check("A2 kazdy styl zawiera postac, akcje i kamere",
      all("silver braid" in p and "cliff" in p and "three-quarter" in p for p in out.values()))
check("A3 spatial ma jawne relacje przestrzenne", "center of the frame" in out["spatial"] and "behind" in out["spatial"])
check("A4 rich_caption/natural/compact bez skladni wag i tagow SD",
      all(not any(x in out[k] for x in ("(((", ":1.", "masterpiece", "score_")) for k in ("rich_caption", "natural", "compact")))
check("A5 prompty nie zawieraja negatywow ('negative')", all("negative" not in p.lower() for p in out.values()))
d1 = prompts.image_prompt(C, SHOT, with_refs=True, style="delta", n_refs=1)
d2 = prompts.image_prompt(C, SHOT, with_refs=True, style="delta", n_refs=2)
check("A6 edycja: instrukcja zmiany z zachowaniem stroju", "reference image" in d1 and "outfit" in d1 and "exactly the same" in d1)
check("A7 edycja z 2 referencjami dopisuje role drugiej", "second reference image" in d2 and "second reference" not in d1)
check("A8 edycja: 1-4 zdania (wg dokumentacji Sogni)", 1 <= d1.count(". ") + 1 <= 4, str(d1.count(". ") + 1))
d3 = prompts.image_prompt(C, {**SHOT, "outfit": "a white dress"}, with_refs=True, style="delta")
check("A9 zmiana stroju: bez wymuszania starego stroju", "Change her clothing: a white dress" in d3 and "hairstyle, outfit" not in d3)

# --- B. profile ---
check("B1 znane profile maja poprawna operacje", models.PROFILES["krea-2-turbo"].op == "generate"
      and models.PROFILES["krea-identity-edit"].op == "edit" and models.PROFILES["qwen"].op == "edit")
check("B2 limity referencji z dokumentacji (Krea 2, Qwen 3)",
      models.PROFILES["krea-identity-edit"].max_refs == 2 and models.PROFILES["qwen"].max_refs == 3)
g = models.get("jakis-nowy-model", "generate")
check("B3 nieznany model: profil ogolny", g.style == "natural" and g.max_refs == 0 and not g.tested)

# --- C. API ---
with TestClient(app) as c:
    cat = c.get("/api/models").json()
    check("C1 /api/models: generowanie i edycja + domyslne", len(cat["generate"]) >= 8 and len(cat["edit"]) >= 4
          and cat["defaults"]["generate"] and cat["defaults"]["edit"])
    ch = c.post("/api/characters", json={**{k: C[k] for k in C}, "name": "T", "adult_fictional": True}).json()
    cid = ch["id"]
    base = {"character_id": cid, "az": 40, "el": 5, "dist": 4.5, "fov": 35, "fmt": "16:9", "action": "stands on a cliff"}

    r = c.post("/api/preview", json=base).json()
    check("C2 bez kanonu: generowanie domyslnym modelem", r["kind"] == "image" and r["model"] == cat["defaults"]["generate"], r["model"])
    styles = {}
    for m in ("krea-2-turbo", "z-turbo", "chroma1-hd", "qwen-2512"):
        styles[m] = c.post("/api/preview", json={**base, "image_model": m}).json()
    check("C3 wybrany model zmienia styl i prompt",
          styles["krea-2-turbo"]["style"] == "rich_caption" and styles["z-turbo"]["style"] == "compact"
          and styles["chroma1-hd"]["style"] == "natural" and styles["qwen-2512"]["style"] == "spatial"
          and len({s["image_prompt"] for s in styles.values()}) == 4)
    b = io.BytesIO(); Image.new("RGB", (64, 64), (1, 2, 3)).save(b, "PNG")
    c.post(f"/api/characters/{cid}/canon", data={"role": "face", "tier": "main"}, files={"file": ("f.png", b.getvalue(), "image/png")})
    r = c.post("/api/preview", json=base).json()
    check("C4 z kanonem: edycja modelem edycji", r["kind"] == "edit" and r["style"] == "delta" and r["refs"], r["model"])
    r = c.post("/api/preview", json={**base, "edit_model": "qwen"}).json()
    check("C5 wybor modelu edycji (Qwen)", r["model"] == "qwen" and r["kind"] == "edit")
    r = c.post("/api/preview", json={**base, "use_refs": False, "image_model": "qwen-2512"}).json()
    check("C6 use_refs=false: generowanie mimo kanonu", r["kind"] == "image" and r["refs"] == [] and r["style"] == "spatial")
    r = c.post("/api/preview", json={**base, "edit_model": "krea-2-turbo"})
    check("C7 model tylko-do-generowania jako model edycji -> 400", r.status_code == 400 and "tylko generowanie" in r.text, r.text[:90])
    r = c.post("/api/preview", json={**base, "use_refs": False, "image_model": "krea-identity-edit"})
    check("C8 model edycji jako model generowania -> 400", r.status_code == 400 and "tylko edycje" in r.text, r.text[:90])
    for bad in ("../etc/passwd", "a b", "x" * 200, "m;drop"):
        r = c.post("/api/preview", json={**base, "use_refs": False, "image_model": bad})
        check(f"C9 niepoprawny identyfikator odrzucony: {bad[:12]!r}", r.status_code == 400)
    r = c.post("/api/preview", json={**base, "use_refs": False, "image_model": "nowy-model-z-katalogu"}).json()
    check("C10 wlasny identyfikator: profil ogolny", r["model"] == "nowy-model-z-katalogu" and r["style"] == "natural")
    sid = c.post("/api/shots", json={**base, "use_refs": False, "image_model": "z-turbo"}).json()["id"]
    j = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": "z-turbo"}).json()
    job = c.get(f"/api/jobs?character_id={cid}").json()[0]
    check("C11 generate zapisuje wybrany model w zadaniu", job["model"] == "z-turbo" and j["kind"] == "image", job["model"])

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
