"""Katalog modeli z API Sogni scalony z rejestrem (app/models.py).

Zrodla: GET /v1/model-catalog (obraz/wideo/dzwiek, ok. 500 pozycji; wewnetrzne identyfikatory) i GET /v1/models (modele
jezykowe). Wynik trafia do pliku data/model_catalog.json (cache; fallback bez sieci). Zasady:
- pozycja z rejestru NIGDY nie znika: gdy jej katalogowych identyfikatorow nie ma w pobranym katalogu, dostaje available=False;
- pozycje z katalogu nieznane rejestrowi pojawiaja sie jako "nieznany, sprawdz" z covered=False (bezpieczniej: bez pewnosci
  zadanie idzie jako Premium Spark dopiero po jawnej zgodzie, patrz pipeline.check_spark);
- identyfikatory `coreml-*` (modele na urzadzenie) pomijamy na liscie.
Zweryfikowane 17.10.2026 prawdziwym kluczem: struktura obu odpowiedzi, liczba pozycji (501), tag "premium". NIE zweryfikowane:
czy identyfikatory katalogowe sa przyjmowane przez edit_image/generate_image tak jak aliasy (README mowi, ze tak).
"""
import json
import logging
import time

from . import config, models

log = logging.getLogger("catalog")
CACHE = config.DATA / "model_catalog.json"
_MEDIA_KIND = {"image": "image", "video": "video", "audio": "music"}


def load_cache() -> dict | None:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refresh(provider) -> dict:
    """Pobiera oba katalogi i zapisuje cache. Zwraca {ok, count, llm, error?}; przy bledzie zostaje stary cache."""
    if provider is None or not hasattr(provider, "_call"):
        return {"ok": False, "error": "katalog z API wymaga PROVIDER=sogni (uzywam wbudowanej listy)"}
    try:
        r1 = provider._call("GET", "/v1/model-catalog", retries=1)
        r2 = provider._call("GET", "/v1/models", retries=1)
        if r1.status_code != 200:
            return {"ok": False, "error": f"/v1/model-catalog: HTTP {r1.status_code}"}
        items = [{k: m.get(k) for k in ("id", "name", "mediaType", "tags")}
                 for m in r1.json()["data"]["models"]]
        llm = [m["id"] for m in r2.json().get("data", [])] if r2.status_code == 200 else []
        data = {"fetched": time.time(), "models": items, "llm": llm}
        tmp = CACHE.with_suffix(".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE)
        return {"ok": True, "count": len(items), "llm": len(llm)}
    except Exception as e:  # noqa: BLE001 - brak sieci nie moze wywrocic programu
        log.warning("odswiezenie katalogu modeli nie powiodlo sie: %s", e)
        return {"ok": False, "error": str(e)[:200]}


def merged(cache: dict | None = None) -> dict:
    """models.catalog() z dolaczonymi pozycjami z cache i oznaczeniem niedostepnych."""
    cache = cache if cache is not None else load_cache()
    if not cache:
        return {**models.catalog(), "source": "wbudowana lista", "fetched": None}
    ids = {m["id"] for m in cache["models"]}
    llm = set(cache.get("llm") or [])
    known = set(models.PROFILES)
    for p in models.PROFILES.values():
        known.update(p.catalog)
    unavailable = set()
    for p in models.PROFILES.values():
        if p.kind == "llm":
            if llm and p.id not in llm:
                unavailable.add(p.id)
        elif p.catalog and not (set(p.catalog) & ids) and p.id not in ids:
            unavailable.add(p.id)
    extra = []
    for m in cache["models"]:
        mid, mt = m["id"], m.get("mediaType")
        if mid in known or mid.startswith("coreml-") or mt not in _MEDIA_KIND:
            continue
        kind = _MEDIA_KIND[mt]
        if kind == "music" and "tts" in mid:
            kind = "speech"
        tags = m.get("tags") or []
        extra.append({"id": mid, "label": m.get("name") or mid, "style": "natural" if kind == "image" else "",
                      "max_refs": 0, "tested": False, "kind": kind, "covered": False, "category": "Nieznane (z katalogu API)",
                      "known": False, "available": True, "pose_transfer": None,
                      "note": "Nieznany, sprawdz: pozycja z katalogu API, nie ma jej w rejestrze. Pokrycie planem nieznane"
                              + (" (tag premium)." if "premium" in tags else ".")})
    for mid in sorted(llm - known):
        extra.append({"id": mid, "label": mid, "style": "", "max_refs": 0, "tested": False, "kind": "llm", "covered": False,
                      "category": "Nieznane (z katalogu API)", "known": False, "available": True, "pose_transfer": None,
                      "note": "Nieznany, sprawdz: model z GET /v1/models, nie ma go w rejestrze."})
    out = models.catalog(extra, unavailable)
    return {**out, "source": "katalog API (cache)", "fetched": cache.get("fetched"), "unavailable": sorted(unavailable)}


def check_defaults(cache: dict | None = None) -> list[str]:
    """Ostrzezenia o domyslnych modelach z .env, ktorych nie ma w rejestrze albo zniknely z katalogu. Wypisuje je w logu."""
    cat = merged(cache)
    flat = {e["id"]: e for k in models.KINDS for e in cat[k]}
    out = []
    for name, mid in (("IMAGE_MODEL", config.IMAGE_MODEL), ("EDIT_MODEL", config.EDIT_MODEL),
                      ("VIDEO_MODEL", config.VIDEO_MODEL), ("FLF_MODEL", config.FLF_MODEL), ("LLM_MODEL", config.LLM_MODEL)):
        e = flat.get(mid)
        if e is None:
            out.append(f"{name}={mid}: brak w rejestrze i katalogu (nieznany, sprawdz)")
        elif not e["available"]:
            out.append(f"{name}={mid}: zniknal z katalogu Sogni (oznaczony jako niedostepny)")
        elif not e["covered"]:
            out.append(f"{name}={mid}: poza planem Unlimited - zadania pojda jako Premium Spark")
    for w in out:
        log.warning("model domyslny: %s", w)
    return out
