import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = Path(os.getenv("STUDIO_DATA") or ROOT / "data")
CANON_DIR = DATA / "canon"
OUT_DIR = DATA / "outputs"
DB_PATH = DATA / "studio.db"
for d in (CANON_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _bool(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes")


def _json(key: str) -> dict:
    raw = os.getenv(key, "{}").strip() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"{key} w .env nie jest poprawnym JSON: {e}")


PROVIDER = os.getenv("PROVIDER", "mock").strip().lower()
SOGNI_API_KEY = os.getenv("SOGNI_API_KEY", "").strip()
SAFE_CONTENT_FILTER = _bool("SAFE_CONTENT_FILTER", "true")
SOGNI_BILLING_MODE = os.getenv("SOGNI_BILLING_MODE", "subscription")
# Ile razy wznowic workflow wstrzymany przez przeglad bezpieczenstwa (safety_review_required) z safe_content_filter=false. 0 = nie wznawiaj.
SAFETY_RESUME_ATTEMPTS = int(os.getenv("SAFETY_RESUME_ATTEMPTS", "2"))
SOGNI_MAX_CAPACITY_UNITS = float(os.getenv("SOGNI_MAX_CAPACITY_UNITS", "40"))
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "krea-2-turbo")
EDIT_MODEL = os.getenv("EDIT_MODEL", "krea-identity-edit")
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "ltx25")
VIDEO_DURATION = int(os.getenv("VIDEO_DURATION", "5"))
# Klip klatka start -> klatka koniec (zweryfikowane testem: wymaga frameRole="both").
FLF_MODEL = os.getenv("FLF_MODEL", "minimax-h3-fasth3-flf2v-turbo")
FLF_DURATION = int(os.getenv("FLF_DURATION", "6"))
SOGNI_EDIT_REF_ARG = os.getenv("SOGNI_EDIT_REF_ARG", "contextImageIndices")
SOGNI_IMAGE_ARGS = _json("SOGNI_IMAGE_ARGS")
SOGNI_VIDEO_ARGS = _json("SOGNI_VIDEO_ARGS")
MAX_IMAGE_JOBS = int(os.getenv("MAX_IMAGE_JOBS", "4"))
MAX_VIDEO_JOBS = int(os.getenv("MAX_VIDEO_JOBS", "1"))
MAX_ATTEMPTS_PER_SHOT = int(os.getenv("MAX_ATTEMPTS_PER_SHOT", "6"))
MAX_REFS = int(os.getenv("MAX_REFS", "3"))
# Film: domyslny budzet jednego uruchomienia produkcji (Spark "wartosci" z licznika planu), limity prob.
FILM_BUDGET_SPARK = float(os.getenv("FILM_BUDGET_SPARK", "400"))
FILM_MAX_TASK_ATTEMPTS = int(os.getenv("FILM_MAX_TASK_ATTEMPTS", "3"))
FILM_PAUSE_MINUTES = int(os.getenv("FILM_PAUSE_MINUTES", "20"))
# Asystent (model jezykowy Sogni, rozliczany z planu). Dostepne modele: GET /v1/models.
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-35b-a3b-gguf-iq4xs")
# Pomiar twarzy (InsightFace). Miara orientacyjna - nie odrzuca wynikow automatycznie.
FACE_GUARD = _bool("FACE_GUARD", "true")
