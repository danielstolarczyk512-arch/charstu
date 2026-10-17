"""Rezyser AI: z pomyslu po polsku planuje caly film (sceny, ujecia, kamera, kwestie, podklad).

Dwa etapy, zeby kazda odpowiedz modelu byla krotka i sprawdzalna: (1) zarys (tytul, opis, podklad, lista scen),
(2) osobno ujecia kazdej sceny (z kontekstem poprzednich scen). Wynik jest walidowany (zakresy kamery, dlugosci, limity)
i przechodzi przez siatke bezpieczenstwa (postac niepelnoletnia). Rezyser TYLKO planuje - generowanie uruchamia producent,
a koszt kontroluje budzet filmu.
"""
import json
import logging
import threading

from . import assistant, db, film as F

log = logging.getLogger("director")

OUTLINE_SYSTEM = """Jestes rezyserem i scenarzysta krotkich filmow AI. Rozmawiasz po polsku. Z pomyslu uzytkownika tworzysz ZARYS filmu.
Odpowiadasz WYLACZNIE jednym poprawnym obiektem JSON (bez tekstu poza nim, bez bloku kodu):
{
  "title": "tytul po polsku",
  "logline": "jedno zdanie po polsku",
  "synopsis": "krotki opis fabuly po polsku (3-6 zdan)",
  "music_prompt": "opis podkladu muzycznego PO ANGIELSKU: nastroj, instrumenty, tempo (BPM), tonacja, 'instrumental, no vocals'",
  "scenes": [ {"title": "tytul sceny po polsku", "summary": "co sie dzieje, po polsku, 1-2 zdania",
               "location": "miejsce akcji PO ANGIELSKU, konkretne i wizualne (stale dla calej sceny)",
               "lighting": "swiatlo i pora dnia PO ANGIELSKU (stale dla calej sceny)"} ]
}
Zasady: bohater filmu jest ten, ktorego opisano w kontekscie; zachowaj spojny swiat i pory dnia miedzy scenami.
Liczba scen: zgodnie z prosba (domyslnie 4, maksymalnie 8). Dramaturgia: poczatek, rozwoj, punkt kulminacyjny, zakonczenie.
""" + assistant.SHARED_RULES

SCENE_SYSTEM = """Jestes rezyserem. Planujesz UJECIA jednej sceny krotkiego filmu AI. Rozmawiasz po polsku.
Odpowiadasz WYLACZNIE jednym poprawnym obiektem JSON (bez tekstu poza nim, bez bloku kodu):
{
  "shots": [ {"title": "krotki tytul po polsku", "az": 0, "el": 5, "dist": 4.5, "fov": 35,
              "action": "co robi bohater i co widac - PO ANGIELSKU, jedno zdanie, bez nazwy miejsca (miejsce jest w scenie)",
              "outfit": "", "dialogue": "", "duration": 5, "link_next": false} ]
}
Zasady:
- 2-6 ujec na scene (zgodnie z prosba), rozne plany i katy, ale to samo miejsce i swiatlo sceny.
- dialogue: krotka kwestia lektora/bohatera PO ANGIELSKU (maks. 120 znakow) albo pusty tekst; najwyzej w co drugim ujeciu.
  Lektor nie obsluguje polskiego, wiec kwestie zawsze po angielsku.
- duration: 4-8 sekund (ile ma trwac klip).
- link_next: true tylko, gdy to ujecie ma plynnie przejsc w NASTEPNE ujecie tej sceny (np. okrazenie postaci: pierwsze
  ujecie az=0, drugie az=180 w tym samym planie); w ostatnim ujeciu sceny zawsze false.
- outfit: puste, chyba ze scena wymaga innego stroju.
""" + assistant.SHARED_RULES


DUET_RULES = """
TRYB DUET (w kadrze sa DWIE osoby: bohater i partner; oboje sa opisani w kontekscie):
- action i interaction pisz PO ANGIELSKU, uzywajac IMION obu osob (kto co robi wobec kogo); nie pisz "the character".
- interaction: jedno zdanie o tym, co robia razem (np. pozycja, gest, kontakt); puste tylko, gdy ujecie jest czysto kadrowe.
- outfit = strój bohatera, outfit_b = strój partnera; puste = jak w kanonie.
- duration: 4-15 sekund; dluzsze (do 15) w scenach zblizeniowych i dluzszych interakcjach.
- Obie osoby maja byc widoczne w kazdym ujeciu; zblizenia planuj tak, by oboje mieli twarz w kadrze, gdy to mozliwe.
"""


def _ctx_text(character: dict, film: dict, partner: dict | None = None) -> str:
    ctx = {"bohater": {k: character.get(k) for k in ("name", "archetype", "traits", "outfit", "style")},
           "format": film["fmt"]}
    if partner:
        ctx["partner"] = {k: partner.get(k) for k in ("name", "archetype", "traits", "outfit", "style")}
        ctx["interakcja_filmu"] = film.get("interaction") or ""
    return json.dumps(ctx, ensure_ascii=False)


def _set_state(film_id: int, state: str):
    db.run("UPDATE films SET plan_state=?, updated=? WHERE id=?", (state, db.now(), film_id))


def plan_outline(provider, film: dict, character: dict, idea: str, n_scenes: int, partner: dict | None = None) -> dict:
    msgs = [{"role": "system", "content": OUTLINE_SYSTEM + (DUET_RULES if partner else "")},
            {"role": "system", "content": "Kontekst (JSON): " + _ctx_text(character, film, partner)},
            {"role": "user", "content": f"Pomysl na film: {idea[:2000]}\nLiczba scen: {n_scenes}"}]
    raw, text = assistant.chat_json(provider, msgs, timeout=100)
    if raw is None:
        raise RuntimeError("Model nie zwrocil poprawnego zarysu filmu: " + text[:200])
    if raw.get("refused"):
        raise F.FilmError(assistant._s(raw.get("reply"), 300) or assistant.REFUSAL)
    scenes = [s for s in (raw.get("scenes") or []) if isinstance(s, dict)][:8]
    if not scenes:
        raise RuntimeError("Zarys nie zawiera scen")
    out = {"title": assistant._s(raw.get("title"), 120), "logline": assistant._s(raw.get("logline"), 400),
           "synopsis": assistant._s(raw.get("synopsis"), 2000), "music_prompt": assistant._s(raw.get("music_prompt"), 800),
           "scenes": [{"title": assistant._s(s.get("title"), 120), "summary": assistant._s(s.get("summary"), 800),
                       "location": assistant._s(s.get("location"), 400), "lighting": assistant._s(s.get("lighting"), 300)}
                      for s in scenes]}
    F.safe_texts(out["title"], out["logline"], out["synopsis"], out["music_prompt"],
                 *[f"{s['title']} {s['summary']} {s['location']} {s['lighting']}" for s in out["scenes"]])
    return out


MAX_DURATION = 8          # film jednoosobowy: klipy 4-8 s
MAX_DURATION_DUET = 15    # film z partnerem: do 15 s (sceny zblizeniowe i dluzsze interakcje)


def plan_scene(provider, film: dict, character: dict, outline: dict, scene_idx: int, n_shots: int,
               partner: dict | None = None) -> list[dict]:
    sc = outline["scenes"][scene_idx]
    prev = [f"{i + 1}. {s['title']}: {s['summary']}" for i, s in enumerate(outline["scenes"][:scene_idx])]
    msgs = [{"role": "system", "content": SCENE_SYSTEM + (DUET_RULES if partner else "")},
            {"role": "system", "content": "Kontekst (JSON): " + _ctx_text(character, film, partner)},
            {"role": "user", "content": json.dumps({
                "film": {"tytul": outline["title"], "opis": outline["synopsis"]},
                "poprzednie_sceny": prev, "ta_scena": sc, "numer_sceny": scene_idx + 1,
                "liczba_scen": len(outline["scenes"]), "liczba_ujec": n_shots}, ensure_ascii=False)}]
    raw, text = assistant.chat_json(provider, msgs, timeout=100)
    if raw is None:
        raise RuntimeError(f"Model nie zwrocil ujec sceny {scene_idx + 1}: " + text[:200])
    shots = [s for s in (raw.get("shots") or []) if isinstance(s, dict)][:8]
    if not shots:
        raise RuntimeError(f"Scena {scene_idx + 1}: brak ujec w odpowiedzi")
    cleaned = []
    for i, s in enumerate(shots):
        d = F.clean_shot({**s, "fmt": film["fmt"]})   # zakresy, dlugosc 2-20 s, siatka bezpieczenstwa
        d["duration"] = int(max(4, min(MAX_DURATION_DUET if partner else MAX_DURATION, d["duration"])))
        d["link_next"] = 1 if (s.get("link_next") and i < len(shots) - 1) else 0
        cleaned.append(d)
    return cleaned


def run_plan(provider, film_id: int, idea: str, n_scenes: int, n_shots: int, replace: bool):
    """Wykonywane w watku: zarys -> sceny -> ujecia kolejnych scen, z postepem w films.plan_state."""
    try:
        film = F.get_film_row(film_id)
        character = db.one("SELECT * FROM characters WHERE id=?", (film["character_id"],))
        _set_state(film_id, "planning: zarys filmu")
        partner = db.one("SELECT * FROM characters WHERE id=?", (film["partner_id"],)) if film.get("partner_id") else None
        outline = plan_outline(provider, film, character, idea, n_scenes, partner)
        if replace:
            for sc in db.rows("SELECT id FROM scenes WHERE film_id=?", (film_id,)):
                F.delete_scene(sc["id"])
        F.update_film(film_id, title=outline["title"] or film["title"], logline=outline["logline"],
                      synopsis=outline["synopsis"], music_prompt=outline["music_prompt"])
        scene_ids = [F.add_scene(film_id, s["title"], s["summary"], s["location"], s["lighting"]) for s in outline["scenes"]]
        for i, sid in enumerate(scene_ids):
            _set_state(film_id, f"planning: scena {i + 1}/{len(scene_ids)}")
            for d in plan_scene(provider, film, character, outline, i, n_shots, partner):
                F.add_shot(sid, d)
        _set_state(film_id, "done")
    except Exception as e:  # noqa: BLE001 - blad pokazujemy w interfejsie
        log.exception("planowanie filmu %s nie powiodlo sie", film_id)
        _set_state(film_id, f"error: {e}"[:400])


def start_plan(provider, film_id: int, idea: str, n_scenes: int = 4, n_shots: int = 3, replace: bool = False):
    film = F.get_film_row(film_id)
    if not idea.strip():
        raise F.FilmError("Opisz pomysl na film")
    F.safe_texts(idea)
    if not hasattr(provider, "_call"):
        raise F.FilmError("Rezyser AI wymaga PROVIDER=sogni (model jezykowy z planu).", 409)
    if (film["plan_state"] or "").startswith("planning"):
        raise F.FilmError("Planowanie juz trwa", 409)
    if db.one("SELECT 1 FROM scenes WHERE film_id=?", (film_id,)) and not replace:
        raise F.FilmError("Film ma juz sceny. Uzyj replace=true, zeby je zastapic (obrazy i klipy zostaja w galerii).", 409)
    n_scenes, n_shots = max(1, min(8, n_scenes)), max(1, min(6, n_shots))
    _set_state(film_id, "planning: start")
    t = threading.Thread(target=run_plan, args=(provider, film_id, idea, n_scenes, n_shots, replace), daemon=True,
                         name=f"director-{film_id}")
    t.start()
    return t
