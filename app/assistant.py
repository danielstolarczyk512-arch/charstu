"""Asystent: z polecenia po polsku proponuje pola postaci i liste ujec (kamera, akcja, strój).

Asystent TYLKO proponuje - niczego nie generuje i nie zapisuje; uzytkownik wczytuje propozycje do formularza
i sam klika "Generuj" (kontrola zuzycia limitu). Model jezykowy: Sogni /v1/chat/completions (z planu).
Twarde granice (zapisane w prompcie systemowym i w formularzu postaci): tylko postacie fikcyjne i dorosle (18+),
bez prawdziwych osob, bez postaci niepelnoletnich. Poza tym asystent nie ma wlasnych ograniczen tresci;
zachowanie zalezy od wybranego modelu (LLM_MODEL).
"""
import json
import re

from . import config

SYSTEM = """Jestes asystentem programu do tworzenia spojnych postaci i ujec (obrazy i klipy). Rozmawiasz po polsku.
Odpowiadasz WYLACZNIE jednym poprawnym obiektem JSON, bez tekstu poza nim i bez bloku kodu:
{
  "reply": "krotka odpowiedz po polsku",
  "refused": false,
  "character": null albo {"name": "...", "archetype": "...", "traits": "...", "outfit": "...", "style": "..."},
  "shots": [ {"title": "krotki tytul po polsku", "az": 0, "el": 5, "dist": 4.5, "fov": 35, "fmt": "16:9",
              "action": "...", "outfit": ""} ]
}
Zasady pol:
- name po polsku; archetype, traits, outfit, style, action i shots[].outfit pisz PO ANGIELSKU (to prompty dla modeli obrazu).
- character: tylko gdy uzytkownik prosi o nowa postac lub zmiane opisu; w przeciwnym razie null.
- shots: pusta lista, jesli uzytkownik o ujecia nie prosi. Maksymalnie 12 ujec.
- shots[].outfit: puste = ten sam strój co w kanonie; wypelnij tylko gdy uzytkownik chce zmiany stroju w tym ujeciu.
Kamera (kamera obraca sie wokol postaci, ktora patrzy w strone +az=0):
- az (stopnie, -180..180): 0 przod, 40 trzy czwarte, 90 profil, 180 tyl; ujemne = z drugiej strony.
- el (stopnie, -60..85): 0..10 poziom oczu; 20..50 z gory; ponad 55 z lotu ptaka; ujemne = kamera nisko:
  -15..-35 heroiczny niski kat, ponizej -35 skrajnie z dolu (kamera przy ziemi).
- dist (metry, 1.2..8): ponizej 2.2 zblizenie twarzy; 3 polzblizenie; 4.5 plan sredni/cala postac; 6 i wiecej plan ogolny.
- fov (stopnie, 20..80): 35 = ok. 38 mm (domyslnie).
- fmt: "16:9" albo "9:16".
Okrazenie postaci planuj jako kilka ujec o rosnacym az (np. 0, 40, 90, 180).
TWARDE GRANICE (nigdy ich nie lam): postac jest zawsze fikcyjna i dorosla (18+); nigdy nie opisuj prawdziwej osoby
(znanej ani prywatnej) ani zdjecia prawdziwej osoby; nigdy nie tworz ani nie opisuj postaci niepelnoletniej ani wygladajacej
na niepelnoletnia. Jesli prosba lamie te granice, ustaw "refused": true, wyjasnij krotko w "reply", character=null i shots=[].
Poza tymi granicami nie dodawaj wlasnych ograniczen tresci dla fikcyjnych dorosłych postaci; trzymaj sie kierunku uzytkownika.
Nie twierdz, ze cos wygenerowales ani zaplanowales do wykonania - tylko proponujesz pola, a uzytkownik klika "Generuj"."""

_FIELDS = {"az": (-180, 180), "el": (-60, 85), "dist": (1.2, 8), "fov": (20, 80)}


def _extract_json(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i:j + 1])
        except json.JSONDecodeError:
            return None
    return None


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _s(v, n=600) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


# Siatka bezpieczenstwa po stronie programu (niezalezna od modelu): slowa wskazujace na postac niepelnoletnia.
_MINOR = re.compile(r"\b(child|children|kid|kids|teen|teens|teenage\w*|preteen|underage|toddler|loli\w*|shota\w*|"
                    r"nastolat\w*|dzieck\w*|dzieci\w*|niepe\w*nolet\w*|nielet\w*|maloletni\w*)\b|(\b1[0-7]\s*[- ]?(year|yo|lat|letni)\w*)",
                    re.IGNORECASE)
REFUSAL = ("Nie mogę zaproponować postaci niepełnoletniej ani wyglądającej na niepełnoletnią. Program obsługuje wyłącznie "
           "fikcyjne postacie dorosłe (18+).")


def _has_minor(*texts: str) -> bool:
    return any(_MINOR.search(t or "") for t in texts)


def validate(raw: dict) -> dict:
    """Przycina liczby do zakresow programu i teksty do rozsadnej dlugosci; wymusza granice dot. wieku postaci."""
    out = {"reply": _s(raw.get("reply"), 1500), "refused": bool(raw.get("refused")), "character": None, "shots": []}
    ch = raw.get("character")
    if isinstance(ch, dict) and not out["refused"]:
        out["character"] = {k: _s(ch.get(k), 300) for k in ("name", "archetype", "traits", "outfit", "style")}
        if "adult" not in out["character"]["archetype"].lower():  # zawsze dorosla (nie zalezy od kaprysu modelu)
            out["character"]["archetype"] = ("adult " + out["character"]["archetype"]).strip()
    shots = raw.get("shots")
    if isinstance(shots, list) and not out["refused"]:
        for s in shots:
            if len(out["shots"]) >= 12:  # limit liczony po odfiltrowaniu wpisow, ktore nie sa slownikami
                break
            if not isinstance(s, dict):
                continue
            out["shots"].append({
                "title": _s(s.get("title"), 80),
                "az": _num(s.get("az"), *_FIELDS["az"], 0), "el": _num(s.get("el"), *_FIELDS["el"], 5),
                "dist": _num(s.get("dist"), *_FIELDS["dist"], 4.5), "fov": _num(s.get("fov"), *_FIELDS["fov"], 35),
                "fmt": s.get("fmt") if s.get("fmt") in ("16:9", "9:16") else "16:9",
                "action": _s(s.get("action")), "outfit": _s(s.get("outfit")),
            })
    texts: list[str] = []  # sprawdzamy tylko propozycje (odpowiedz tekstowa moze cytowac odmowe)
    if out["character"]:
        texts += list(out["character"].values())
    texts += [f"{s['title']} {s['action']} {s['outfit']}" for s in out["shots"]]
    if _has_minor(*texts):
        return {"reply": REFUSAL, "refused": True, "character": None, "shots": []}
    return out


def ask(provider, message: str, history: list[dict], context: dict) -> dict:
    """provider: SogniProvider (uzywa jego klienta HTTP). Zwraca zwalidowana propozycje."""
    msgs = [{"role": "system", "content": SYSTEM}]
    ctx = json.dumps(context, ensure_ascii=False)[:1500]
    msgs.append({"role": "system", "content": "Biezacy stan programu (JSON): " + ctx})
    for h in history[-8:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:1500]})
    msgs.append({"role": "user", "content": message[:2000]})
    raw, text = chat_json(provider, msgs)
    if raw is not None:
        return validate(raw)
    # nadal bez JSON-a: pokazujemy tekst modelu, bez propozycji
    return {"reply": text.strip()[:1500], "refused": False, "character": None, "shots": []}


def chat_json(provider, msgs: list[dict], timeout: float = 70, attempts: int = 2) -> tuple[dict | None, str]:
    """Zapytanie do modelu jezykowego Sogni o odpowiedz JSON. Model czasem odpowiada tekstem zamiast JSON-a:
    ponawiamy z przypomnieniem. Zwraca (obiekt albo None, ostatni tekst)."""
    msgs = list(msgs)
    text = ""
    for _ in range(attempts):
        r = provider._call("POST", "/v1/chat/completions", retries=1, timeout=timeout,
                           json={"model": config.LLM_MODEL, "messages": msgs, "tool_choice": "none"})
        if r.status_code != 200:
            raise RuntimeError(provider._err(r))
        text = r.json()["choices"][0]["message"]["content"] or ""
        raw = _extract_json(text)
        if raw is not None:
            return raw, text
        msgs += [{"role": "assistant", "content": text[:1500]},
                 {"role": "user", "content": "Twoja odpowiedz nie byla poprawnym JSON-em. Odpowiedz ponownie "
                                             "WYLACZNIE jednym obiektem JSON w podanym schemacie, bez tekstu poza nim."}]
    return None, text


# Wspolne fragmenty promptow systemowych (kamera i twarde granice) - zrodlo prawdy dla asystenta i rezysera.
SHARED_RULES = SYSTEM[SYSTEM.index("Kamera (kamera"):SYSTEM.index("Nie twierdz")]
