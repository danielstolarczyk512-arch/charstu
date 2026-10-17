"""Testy rejestru modeli i pokrycia planem (dodatek do briefu), bez modelu i bez konta: python -m tests.models_plan_test"""
import io
import os
import re
import tempfile
from pathlib import Path

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-plan-")
os.environ["PROVIDER"] = "mock"
os.environ["SOGNI_API_KEY"] = "test-key-nieprawdziwy"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import catalog_sync, config, models, pipeline, runner  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.base import GenRequest  # noqa: E402
from app.providers.sogni import SogniProvider  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""), flush=True)


# --- rejestr ---
bad = [p.id for p in models.PROFILES.values()
       if p.kind not in models.KINDS or not isinstance(p.covered, bool) or p.category not in models.CATEGORIES]
check("P1 kazdy wpis ma kind, covered i category", not bad, str(bad[:5]))
bad = [p.id for p in models.PROFILES.values() if not p.covered and not p.note.strip()]
check("P2 kazdy covered=False ma niepusty powod w note", not bad, str(bad))
uncovered = {p.id for p in models.PROFILES.values() if not p.covered}
want = {"wan3.0-video", "wan3.0-spicy-video", "gpt-image-2", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare",
        "seedance2", "seedance2-mini", "seedance2-mini-uncensored", "seedance2-5", "seedance2-5-uncensored",
        "happyhorse-1.1-i2v", "minimax-h3-fasth3-i2v-turbo-2stage"}
check("P3 lista poza planem: Premium Spark wg briefu (identyfikatory poprawione wg walidacji Sogni)", uncovered == want, str(uncovered ^ want))
check("P4 istniejace wartosci tested bez zmian",
      all(models.PROFILES[i].tested for i in ("krea-2-turbo", "qwen", "krea-identity-edit", "dark-beast-krea2", "z-turbo"))
      and models.PROFILES["krea-identity-edit"].max_refs == 2 and models.PROFILES["qwen"].max_refs == 3)
check("P5 nowe wpisy bez potwierdzenia renderem maja tested=False",
      not any(models.PROFILES[i].tested for i in ("dark-beast-z-image-turbo", "krea-2-identity-edit-lora-v1-2",
                                                  "minimax-h3-i2v", "wan3.0-spicy-video", "albedobase-xl")))

cat = models.catalog()
check("C1 catalog() zawiera wszystkie rodzaje", all(k in cat for k in models.KINDS), str(list(cat)))
dups = [k for k in models.KINDS if len({e["id"] for e in cat[k]}) != len(cat[k])]
check("C2 bez duplikatow w obrebie rodzaju", not dups, str(dups))
check("C3 pozycje maja covered/label/note/category/kind",
      all({"covered", "label", "note", "category", "kind"} <= set(e) for k in models.KINDS for e in cat[k]))
unsorted = [k for k in models.KINDS if [e["covered"] for e in cat[k]] != sorted((e["covered"] for e in cat[k]), reverse=True)]
check("C4 w kazdym rodzaju najpierw modele z planu, potem reszta", not unsorted, str(unsorted))
check("C5 klucz 'generate' = alias 'image' (zgodnosc)", cat["generate"] == cat["image"])

# --- billing ---
CFG_BILL = config.SOGNI_BILLING_MODE
check("B1 model poza planem -> tokens", models.billing_for("wan3-uncensored", CFG_BILL) == "tokens")
check("B2 model z planu -> wartosc z konfiguracji", models.billing_for("qwen", CFG_BILL) == CFG_BILL)
check("B3 nieznany identyfikator -> covered False, billing tokens",
      models.covered("jakis-nowy-model") is False and models.billing_for("jakis-nowy-model", CFG_BILL) == "tokens")
job = lambda **k: {"kind": "video", "model": "ltx25", **k}  # noqa: E731
check("B4 runner.job_billing: poza planem tokens, z planu config, glos/muzyka config",
      runner.job_billing(job(model="wan3-uncensored")) == "tokens" and runner.job_billing(job()) == CFG_BILL
      and runner.job_billing(job(kind="speech", model="qwen3-tts-voice")) == CFG_BILL
      and runner.job_billing(job(kind="image", model="gpt-image-2")) == "tokens")
prov = SogniProvider()
body = prov._plan(GenRequest(kind="image", prompt="x", model="gpt-image-2", billing_mode="tokens"))
body2 = prov._plan(GenRequest(kind="image", prompt="x", model="qwen-2512"))
check("B5 _plan: billing_mode z zadania, a bez niego z konfiguracji; confirm_cost zostaje",
      body["billing_mode"] == "tokens" and body2["billing_mode"] == CFG_BILL and body["confirm_cost"] is True)
check("B6 GenRequest ma pole billing_mode (domyslnie None)", GenRequest(kind="image", prompt="x").billing_mode is None)

# --- nieznany identyfikator i bramka Spark ---
p = models.get("nowy-model-z-katalogu", "generate")
check("U1 nieznany identyfikator: profil ogolny, covered False, known False", not p.covered and not p.known and "sprawdz" in p.note)
try:
    pipeline.check_spark("nowy-model-z-katalogu", False)
    err = None
except pipeline.PipelineError as e:
    err = e
check("U2 bez zgody: 409 z ostrzezeniem", err is not None and err.status == 409 and "Premium Spark" in str(err))
try:
    pipeline.check_spark("nowy-model-z-katalogu", True)
    ok = True
except pipeline.PipelineError:
    ok = False
check("U3 ze zgoda (mock, saldo nieznane): przechodzi", ok)
pipeline.check_spark("qwen", False)
check("U4 model z planu nie wymaga zgody", True)
real_balance = pipeline.spark_balance
pipeline.spark_balance = lambda: 0.0
try:
    pipeline.check_spark("wan3-uncensored", True)
    err = None
except pipeline.PipelineError as e:
    err = e
pipeline.spark_balance = real_balance
check("U5 saldo 0: blad PRZED wyslaniem (402)", err is not None and err.status == 402 and "0" in str(err))

# --- scalanie katalogu z API (cache) ---
cache = {"fetched": 1.0, "llm": ["qwen3.6-35b-a3b-gguf-iq4xs", "nowy-llm"],
         "models": [{"id": "seedance-2-0", "name": "Seedance 2.0", "mediaType": "video", "tags": ["premium"]},
                    {"id": "coreml-cos", "name": "x", "mediaType": "image", "tags": []},
                    {"id": "obcy_model_xyz", "name": "Obcy", "mediaType": "image", "tags": ["premium"]},
                    {"id": "krea2_identity_edit_v1_2", "name": "k", "mediaType": "image", "tags": []}]}
m = catalog_sync.merged(cache)
img_ids = {e["id"] for e in m["image"]}
obcy = next((e for e in m["image"] if e["id"] == "obcy_model_xyz"), None)
check("S1 nieznana pozycja z katalogu: covered False, known False, 'nieznany, sprawdz'",
      obcy and not obcy["covered"] and not obcy["known"] and "sprawdz" in obcy["note"])
check("S2 coreml-* pominiete, pozycje znane nie dubluja sie", "coreml-cos" not in img_ids and "seedance-2-0" not in img_ids)
check("S3 pozycje z rejestru nigdy nie znikaja", set(models.PROFILES) <= {e["id"] for k in models.KINDS for e in m[k]})
unav = set(m["unavailable"])
gpt = next(e for e in m["image"] if e["id"] == "gpt-image-2")
check("S4 zniknieta z katalogu pozycja jest oznaczona niedostepna, nie usunieta", "gpt-image-2" in unav and gpt["available"] is False)
check("S5 pozycje potwierdzone katalogiem sa dostepne",
      not ({"seedance-2-0", "dark-beast-krea2-identity-edit", "krea-identity-edit"} & unav) or "krea-identity-edit" not in unav)
check("S6 alias bez katalogowego odpowiednika (qwen-lightning) nie jest 'niedostepny'", "qwen-lightning" not in unav)
check("S7 LLM: znany dostepny, brakujacy niedostepny, nowy jako nieznany",
      "qwen3.6-35b-a3b-gguf-iq4xs" not in unav and "deepseek-v4-flash-vision-exp-dspark-1m" in unav
      and any(e["id"] == "nowy-llm" and not e["known"] for e in m["llm"]))
check("S8 bez cache: wbudowana lista", "wbudowana" in catalog_sync.merged(None)["source"])
warn = catalog_sync.check_defaults(cache)
check("S9 ostrzezenie o domyslnym modelu, ktory zniknal z katalogu", any("IMAGE_MODEL" in w and "zniknal" in w for w in warn), str(warn))
check("S10 refresh bez PROVIDER=sogni: czytelny blad, nie wyjatek", catalog_sync.refresh(None)["ok"] is False)

# --- JS bez zaszytych identyfikatorow ---
hard = []
for f in Path("static").glob("*.js"):
    src = f.read_text(encoding="utf-8")
    for pid in models.PROFILES:
        if ("'" + pid + "'") in src or ('"' + pid + '"') in src:
            hard.append((f.name, pid))
    for kw in ("krea", "qwen", "seedance", "wan3", "gpt-image", "chroma", "ltx"):
        if re.search(r"""['"][a-z0-9._-]*""" + kw + r"""[a-z0-9._-]*['"]""", src, re.IGNORECASE):  # token bez spacji = identyfikator
            hard.append((f.name, kw))
check("J1 pliki static/*.js nie zawieraja zaszytych identyfikatorow modeli", not hard, str(hard[:5]))
html = Path("static/index.html").read_text(encoding="utf-8")
check("J2 w index.html nie ma pol tekstowych na model, sa listy",
      "dlGen" not in html and "dlEdit" not in html and '<select id="mGen"' in html and '<select id="mVid"' in html)

# --- API ---
with TestClient(app) as c:
    r = c.get("/api/models").json()
    check("A1 /api/models: wszystkie rodzaje, domyslne i ostrzezenie", all(k in r for k in models.KINDS) and r["defaults"]["video"]
          and "Premium Spark" in r["spark_warning"] and r["source"])
    b = io.BytesIO()
    Image.new("RGB", (32, 32), (120, 80, 200)).save(b, "PNG")
    cid = c.post("/api/characters", json={"name": "T", "archetype": "adult test", "traits": "x", "outfit": "y", "style": "z",
                                          "adult_fictional": True}).json()["id"]
    c.post(f"/api/characters/{cid}/canon", files={"file": ("a.png", b.getvalue(), "image/png")}, data={"role": "face"})
    base = {"character_id": cid, "az": 0, "el": 5, "dist": 4, "fov": 35, "fmt": "16:9", "action": "stands", "outfit": ""}
    sid = c.post("/api/shots", json=base).json()["id"]
    r1 = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": "gpt-image-2"})
    check("A2 model poza planem bez zgody: 409 i ostrzezenie", r1.status_code == 409 and "Premium Spark" in r1.json()["detail"])
    r2 = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": "gpt-image-2",
                                                    "allow_spark": True})
    jobs = c.get(f"/api/jobs?character_id={cid}").json()
    check("A3 ze zgoda: zadanie utworzone, billing zadania = tokens",
          r2.status_code == 200 and jobs and runner.job_billing(jobs[0]) == "tokens", str(r2.status_code))
    r3 = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": "z-turbo"})
    jobs = c.get(f"/api/jobs?character_id={cid}").json()
    check("A4 model z planu: bez zgody, billing z konfiguracji", r3.status_code == 200 and runner.job_billing(jobs[0]) == CFG_BILL)
    r4 = c.post(f"/api/shots/{sid}/generate", json={"kind": "image", "use_refs": False, "image_model": "ltx25"})
    check("A5 model wideo wybrany jako obrazowy: czytelny blad", r4.status_code == 400
          and "nie jest modelem obrazu" in r4.json()["detail"])
    r5 = c.get("/api/account").json()
    check("A6 /api/account: saldo (mock = None) i ostrzezenie", "premium_spark" in r5 and "Premium Spark" in r5["spark_warning"])
    fid = c.post("/api/films", json={"character_id": cid, "title": "F"}).json()["film"]["id"]
    pf = c.patch(f"/api/films/{fid}", json={"allow_spark": True, "image_model": "gpt-image-2"}).json()["film"]
    check("A7 film: allow_spark i modele zapisane", pf["allow_spark"] == 1 and pf["image_model"] == "gpt-image-2")

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
