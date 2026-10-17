"""Rejestr modeli (jedno zrodlo prawdy): obraz, edycja, wideo, klip start->koniec, muzyka, glos i model jezykowy.

Zrodlo struktur promptu: oficjalny przewodnik Sogni (sogni-creative-agent-skill, references/image-prompting.md) i
references/models.md. Identyfikatory: dokumentacja API (Generation Recipes, Personal LoRAs, Creative-agent skill) i
GET /v1/model-catalog oraz GET /v1/models (zapytane kluczem 17.10.2026).
`tested` = sprawdzone w tym projekcie prawdziwym renderem; wpisy dopisane 17.10.2026 maja tested=False, dopoki nie przejda renderu.
`covered` = objety planem Unlimited (fair use, 0 Spark); False = tylko Premium Spark (wtedy `note` podaje powod).
UWAGA: niektore identyfikatory (np. "qwen", "ltx25", "krea-identity-edit") to aliasy narzedzia creative-agent, ktorych NIE ma w
/v1/model-catalog (tam sa identyfikatory wewnetrzne, np. qwen_image_edit_2511_8bit). Alias bez wpisu w katalogu nie jest bledem,
ale tez nie jest potwierdzony przez katalog - potwierdza go dopiero render. Pokrycie planem (`covered`) pochodzi z listy
uzytkownika (konto Unlimited) i z tagu "premium" w katalogu, nie z odczytu planu przez API.
Prompt negatywny NIE jest wysylany: nazwa argumentu nie jest w dokumentacji, a test na Qwen 2512 (negativePrompt / negative_prompt)
nie usunal wskazanych obiektow.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    op: str                 # obraz: generate | edit; inne rodzaje: video | flf | music | speech | llm
    style: str              # rich_caption | compact | natural | spatial | delta (tylko obraz); dla reszty ""
    max_refs: int = 0       # dla edycji: limit obrazow referencyjnych
    tested: bool = True     # wygenerowal wynik w tym projekcie (16.10.2026); jakosc oceniona tylko wizualnie
    note: str = ""
    pose_transfer: bool | None = None   # edycja: czy przenosi poze z 2. obrazu; None = nie sprawdzono renderem
    pose_note: str = ""                 # powod, gdy pose_transfer=False (pokazywany w komunikacie bledu)
    kind: str = ""          # image | edit | video | flf | music | speech | llm
    covered: bool = True    # True = plan Unlimited (0 Spark), False = tylko Premium Spark
    category: str = ""      # grupa listy rozwijanej
    catalog: tuple = ()     # odpowiadajace identyfikatory z /v1/model-catalog (gdy znane)
    known: bool = True      # False = nie ma go w rejestrze ("nieznany, sprawdz")
    i2v: bool = True        # wideo: czy przyjmuje obraz startowy (animate_photo); False = tylko tekst->wideo


KINDS = ("image", "edit", "video", "flf", "music", "speech", "llm")
CATEGORIES = ("Fotorealistyczne", "Niescenzurowane", "Anime", "Edycja z kanonem", "Wideo", "Wideo niescenzurowane",
              "Muzyka", "Asystent")
_OP_KIND = {"generate": "image", "edit": "edit"}


def _p(id, label, op, style="", max_refs=0, tested=True, note="", category="", covered=True, catalog=(),
       pose_transfer=None, pose_note="", i2v=True):
    return Profile(id, label, op, style, max_refs, tested, note, pose_transfer, pose_note,
                   _OP_KIND.get(op, op), covered, category, tuple(catalog), True, i2v)


_POSE_KREA = "test z 17.10.2026 (README, 'Poza z referencji'): nie przenosi pozy z drugiego obrazu w zadnej roli obrazu"
_POSE_DB = ("Wariant Krea Identity Edit; 1-2 referencje. Poza z referencji: render 17.10.2026 (n=1, kanon jako 1. obraz) "
            "przeniosl poze, ale z przeciekiem pancerza i koloru plaszcza ze zdjecia pozy; przy odwroconej kolejnosci "
            "obrazow poza nie przeszla.")
_NEW = "Dopisany 17.10.2026 z listy pokrycia planu; identyfikator niepotwierdzony renderem."
_PREMIUM = "Poza planem, model dostawcy (tag premium w katalogu)."
_VID = "Identyfikator zweryfikowany walidacja Sogni (17.10.2026), render nie wykonany."

PROFILES: dict[str, Profile] = {p.id: p for p in [
    # --- generowanie (bez kanonu) ---
    _p("krea-2-turbo", "Krea 2 Turbo", "generate", "rich_caption", tested=True, category="Fotorealistyczne",
       note="Gesty, plynny opis; bez skladni wag. Tylko generowanie.", catalog=("krea2_turbo_fp8_scaled", "krea2_turbo_4bit")),
    _p("dark-beast-krea2", "Dark Beast Krea 2", "generate", "rich_caption", category="Niescenzurowane",
       note="Wariant Krea 2.", catalog=("dark_beast_krea2_fp8", "dark_beast_krea2_4bit")),
    _p("dark-beast-z-image-turbo", "Dark Beast Z-Image Turbo", "generate", "compact", tested=False,
       category="Niescenzurowane", note=_NEW + " W katalogu: dark_beast_z_image_turbo_*.",
       catalog=("dark_beast_z_image_turbo_8bit", "dark_beast_z_image_turbo_4bit")),
    _p("z-turbo", "Z-Image Turbo", "generate", "compact", category="Fotorealistyczne", note="Zwiezly opis zdaniowy.",
       catalog=("z_image_turbo_bf16",)),
    _p("z-image", "Z-Image", "generate", "compact", category="Fotorealistyczne", note="Zwiezly opis zdaniowy.",
       catalog=("z_image_bf16",)),
    _p("chroma-v46-flash", "Chroma v.46 flash", "generate", "natural", category="Niescenzurowane",
       note="Jeden spojny opis naturalnym jezykiem.", catalog=("chroma-v.46-flash_fp8",)),
    _p("chroma1-hd", "Chroma 1 HD", "generate", "natural", category="Niescenzurowane",
       note="Jeden spojny opis naturalnym jezykiem.", catalog=("chroma1-hd_fp8_scaled",)),
    _p("flux1-schnell-fp8", "FLUX.1 schnell", "generate", "natural", category="Fotorealistyczne",
       note="Jeden zwiezly opis; bez tagow SD. Pokrycie planem wg dodatku do briefu (nie bylo na pierwszej liscie).",
       catalog=("flux1-schnell-fp8",)),
    _p("qwen-2512", "Qwen Image 2512", "generate", "spatial", tested=True, category="Fotorealistyczne",
       note="Szczegolowy opis z relacjami przestrzennymi.", catalog=("qwen_image_2512_fp8",)),
    _p("qwen-2512-lightning", "Qwen Image 2512 Lightning", "generate", "spatial", category="Fotorealistyczne",
       note="Szczegolowy opis z relacjami przestrzennymi.", catalog=("qwen_image_2512_fp8_lightning",)),
    _p("one-obsession-v22", "One Obsession v2.2", "generate", "natural", tested=False, category="Anime",
       note=_NEW + " W katalogu: one_obsession_v22_fp16.", catalog=("one_obsession_v22_fp16",)),
    _p("albedobase-xl", "AlbedoBase XL", "generate", "natural", tested=False, category="Fotorealistyczne", note=_NEW),
    _p("juggernaut-xl", "Juggernaut XL", "generate", "natural", tested=False, category="Fotorealistyczne", note=_NEW),
    _p("cyberrealistic-xl", "CyberRealistic XL", "generate", "natural", tested=False, category="Fotorealistyczne", note=_NEW),
    _p("cyberrealistic-pony", "CyberRealistic Pony", "generate", "natural", tested=False, category="Niescenzurowane",
       note=_NEW),
    _p("pony-realism", "Pony Realism", "generate", "natural", tested=False, category="Niescenzurowane", note=_NEW),
    _p("dreamshaper-xl", "DreamShaper XL", "generate", "natural", tested=False, category="Fotorealistyczne", note=_NEW),
    _p("epicrealism-xl", "epiCRealism XL", "generate", "natural", tested=False, category="Fotorealistyczne", note=_NEW),
    # --- generowanie: poza planem (Premium Spark) ---
    _p("gpt-image-2", "GPT Image 2", "generate", "natural", tested=False, covered=False, category="Fotorealistyczne",
       note=_PREMIUM, catalog=("gpt-image-2",)),
    _p("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst", "generate", "natural", tested=False, covered=False,
       category="Fotorealistyczne", note=_PREMIUM, catalog=("gpt-image-2.5-sunburst",)),
    _p("gpt-image-2.5-flare", "GPT Image 2.5 Flare", "generate", "natural", tested=False, covered=False,
       category="Fotorealistyczne", note=_PREMIUM, catalog=("gpt-image-2.5-flare",)),
    # --- edycja z referencja (kanon) ---
    _p("krea-identity-edit", "Krea 2 Identity Edit", "edit", "delta", max_refs=2, tested=True, category="Edycja z kanonem",
       note="1-2 referencje (najpierw scena bazowa), instrukcja 1-4 zdan, bez promptu negatywnego.",
       pose_transfer=False, pose_note=_POSE_KREA, catalog=("krea2_identity_edit_v1_2",)),
    _p("krea-2-identity-edit-lora-v1-2", "Krea 2 Identity Edit LoRA v1.2", "edit", "delta", max_refs=2, tested=False,
       category="Edycja z kanonem", note=_NEW + " 2 referencje (wg listy pokrycia).", catalog=("krea2_identity_edit_v1_2",)),
    _p("dark-beast-krea2-identity-edit", "Dark Beast Krea 2 Identity Edit", "edit", "delta", max_refs=2,
       category="Edycja z kanonem", note=_POSE_DB, pose_transfer=True, catalog=("dark_beast_krea2_identity_edit_v1_2",)),
    _p("qwen", "Qwen Image Edit 2511", "edit", "delta", max_refs=3, tested=True, category="Edycja z kanonem",
       note="Do 3 referencji.", pose_transfer=True, catalog=("qwen_image_edit_2511_8bit",)),
    _p("qwen-lightning", "Qwen Image Edit 2511 Lightning", "edit", "delta", max_refs=3, category="Edycja z kanonem",
       note="Do 3 referencji."),
    # --- wideo (identyfikatory zweryfikowane walidacja Sogni 17.10.2026: animate_photo / generate_video wypisuja liste dozwolonych) ---
    _p("ltx25", "LTX-2.5", "video", tested=True, category="Wideo", note="Domyslny klip z obrazu (VIDEO_MODEL).",
       catalog=("ltx25-22b-int8_i2v_distilled",)),
    _p("ltx23", "LTX-2.3", "video", tested=False, category="Wideo",
       note=_VID + " W katalogu: ltx23-22b-fp8_*.", catalog=("ltx23-22b-fp8_i2v_distilled",)),
    _p("wan22", "WAN 2.2", "video", tested=False, category="Wideo", note=_VID + " W katalogu: wan_v2.2-14b-fp8_*.",
       catalog=("wan_v2.2-14b-fp8_i2v",)),
    _p("minimax-h3-i2v-turbo", "MiniMax H3 Turbo (z obrazu)", "video", tested=False, category="Wideo", note=_VID),
    _p("minimax-h3-fasth3-i2v-turbo", "MiniMax H3 FastH3 Turbo (z obrazu)", "video", tested=False, category="Wideo",
       note=_VID, catalog=("minimax-h3-fastvideo-int8_i2v_turbo",)),
    _p("minimax-h3-i2v", "MiniMax H3 (z obrazu)", "video", tested=False, category="Wideo", note=_VID,
       catalog=("minimax-h3-fl2va-fp8_i2v",)),
    _p("minimax-h3-fasth3-i2v-turbo-2stage", "MiniMax H3 FastH3 Turbo 2-stage (z obrazu)", "video", tested=False,
       covered=False, category="Wideo", note="Poza planem: wariant 2stage ma tag premium w katalogu. " + _VID,
       catalog=("minimax-h3-fastvideo-int8_i2v_turbo_2stage",)),
    _p("wan3.0-spicy-video", "WAN 3 Uncensored", "video", tested=False, covered=False, category="Wideo niescenzurowane",
       note="Poza planem, model dostawcy (Premium Spark). " + _VID + " W briefie: wan3-uncensored (taki identyfikator "
            "odrzuca walidacja Sogni).", catalog=("wan3.0-spicy-video",)),
    _p("wan3.0-video", "WAN 3", "video", tested=False, covered=False, category="Wideo",
       note="Poza planem, model dostawcy (Premium Spark). " + _VID + " W briefie: wan3 (taki identyfikator odrzuca walidacja Sogni).",
       catalog=("wan3.0-video",)),
    _p("happyhorse-1.1-i2v", "HappyHorse 1.1 (z obrazu)", "video", tested=False, covered=False, category="Wideo",
       note="Poza planem, model dostawcy (tag premium w katalogu). " + _VID + " W briefie: happyhorse-1-1 (taki identyfikator "
            "odrzuca walidacja Sogni).", catalog=("happyhorse-1.1-i2v",)),
    _p("seedance2", "Seedance 2.0 (tekst->wideo)", "video", tested=False, covered=False, category="Wideo",
       note=_PREMIUM + " Tylko generate_video (tekst->wideo), nie przyjmuje obrazu startowego. W briefie: seedance-2-0.",
       catalog=("seedance-2-0",), i2v=False),
    _p("seedance2-mini", "Seedance 2.0 Mini (tekst->wideo)", "video", tested=False, covered=False, category="Wideo",
       note=_PREMIUM + " Tylko generate_video. W briefie: seedance-2-0-mini.", catalog=("seedance-2-0-mini",), i2v=False),
    _p("seedance2-mini-uncensored", "Seedance 2.0 Mini Uncensored (tekst->wideo)", "video", tested=False, covered=False,
       category="Wideo niescenzurowane", note=_PREMIUM + " Tylko generate_video.", i2v=False),
    _p("seedance2-5", "Seedance 2.5 (tekst->wideo)", "video", tested=False, covered=False, category="Wideo",
       note=_PREMIUM + " Tylko generate_video. W briefie: seedance-2-5.", catalog=("seedance-2-5",), i2v=False),
    _p("seedance2-5-uncensored", "Seedance 2.5 Uncensored (tekst->wideo)", "video", tested=False, covered=False,
       category="Wideo niescenzurowane", note=_PREMIUM + " Tylko generate_video.", i2v=False),
    # --- klip start -> koniec ---
    _p("minimax-h3-fasth3-flf2v-turbo", "MiniMax H3 start->koniec (turbo)", "flf", tested=True, category="Wideo",
       note="frameRole='both', sourceImageIndex=-1, endImageIndex=-2, media w kolejnosci start, koniec (zweryfikowane).",
       catalog=("minimax-h3-fastvideo-int8_flf2v_turbo",)),
    _p("minimax-h3-flf2v-turbo", "MiniMax H3 start->koniec (turbo, wariant)", "flf", tested=False, category="Wideo",
       note=_VID + " Dozwolony w animate_photo wg walidacji; frameRole/indeksy jak dla wariantu fasth3 (niezweryfikowane)."),
    # --- muzyka i glos ---
    _p("music3", "MiniMax Music 3", "music", tested=True, category="Muzyka",
       note="Domyslny model generate_music (10-300 s); uzyty w filmie testowym bez debetu konta (16.10.2026)."),
    _p("ace_step_1.5_xl_turbo", "Ace-Step v1.5 XL Turbo", "music", tested=False, category="Muzyka", note=_NEW,
       catalog=("ace_step_1.5_xl_turbo",)),
    _p("ace_step_1.5_xl_sft", "Ace-Step v1.5 XL SFT", "music", tested=False, category="Muzyka", note=_NEW,
       catalog=("ace_step_1.5_xl_sft",)),
    _p("ace_step_1.5_turbo", "Ace-Step v1.5 Turbo", "music", tested=False, category="Muzyka", note=_NEW,
       catalog=("ace_step_1.5_turbo",)),
    _p("ace_step_1.5_sft", "Ace-Step v1.5 SFT", "music", tested=False, category="Muzyka", note=_NEW,
       catalog=("ace_step_1.5_sft",)),
    _p("qwen3-tts", "Qwen3-TTS (lektor)", "speech", tested=True, category="Muzyka",
       note="Tryby voice/design/clone; nie obsluguje polskiego.",
       catalog=("qwen3_tts_1.7b_custom_voice_bf16", "qwen3_tts_1.7b_voice_clone_bf16", "qwen3_tts_1.7b_voice_design_bf16")),
    # --- asystent i rezyser (GET /v1/models) ---
    _p("qwen3.6-35b-a3b-gguf-iq4xs", "Qwen3.6 35B A3B", "llm", tested=True, category="Asystent",
       note="Domyslny LLM asystenta i rezysera (LLM_MODEL)."),
    _p("deepseek-v4-flash-vision-exp-dspark-1m", "DeepSeek V4 Flash (vision, exp)", "llm", tested=False,
       category="Asystent", note=_NEW + " Identyfikator z GET /v1/models (w briefie: deepseek-v4-flash-vision-exp)."),
    _p("qwen3.5-35b-a3b-abliterated-gguf-q4km", "Qwen3.5 35B A3B abliterated", "llm", tested=False, category="Asystent",
       note=_NEW + " Identyfikator z GET /v1/models (w briefie: qwen-3-5-35b-abliterated)."),
]}


def get(model_id: str, op: str) -> Profile:
    """Profil znanego modelu; nieznany identyfikator dostaje profil ogolny (opis naturalnym jezykiem)."""
    p = PROFILES.get(model_id)
    if p and p.op == op:
        return p
    return Profile(model_id, model_id, op, "delta" if op == "edit" else "natural",
                   max_refs=2 if op == "edit" else 0, tested=False,
                   note="Wlasny identyfikator - profil ogolny, niesprawdzony. Nieznany, sprawdz: traktowany jako poza planem.",
                   kind=_OP_KIND.get(op, op), covered=False, category="Nieznane", known=False)


def covered(model_id: str) -> bool:
    """Czy model jest objety planem Unlimited. Nieznany identyfikator = False (zadanie pojdzie jako Premium Spark)."""
    p = PROFILES.get(model_id)
    return bool(p and p.covered)


def billing_for(model_id: str, default: str) -> str:
    """billing_mode zadania: 'tokens' (Premium Spark) dla modelu poza planem, inaczej wartosc z konfiguracji."""
    return default if covered(model_id) else "tokens"


def entry(p: Profile) -> dict:
    return {"id": p.id, "label": p.label, "style": p.style, "max_refs": p.max_refs, "tested": p.tested, "note": p.note,
            "kind": p.kind, "covered": p.covered, "category": p.category, "known": p.known, "available": True,
            "pose_transfer": p.pose_transfer, "i2v": p.i2v}


def _sort(items: list[dict]) -> list[dict]:
    cats = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(items, key=lambda e: (not e["covered"], cats.get(e["category"], 99), e["label"].lower()))


def catalog(extra: list[dict] | None = None, unavailable: set[str] | None = None) -> dict:
    """Wszystkie rodzaje zgrupowane po kind; w obrebie rodzaju najpierw modele z planu, potem reszta.
    `extra` = pozycje z katalogu API nieznane w rejestrze (format entry()); `unavailable` = identyfikatory z rejestru,
    ktorych nie ma juz w pobranym katalogu (oznaczane available=False, nigdy nie usuwane).
    Klucz "generate" to alias klucza "image" (zgodnosc ze starszym interfejsem)."""
    out: dict[str, list] = {k: [] for k in KINDS}
    seen: set[tuple] = set()
    for p in PROFILES.values():
        e = entry(p)
        if unavailable and p.id in unavailable:
            e["available"] = False
        out[p.kind].append(e)
        seen.add((p.kind, p.id))
    for e in extra or []:
        if (e["kind"], e["id"]) not in seen and e["kind"] in out:
            out[e["kind"]].append(e)
            seen.add((e["kind"], e["id"]))
    out = {k: _sort(v) for k, v in out.items()}
    out["generate"] = out["image"]
    return out
