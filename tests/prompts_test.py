"""Testy promptow (B2): sciezka jednej postaci bez zmian wzgledem zlotego pliku + parametr `presence` i `wearing`.
Zloty plik tests/golden_prompts.json zrzucono z kodu PRZED zmiana B2 (139 promptow). python -m tests.prompts_test"""
import json
import os
import tempfile
from pathlib import Path

os.environ["STUDIO_DATA"] = tempfile.mkdtemp(prefix="studio-prompts-")
os.environ["PROVIDER"] = "mock"

from app import prompts  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""), flush=True)


gold = json.loads((Path(__file__).parent / "golden_prompts.json").read_text(encoding="utf-8"))
C = {"archetype": "adult huntress", "traits": "long silver braid, green eyes", "outfit": "green cloak and leather armor",
     "style": "cinematic fantasy, soft light"}
C2 = {"archetype": "adult knight", "traits": "", "outfit": "", "style": ""}
SHOTS = [
    {"az": 40, "el": 5, "dist": 4.5, "fov": 35, "action": "stands on a cliff at dawn", "outfit": ""},
    {"az": 180, "el": -45, "dist": 1.5, "fov": 50, "action": "", "outfit": "red silk dress"},
    {"az": 0, "el": 60, "dist": 7, "fov": 25, "action": "runs through rain", "outfit": "black leather jacket"},
]
bad = []
for ci, c in enumerate((C, C2)):
    for si, sh in enumerate(SHOTS):
        for style in ("rich_caption", "compact", "natural", "spatial", "delta"):
            for wr in (False, True):
                for n in (1, 2):
                    k = f"img|{ci}|{si}|{style}|{wr}|{n}"
                    if prompts.image_prompt(c, sh, with_refs=wr, style=style, n_refs=n) != gold[k]:
                        bad.append(k)
        for k, got in ((f"pose|{ci}|{si}", prompts.pose_prompt(c, sh)), (f"video|{ci}|{si}", prompts.video_prompt(c, sh)),
                       (f"char|{ci}|{si}", prompts.character_block(c, sh["outfit"]))):
            if got != gold[k]:
                bad.append(k)
if prompts.refine_prompt("make her braid longer") != gold["refine"]:
    bad.append("refine")
check("R1 sciezka jednej postaci: wszystkie zlote prompty identyczne", not bad, f"{len(gold)} promptow; rozne: {bad[:3]}")

sh = SHOTS[0]
one = prompts.image_prompt(C, sh, with_refs=True, style="delta", n_refs=1)
check("P1 domyslnie 'Only one person' w obu galeziach with_refs",
      "Only one person is visible in the frame." in one
      and "Only one person is visible in the frame." in prompts.image_prompt(C, SHOTS[1], with_refs=True, style="delta"))
tw = prompts.two_people("Mira", "Kael")
two = prompts.image_prompt(C, sh, with_refs=True, style="delta", n_refs=2, presence=tw)
check("P2 presence=two_people: 'Exactly two people', brak 'only one person'",
      "Exactly two people are visible: Mira and Kael." in two and "only one person" not in two.lower(), two)
two_o = prompts.image_prompt(C, SHOTS[1], with_refs=True, style="delta", n_refs=2, presence=tw)
check("P3 galaz 'Change her clothing' tez przyjmuje presence", "Change her clothing" in two_o
      and "Exactly two people" in two_o and "only one person" not in two_o.lower())
pp = prompts.pose_prompt(C, sh, presence=tw)
check("P4 pose_prompt z presence: bez 'Only one person'", "Exactly two people" in pp and "only one person" not in pp.lower())
check("P5 pose_prompt domyslnie bez zmian", prompts.pose_prompt(C, sh).endswith("Only one person is visible."))

nude = prompts._described(C, "fully nude")
check("W1 'fully nude' bez 'wearing'", "wearing" not in nude and nude.endswith(", fully nude"), nude)
for v in ("nude", "naked", "topless", "bare", "Bare-chested", "completely naked"):
    ok = "wearing" not in prompts._described(C, v)
    check(f"W2 '{v}' bez 'wearing'", ok)
check("W3 zwykly strój nadal 'wearing'", prompts._described(C, "red dress").endswith("wearing red dress"))
check("W4 'barely dressed' / 'bareback' nie sa traktowane jak brak ubrania",
      "wearing barely dressed" in prompts._described(C, "barely dressed"))
check("W5 strój z karty (nie z ujecia) tez przechodzi przez wearing",
      "wearing" not in prompts._described({**C, "outfit": "naked"}, ""))

# --- V. klip pary: wymuszanie stroju zalezy od POL STROJU, nie tylko od opisu interakcji (zadanie 1 etapu E5) ---
PA, PB = {"name": "Mira"}, {"name": "Kael"}
sh = {"az": 0, "el": 5, "dist": 3.0, "fov": 35, "action": "", "outfit": "", "outfit_b": ""}
v_nude = prompts.video_prompt(PA, sh, PB, "Mira and Kael lie close together on a bed", "fully nude", "fully nude")
check("V1 stroje 'fully nude': klip nie wymusza stroju", "keep their own faces and hairstyles" in v_nude and "outfits" not in v_nude, v_nude)
v_nude_b = prompts.video_prompt(PA, {**sh, "outfit_b": "naked"}, PB, "Mira and Kael lie close together on a bed")
check("V2 jedna osoba naga (pole ujecia outfit_b): bez wymuszania stroju", "outfits" not in v_nude_b)
v_dressed = prompts.video_prompt(PA, {**sh, "outfit": "red dress", "outfit_b": "grey suit"}, PB, "Mira and Kael dance")
check("V3 para ubrana, interakcja bez slow o ubraniu: stroj wymuszony", "faces, hairstyles and outfits" in v_dressed)
v_chg = prompts.video_prompt(PA, sh, PB, "Mira slowly removes his shirt")
check("V4 ubranie znika w trakcie klipu (interakcja): bez wymuszania stroju", "outfits" not in v_chg)

print(f"\nWYNIK: {sum(results)}/{len(results)}")
raise SystemExit(0 if all(results) else 1)
