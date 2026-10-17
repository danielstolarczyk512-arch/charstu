"""Producent filmu: seryjna produkcja ujec (obraz -> klip, kwestie lektora, podklad) z kontrola limitu i budzetu.

Dziala jako watek w tle (tick co kilka sekund). Stan wynika z artefaktow i zadan, wiec produkcja przezywa restart:
po starcie programu filmy w statusie 'producing' ida dalej, a Runner wznawia zadania Sogni po workflow_id.
"""
import json
import logging
import re
import threading
import time

from . import config, db, film as F, pipeline

log = logging.getLogger("producer")

# Orientacyjne koszty (Spark "wartosci" z licznika planu, zmierzone w Etapie 0) - uzywane tylko, gdy dostawca nie podaje licznika.
COST = {"image": 4.0, "clip": 25.0, "flf": 30.0, "speech": 3.0, "bed": 10.0}
# Bledy, ktore nie sa wina ujecia (siec, limity, kolejka): nie zuzywaja prob, produkcja robi przerwe.
_TRANSIENT = re.compile(r"429|rate|limit|quota|capacity|busy|queue|timeout|timed out|tempor|50[234]|network|siec|connection",
                        re.IGNORECASE)
_POLISH_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
# Slowa pomocnicze polskiego (bez ogonkow), zeby wykryc polski tekst pisany bez znakow diakrytycznych.
_POLISH_WORDS = {"sie", "nie", "jest", "ze", "jak", "ale", "tylko", "przez", "dla", "czy", "juz", "bardzo", "tego", "oraz",
                 "ktory", "ktora", "dalej", "idziemy", "bedzie", "moze", "tutaj", "wiec", "gdzie", "kiedy", "teraz", "zawsze",
                 "nigdy", "wszystko", "pamietaj", "dzis", "jutro", "droga", "wioski", "wiosce", "lasu", "jestem", "mamy",
                 "musimy", "chodz", "chodzmy", "prosze", "dziekuje", "cos", "ktos", "moj", "twoj", "nasz", "nasza", "wiem",
                 "chce", "mozemy", "razem", "dobrze", "zle", "przeszlosc", "swiat", "czas", "ludzie", "noc", "dzien"}


def looks_polish(text: str) -> bool:
    """Heurystyka: polskie znaki albo >= 2 typowe polskie slowa. Qwen3-TTS nie obsluguje polskiego."""
    if _POLISH_CHARS.search(text):
        return True
    words = re.findall(r"[a-z]+", text.lower())
    return sum(1 for w in words if w in _POLISH_WORDS) >= 2


class _PolishCompat:
    """Zachowuje interfejs .search(text) uzywany w kodzie producenta."""
    @staticmethod
    def search(text: str):
        return looks_polish(text or "")


_POLISH = _PolishCompat()
MAX_ACTIVE = {"image": 4, "clip": 2, "speech": 2}   # jednoczesne zadania jednego filmu

provider = None  # ustawiane przez main.lifespan (do licznika zuzycia)


def is_transient(error: str | None) -> bool:
    return bool(error and _TRANSIENT.search(error)) and "SAFETY_REJECTED" not in (error or "")


# ---------------- zlecanie pojedynczych zadan (uzywane tez przez API recznie) ----------------
def _ctx(fs_id: int):
    fs = F.get_shot(fs_id)
    film = F.get_film_row(fs["film_id"])
    scene = F.get_scene(fs["scene_id"])
    c = db.one("SELECT * FROM characters WHERE id=?", (film["character_id"],))
    return film, scene, fs, c


def shot_row(fs_id: int) -> dict:
    """Wiersz 'shots' (jak w Studiu) dla ujecia filmu; odswiezany, gdy zmienil sie opis/kamera."""
    film, scene, fs, c = _ctx(fs_id)
    eff = F.effective_shot(scene, fs)
    if fs["shot_row_id"]:
        db.run("UPDATE shots SET az=?,el=?,dist=?,fov=?,fmt=?,action=?,outfit=? WHERE id=?",
               (eff["az"], eff["el"], eff["dist"], eff["fov"], eff["fmt"], eff["action"], eff["outfit"], fs["shot_row_id"]))
        return db.one("SELECT * FROM shots WHERE id=?", (fs["shot_row_id"],))
    sid = pipeline.new_shot(c["id"], eff)
    db.run("UPDATE film_shots SET shot_row_id=? WHERE id=?", (sid, fs_id))
    return db.one("SELECT * FROM shots WHERE id=?", (sid,))


def request_image(fs_id: int, count: int = 1) -> dict:
    film, scene, fs, c = _ctx(fs_id)
    row = shot_row(fs_id)
    return pipeline.submit_image(row, c, film["image_model"], film["edit_model"], True, count, fs_id, "image")


def request_clip(fs_id: int) -> dict:
    """Klip z wybranego obrazu. Przy link_next i obrazie nastepnego ujecia: klip start->koniec (H3), z awaryjnym i2v."""
    film, scene, fs, c = _ctx(fs_id)
    if not fs["image_artifact_id"]:
        raise F.FilmError("Najpierw wybierz obraz ujecia")
    row = shot_row(fs_id)
    end_id = None
    if fs["link_next"] and not fs["no_flf"]:   # no_flf: limit H3 w okresie probnym -> zwykly klip z obrazu
        nxt = db.one("SELECT fs.image_artifact_id FROM film_shots fs JOIN scenes sc ON sc.id=fs.scene_id WHERE fs.film_id=? AND "
                     "(sc.idx>? OR (sc.idx=? AND fs.idx>?)) ORDER BY sc.idx, fs.idx LIMIT 1",
                     (fs["film_id"], scene["idx"], scene["idx"], fs["idx"]))
        end_id = nxt["image_artifact_id"] if nxt else None
        if end_id:
            try:
                pipeline.check_flf(fs["image_artifact_id"], end_id)
            except pipeline.PipelineError as e:   # np. rozne proporcje -> zwykly klip z obrazu
                db.run("UPDATE film_shots SET note=? WHERE id=?", (f"start->koniec pominiety: {e}"[:300], fs_id))
                end_id = None
    return pipeline.submit_video(row, c, fs["image_artifact_id"], end_id, fs["duration"], fs_id, "clip")


def request_speech(fs_id: int) -> dict | None:
    film, scene, fs, c = _ctx(fs_id)
    text = (fs["dialogue"] or "").strip()
    if not text:
        return None
    if _POLISH.search(text):   # Qwen3-TTS nie obsluguje polskiego (lista jezykow w dokumentacji Sogni)
        note = "Kwestia po polsku pominieta: Qwen3-TTS nie obsluguje polskiego. Wpisz ja po angielsku."
        if fs["note"] != note:
            db.run("UPDATE film_shots SET note=? WHERE id=?", (note, fs_id))
        return None
    row = shot_row(fs_id)
    voice = json.loads(c.get("voice") or "null") or {"mode": "voice", "voice": "serena", "language": "english"}
    params = {"text": text, "prompt": text, "voice": voice, "language": voice.get("language", "english"),
              "label": text[:60]}
    jid = pipeline.submit_job(row["id"], "speech", "qwen3-tts-" + voice.get("mode", "voice"), params, fs_id, "speech")
    return {"jobs": [jid]}


def request_bed(film_id: int) -> dict | None:
    """Podklad muzyczny calego filmu. Zadanie oznaczone film_shot_id = -film_id (marker poziomu filmu)."""
    film = F.get_film_row(film_id)
    if not (film["music_prompt"] or "").strip():
        return None
    total = sum(s["duration"] for s in F.ordered_shots(film_id)) or 20
    first = db.one("SELECT shot_row_id FROM film_shots WHERE film_id=? AND shot_row_id IS NOT NULL ORDER BY id LIMIT 1", (film_id,))
    c = db.one("SELECT * FROM characters WHERE id=?", (film["character_id"],))
    row_id = first["shot_row_id"] if first else pipeline.new_shot(c["id"], {"fmt": "audio", "action": "podklad filmu"})
    params = {"prompt": film["music_prompt"], "duration": max(10, min(300, total + 4)), "label": "podklad: " + film["title"][:40]}
    jid = pipeline.submit_job(row_id, "music", "music3", params, -film_id, "bed")
    return {"jobs": [jid]}


# ---------------- uzgadnianie stanu (artefakty -> pola ujecia) ----------------
def _latest_artifact(film_shot_id: int, role: str, kind: str) -> dict | None:
    return db.one("SELECT a.id, a.face_score FROM artifacts a JOIN jobs j ON j.id=a.job_id WHERE j.film_shot_id=? AND "
                  "j.role=? AND a.kind=? ORDER BY a.id DESC LIMIT 1", (film_shot_id, role, kind))


def best_candidate(candidates: list[dict]) -> dict:
    """Najlepszy kandydat: najwyzszy wynik twarzy (orientacyjny), a bez wynikow - najnowszy."""
    scored = [c for c in candidates if c.get("face_score") is not None]
    return max(scored, key=lambda c: c["face_score"]) if scored else candidates[-1]


def reconcile(film_id: int):
    film = F.get_film_row(film_id)
    for fs in F.ordered_shots(film_id):
        st = F.shot_state(fs)
        jobs = st["jobs"]
        if not fs["image_artifact_id"] and st["candidates"] and film["auto_pick"] and not jobs.get("image", {}).get("active"):
            db.run("UPDATE film_shots SET image_artifact_id=? WHERE id=?", (best_candidate(st["candidates"])["id"], fs["id"]))
        if not fs["clip_artifact_id"]:
            a = _latest_artifact(fs["id"], "clip", "video")
            if a:
                db.run("UPDATE film_shots SET clip_artifact_id=? WHERE id=?", (a["id"], fs["id"]))
        if fs["dialogue"] and not fs["speech_artifact_id"]:
            a = _latest_artifact(fs["id"], "speech", "audio")
            if a:
                db.run("UPDATE film_shots SET speech_artifact_id=? WHERE id=?", (a["id"], fs["id"]))
    if not film["music_artifact_id"]:
        a = _latest_artifact(-film_id, "bed", "audio")
        if a:
            db.run("UPDATE films SET music_artifact_id=? WHERE id=?", (a["id"], film_id))


# ---------------- licznik zuzycia i budzet ----------------
def usage_spark() -> float | None:
    """Zuzycie planu z licznika Sogni (renderSpark w biezacym oknie dziennym) albo None (mock / blad)."""
    if provider is None or not hasattr(provider, "_call"):
        return None
    try:
        r = provider._call("GET", "/v1/subscriptions/usage", retries=1)
        if r.status_code != 200:
            return None
        return float(r.json()["data"]["usage"]["value"]["daily"]["renderSpark"])
    except Exception:  # noqa: BLE001
        return None


def spent_since_start(film: dict) -> tuple[float, str]:
    now = usage_spark()
    if now is not None and film.get("usage_start") is not None:
        return max(0.0, now - film["usage_start"]), "licznik planu"
    # szacunek z liczby ukonczonych zadan od startu produkcji
    start = film.get("updated") or 0
    est = 0.0
    for j in db.rows("SELECT j.role, j.params FROM jobs j JOIN film_shots fs ON fs.id=j.film_shot_id WHERE fs.film_id=? "
                     "AND j.status='done' AND j.finished>=?", (film["id"], start)):
        est += COST.get(j["role"], 0.0)
    return est, "szacunek"


def estimate_remaining(film_id: int) -> dict:
    """Ile zadan i ile Spark 'wartosci' zostalo do wyprodukowania (orientacyjnie)."""
    film = F.get_film_row(film_id)
    shots = F.ordered_shots(film_id)
    n_img = sum(1 for s in shots if not s["image_artifact_id"])
    n_clip = sum(1 for s in shots if not s["clip_artifact_id"])
    n_flf = sum(1 for s in shots if not s["clip_artifact_id"] and s["link_next"])
    n_sp = sum(1 for s in shots if s["dialogue"] and not s["speech_artifact_id"] and not _POLISH.search(s["dialogue"]))
    bed = 1 if (film["music_prompt"] and not film["music_artifact_id"]) else 0
    cost = (n_img * COST["image"] + (n_clip - n_flf) * COST["clip"] + n_flf * COST["flf"] + n_sp * COST["speech"]
            + bed * COST["bed"])
    return {"images": n_img, "clips": n_clip, "linked_clips": n_flf, "speech": n_sp, "bed": bed,
            "jobs": n_img + n_clip + n_sp + bed, "est_spark": round(cost, 1)}


# ---------------- sterowanie ----------------
def start(film_id: int) -> dict:
    film = F.get_film_row(film_id)
    if not F.ordered_shots(film_id):
        raise F.FilmError("Film nie ma ujec - zaplanuj go (asystent) albo dodaj ujecia")
    if not db.one("SELECT 1 FROM canon_assets WHERE character_id=? AND approved=1", (film["character_id"],)):
        # bez kanonu obrazy powstaja bez referencji (kazda twarz inna) - ostrzezenie, nie blokada
        db.run("UPDATE films SET note=? WHERE id=?", ("Brak kanonu postaci: obrazy beda bez referencji (rozne twarze).", film_id))
    db.run("UPDATE films SET status='producing', paused_until=NULL, usage_start=?, updated=? WHERE id=?",
           (usage_spark(), db.now(), film_id))
    return F.get_film_row(film_id)


def pause(film_id: int) -> dict:
    F.get_film_row(film_id)
    db.run("UPDATE films SET status='paused' WHERE id=?", (film_id,))
    return F.get_film_row(film_id)


# ---------------- glowna petla ----------------
def tick(film_id: int):
    film = F.get_film_row(film_id)
    if film["status"] != "producing":
        return
    reconcile(film_id)
    film = F.get_film_row(film_id)
    shots = F.ordered_shots(film_id)

    # Limit dobowy okresu probnego (np. "MiniMax H3 trial limit: 6 videos per UTC day"): to nie wina ujecia.
    # H3 -> awaryjnie zwykly klip LTX (jawna notatka); inne limity dobowe -> czekamy do resetu (polnoc UTC).
    for fs in shots:
        for j in db.rows("SELECT id, role, model, error FROM jobs WHERE film_shot_id=? AND status='failed' AND "
                         "(error LIKE '%UTC day%' OR error LIKE '%trial limit%')", (fs["id"],)):
            db.run("UPDATE jobs SET status='retried' WHERE id=?", (j["id"],))
            if j["role"] == "clip" and (j["model"] or "").startswith("minimax-h3") and not fs["no_flf"]:
                db.run("UPDATE film_shots SET no_flf=1, failed=0, note=? WHERE id=?",
                       ("Limit H3 w okresie próbnym (6 klipów/dobę UTC): zrobię zwykły klip LTX zamiast przejścia start→koniec. "
                        "Reset ujęcia przywróci przejście.", fs["id"]))
            else:
                import datetime as _dt
                now = _dt.datetime.now(_dt.timezone.utc)
                reset = (now + _dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
                db.run("UPDATE films SET paused_until=?, note=? WHERE id=?",
                       (reset.timestamp(), f"Limit dobowy okresu próbnego: {(j['error'] or '')[-160:]} Wznowię po resecie "
                                           f"({reset.strftime('%H:%M')} UTC).", film_id))
                return
    shots = F.ordered_shots(film_id)   # no_flf mogl sie zmienic

    # wykrywanie chwilowych bledow (siec, limity, kolejka) - zadania ujec i podkladu
    pause_reason = None
    for key in [fs["id"] for fs in shots if not fs["failed"]] + [-film_id]:
        for role, b in F.job_buckets(key).items():
            if b["failed"] and is_transient(b["last_error"]):
                pause_reason = (b["last_error"] or "")[:200]
    # jesli ostatnie zadanie danej roli padlo z powodu limitow/sieci - przerwa, a to zadanie nie liczy sie do prob
    if pause_reason:
        until = db.now() + config.FILM_PAUSE_MINUTES * 60
        db.run("UPDATE films SET paused_until=?, note=? WHERE id=?",
               (until, f"Przerwa (limit/siec): {pause_reason}", film_id))
        # chwilowo nieudane zadania oznaczamy jako 'retry', zeby nie liczyly sie do prob
        db.run("UPDATE jobs SET status='retried' WHERE (film_shot_id IN (SELECT id FROM film_shots WHERE film_id=?) "
               "OR film_shot_id=?) AND status='failed' AND (error LIKE '%429%' OR error LIKE '%limit%' OR error LIKE '%quota%' "
               "OR error LIKE '%capacity%' OR error LIKE '%busy%' OR error LIKE '%queue%' OR error LIKE '%timeout%' "
               "OR error LIKE '%timed out%' OR error LIKE '%network%' OR error LIKE '%connection%') "
               "AND error NOT LIKE '%SAFETY_REJECTED%'", (film_id, -film_id))
        return

    # budzet
    spent, source = spent_since_start(film)
    if film["budget_spark"] and spent >= film["budget_spark"]:
        db.run("UPDATE films SET status='paused', note=? WHERE id=?",
               (f"Wstrzymano: osiagnieto budzet {film['budget_spark']:.0f} Spark ({source}: {spent:.0f}). "
                "Zwieksz budzet albo wznow jutro.", film_id))
        return

    active = {"image": 0, "clip": 0, "speech": 0}
    for fs in shots:
        for role, b in F.shot_state(fs)["jobs"].items():
            if role in active:
                active[role] += b["active"]
    max_att = config.FILM_MAX_TASK_ATTEMPTS

    def attempts(st, role):
        """Nieudane proby roli. Chwilowe ponowienia ('retried') nie licza sie do 3 pierwszych - potem tak (zabezpieczenie
        przed nieskonczona petla, gdyby blad tylko wygladal na chwilowy)."""
        b = st["jobs"].get(role, {})
        return b.get("failed", 0) + max(0, b.get("retried", 0) - 3)

    for idx, fs in enumerate(shots):
        if fs["failed"]:
            continue
        st = F.shot_state(fs)
        jobs = st["jobs"]
        # 1. obraz
        if not fs["image_artifact_id"]:
            if jobs.get("image", {}).get("active") or st["candidates"] and film["auto_pick"]:
                pass
            elif st["candidates"] and not film["auto_pick"]:
                pass  # czeka na reczny wybor
            elif attempts(st, "image") >= max_att:
                db.run("UPDATE film_shots SET failed=1, note=? WHERE id=?",
                       (f"Obraz: {max_att} nieudane proby. {jobs['image']['last_error'] or ''}"[:300], fs["id"]))
            elif active["image"] < MAX_ACTIVE["image"]:
                try:
                    request_image(fs["id"])
                    active["image"] += 1
                except (pipeline.PipelineError, F.FilmError) as e:
                    db.run("UPDATE film_shots SET failed=1, note=? WHERE id=?", (str(e)[:300], fs["id"]))
            continue
        # 2. klip (przy link_next potrzebny obraz nastepnego ujecia)
        if not fs["clip_artifact_id"]:
            if jobs.get("clip", {}).get("active"):
                pass
            elif attempts(st, "clip") >= max_att:
                db.run("UPDATE film_shots SET failed=1, note=? WHERE id=?",
                       (f"Klip: {max_att} nieudane proby. {jobs['clip']['last_error'] or ''}"[:300], fs["id"]))
            else:
                nxt = shots[idx + 1] if idx + 1 < len(shots) else None
                if fs["link_next"] and nxt and not nxt["image_artifact_id"] and not nxt["failed"]:
                    pass  # czekamy na obraz nastepnego ujecia (koniec klipu start->koniec)
                elif active["clip"] < MAX_ACTIVE["clip"]:
                    try:
                        request_clip(fs["id"])
                        active["clip"] += 1
                    except (pipeline.PipelineError, F.FilmError) as e:
                        db.run("UPDATE film_shots SET failed=1, note=? WHERE id=?", (str(e)[:300], fs["id"]))
        # 3. kwestia lektora (niezalezna od klipu)
        if fs["dialogue"] and not fs["speech_artifact_id"] and not _POLISH.search(fs["dialogue"]):
            if jobs.get("speech", {}).get("active"):
                pass
            elif attempts(st, "speech") >= max_att:
                if fs["note"] != "Kwestia: nieudane proby - pomijam.":
                    db.run("UPDATE film_shots SET note=? WHERE id=?", ("Kwestia: nieudane proby - pomijam.", fs["id"]))
            elif active["speech"] < MAX_ACTIVE["speech"]:
                if request_speech(fs["id"]):
                    active["speech"] += 1
        elif fs["dialogue"] and _POLISH.search(fs["dialogue"]):
            request_speech(fs["id"])   # tylko zapisuje notatke o jezyku

    # podklad
    film = F.get_film_row(film_id)
    if film["music_prompt"] and not film["music_artifact_id"]:
        bed = F.job_buckets(-film_id).get("bed", {})
        if not bed.get("active") and bed.get("failed", 0) < max_att:
            request_bed(film_id)

    # zakonczenie
    shots = F.ordered_shots(film_id)
    film = F.get_film_row(film_id)

    def speech_blocking(s):
        return bool(s["dialogue"]) and not s["speech_artifact_id"] and not _POLISH.search(s["dialogue"]) \
            and F.job_buckets(s["id"]).get("speech", {}).get("failed", 0) < max_att

    pending = [s for s in shots if not s["failed"] and (not s["clip_artifact_id"] or speech_blocking(s))]
    bed_pending = bool(film["music_prompt"]) and not film["music_artifact_id"] \
        and F.job_buckets(-film_id).get("bed", {}).get("failed", 0) < max_att
    if not pending and not bed_pending:
        failed = [s for s in shots if s["failed"]]
        db.run("UPDATE films SET status=?, note=?, updated=? WHERE id=?",
               ("needs_attention" if failed else "ready",
                f"{len(failed)} ujec wymaga uwagi (zobacz notatki)." if failed else "Produkcja zakonczona - mozna montowac.",
                db.now(), film_id))


class Producer(threading.Thread):
    def __init__(self, interval: float = 4.0):
        super().__init__(daemon=True, name="producer")
        self.interval = interval
        self._halt = threading.Event()   # UWAGA: nie _stop - to wewnetrzna metoda threading.Thread

    def run(self):
        while not self._halt.is_set():
            try:
                for f in db.rows("SELECT id, paused_until FROM films WHERE status='producing'"):
                    if f["paused_until"] and f["paused_until"] > db.now():
                        continue
                    tick(f["id"])
            except Exception:  # noqa: BLE001 - petla nie moze umrzec
                log.exception("blad producenta")
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
