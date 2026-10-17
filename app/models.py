"""Profile modeli obrazu: jak model oczekuje promptu i jakie ma ograniczenia.

Zrodlo struktur promptu: oficjalny przewodnik Sogni (sogni-creative-agent-skill, references/image-prompting.md) i
references/models.md. Identyfikatory: dokumentacja API (Generation Recipes, Personal LoRAs, Creative-agent skill).
`tested` = sprawdzone w tym projekcie prawdziwym renderem. Prompt negatywny NIE jest wysylany: nazwa argumentu nie
jest w dokumentacji, a test na Qwen 2512 (negativePrompt / negative_prompt) nie usunal wskazanych obiektow.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    op: str                 # generate | edit
    style: str              # rich_caption | compact | natural | spatial | delta
    max_refs: int = 0       # dla edycji: limit obrazow referencyjnych
    tested: bool = True     # wygenerowal obraz w tym projekcie (16.10.2026); jakosc oceniona tylko wizualnie
    note: str = ""


PROFILES: dict[str, Profile] = {p.id: p for p in [
    # --- generowanie (bez kanonu) ---
    Profile("krea-2-turbo", "Krea 2 Turbo", "generate", "rich_caption", tested=True,
            note="Gesty, plynny opis; bez skladni wag. Tylko generowanie."),
    Profile("dark-beast-krea2", "Dark Beast Krea 2", "generate", "rich_caption", note="Wariant Krea 2."),
    Profile("z-turbo", "Z-Image Turbo", "generate", "compact", note="Zwiezly opis zdaniowy."),
    Profile("z-image", "Z-Image", "generate", "compact", note="Zwiezly opis zdaniowy."),
    Profile("chroma-v46-flash", "Chroma v.46 flash", "generate", "natural", note="Jeden spojny opis naturalnym jezykiem."),
    Profile("chroma1-hd", "Chroma 1 HD", "generate", "natural", note="Jeden spojny opis naturalnym jezykiem."),
    Profile("flux1-schnell-fp8", "FLUX.1 schnell", "generate", "natural", note="Jeden zwiezly opis; bez tagow SD."),
    Profile("qwen-2512", "Qwen Image 2512", "generate", "spatial", tested=True,
            note="Szczegolowy opis z relacjami przestrzennymi."),
    Profile("qwen-2512-lightning", "Qwen Image 2512 Lightning", "generate", "spatial",
            note="Szczegolowy opis z relacjami przestrzennymi."),
    # --- edycja z referencja (kanon) ---
    Profile("krea-identity-edit", "Krea 2 Identity Edit", "edit", "delta", max_refs=2, tested=True,
            note="1-2 referencje (najpierw scena bazowa), instrukcja 1-4 zdan, bez promptu negatywnego."),
    Profile("dark-beast-krea2-identity-edit", "Dark Beast Krea 2 Identity Edit", "edit", "delta", max_refs=2,
            note="Wariant Krea Identity Edit; 1-2 referencje."),
    Profile("qwen", "Qwen Image Edit 2511", "edit", "delta", max_refs=3, tested=True, note="Do 3 referencji."),
    Profile("qwen-lightning", "Qwen Image Edit 2511 Lightning", "edit", "delta", max_refs=3, note="Do 3 referencji."),
]}


def get(model_id: str, op: str) -> Profile:
    """Profil znanego modelu; nieznany identyfikator dostaje profil ogolny (opis naturalnym jezykiem)."""
    p = PROFILES.get(model_id)
    if p and p.op == op:
        return p
    return Profile(model_id, model_id, op, "delta" if op == "edit" else "natural",
                   max_refs=2 if op == "edit" else 0, tested=False,
                   note="Wlasny identyfikator - profil ogolny, niesprawdzony.")


def catalog() -> dict:
    out: dict[str, list] = {"generate": [], "edit": []}
    for p in PROFILES.values():
        out[p.op].append({"id": p.id, "label": p.label, "style": p.style, "max_refs": p.max_refs,
                          "tested": p.tested, "note": p.note})
    return out
