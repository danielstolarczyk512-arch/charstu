"""Skladanie promptow z szablonow (kod, nie LLM)."""
import re

from .camera import describe

# Zdanie o liczbie osob w kadrze. W Etapie 0 "Only one person..." naprawilo pojawianie sie drugiej osoby w zblizeniu,
# wiec dla jednej postaci zostaje domyslne; dla pary wolajacy podaje two_people() zamiast niego (parametr `presence`).
ONE_PERSON_FRAME = "Only one person is visible in the frame."
ONE_PERSON_POSE = "Only one person is visible."


def two_people(a: str, b: str) -> str:
    """Zdanie o dwoch osobach w kadrze z jawnie nazwanymi rolami (a, b = krotkie opisy, np. imie)."""
    return (f"Exactly two people are visible: {a} and {b}. "
            "Keep both faces, both hairstyles and the scene unchanged.")


def character_block(c: dict, outfit_override: str = "") -> str:
    outfit = outfit_override.strip() or c.get("outfit")
    parts = [c.get("archetype"), c.get("traits"), outfit, c.get("style")]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _clean(s: str | None) -> str:
    return (s or "").strip().rstrip(".,; ")


# Stroj opisujacy brak ubrania: "wearing fully nude" jest bledne, wiec "wearing" pomijamy.
_UNCLOTHED = re.compile(r"^(?:(?:fully|completely|totally|entirely|almost|half|partially)[\s-]+)?(?:nude|naked|topless|bottomless|bare)\b",
                        re.IGNORECASE)


def wearing(cloth: str) -> str:
    """Fraza stroju: 'wearing X', a dla opisow bez ubrania (nude/naked/topless/bare) sam opis."""
    cloth = _clean(cloth)
    if not cloth:
        return ""
    return cloth if _UNCLOTHED.match(cloth) else f"wearing {cloth}"


def _described(c: dict, outfit: str) -> str:
    """Opis postaci zdaniem: 'archetyp with traits, wearing outfit'."""
    who = _clean(c.get("archetype")) or "a character"
    out = f"{who} with {_clean(c.get('traits'))}" if _clean(c.get("traits")) else who
    cloth = wearing(_clean(outfit) or _clean(c.get("outfit")))
    return f"{out}, {cloth}" if cloth else out


def image_prompt(c: dict, shot: dict, with_refs: bool = False, style: str = "natural", n_refs: int = 1,
                 presence: str | None = None) -> str:
    """Prompt obrazu w stylu oczekiwanym przez model (app/models.py):
    delta (edycje), rich_caption (Krea), compact (Z-Image), natural (Chroma/FLUX), spatial (Qwen 2512).
    presence: zdanie o liczbie osob w kadrze; None = jedna osoba (ONE_PERSON_FRAME), dla pary podaj two_people(...)."""
    presence = presence or ONE_PERSON_FRAME
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    action = _clean(shot.get("action")) or "standing in a neutral pose"
    outfit = (shot.get("outfit") or "").strip()
    if not with_refs and style != "delta":
        who, st = _described(c, outfit), _clean(c.get("style"))
        if style == "rich_caption":   # Krea 2: gesty, plynny opis obserwowalnej kompozycji i swiatla
            return (f"A {cam} of {who}. {action[0].upper() + action[1:]}. "
                    f"{('Rendered as ' + st + '.') if st else ''}").strip()
        if style == "compact":        # Z-Image: zwiezly opis zdaniowy
            return f"{who[0].upper() + who[1:]}, {action}. {cam}. {st}".strip().rstrip(".") + "."
        if style == "spatial":        # Qwen 2512: jawne relacje przestrzenne
            return (f"In the center of the frame: {who}, {action}. "
                    f"The camera is positioned for a {cam}; the subject fills the middle of the image and the "
                    f"environment extends behind her. {('Style: ' + st + '.') if st else ''}").strip()
        # natural (Chroma, FLUX schnell, modele nieznane): jeden zwiezly, spojny opis
        return f"{who[0].upper() + who[1:]}, {action}, {cam}. {st}".strip().rstrip(".") + "."
    if with_refs:
        # Edycja: krotka instrukcja zmiany (co sie zmienia, co zostaje, rola referencji) - sprawdzone testem widoku z tylu.
        role = (" Use the second reference image only for the character's face and outfit details." if n_refs >= 2 else "")
        if outfit:  # zmiana stroju: nie wymuszamy starego ubioru (wczesniej szablon sprzeczny z takim opisem)
            return (f"Show the same character from the reference image, {cam}. {action}. "
                    f"Change her clothing: {outfit}. {presence} "
                    f"Keep her face, hairstyle and the overall scene and lighting exactly the same.{role}")
        return (f"Show the same character from the reference image, {cam}. {action}. "
                f"{presence} "
                f"Keep her face, hairstyle, outfit and the overall scene and lighting exactly the same.{role}")
    return f"{character_block(c, outfit)}. {action}. Camera: {cam}."  # edycja bez referencji (awaryjnie)


def pose_prompt(c: dict, shot: dict, presence: str | None = None) -> str:
    """Poza z referencji (Qwen, sprawdzone testem): 1. obraz = postac z kanonu, 2. obraz = tylko poza ciala.
    Zdjecie pozy przecieka ubraniem/sylwetka, wiec prompt jawnie przypisuje twarz i strój do 1. obrazu."""
    presence = presence or ONE_PERSON_POSE
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    outfit = (shot.get("outfit") or "").strip()
    # Brzmienie zweryfikowane eksperymentem 3 (dluzsze/"zakazowe" wersje oddawaly obraz pozy prawie bez zmian).
    # Opis z karty (wlosy, strój) jest potrzebny: bez konkretow model oddaje obraz pozy prawie bez zmian.
    who = _clean(c.get("traits")) or "face and hairstyle"
    wear = _clean(outfit) or _clean(c.get("outfit"))
    keep = f"her face, {who}" + (f", the {wear}" if wear else "") + " and the background"
    return ("The woman in the first image takes the same body pose as the person in the second image. "
            f"Keep {keep} from the first image. Do not use the second person's face, hair or clothes. "
            f"{presence}")


def refine_prompt(instruction: str) -> str:
    """Poprawka obrazu: krotka instrukcja zmiany + co zostaje (wg przewodnika Sogni dla edycji)."""
    ins = _clean(instruction)
    return (f"{ins[0].upper() + ins[1:]}. Keep everything else in the image exactly the same: the pose, composition, "
            "background, lighting and the character's face and identity.")


# Opis zmiany ubrania w interakcji: wtedy klip nie wymusza niezmiennego stroju.
_OUTFIT_CHANGE = re.compile(r"\b(undress\w*|strip\w*|take[sn]?\s+off|takes?\s+off|pull\w*\s+off|remov\w+|unbutton\w*|unzip\w*|"
                            r"naked|nude|topless|clothes|clothing|lingerie)\b", re.IGNORECASE)


def _roles(c: dict, partner: dict) -> tuple[str, str]:
    """Krotkie, rozne etykiety A i B (imiona; przy braku lub rownych imionach opisowe)."""
    a, b = _clean(c.get("name")), _clean(partner.get("name"))
    if not a or not b or a.lower() == b.lower():
        a, b = (a or "the first person") + (" (first reference)" if a else ""),                (b or "the second person") + (" (second reference)" if b else "")
        if a == b:
            a, b = "the first person", "the second person"
    return a, b


def _who(c: dict) -> str:
    who = _clean(c.get("archetype"))
    traits = _clean(c.get("traits"))
    return f"{who} with {traits}" if who and traits else (who or traits)


def frame_guard() -> str:
    """Blok pozytywny o liczbie osob i rozdzielnosci cial (program nie wysyla promptu negatywnego, wiec 'bez trzeciej osoby'
    trzeba napisac wprost). Uzywany tylko w promptach pary (obraz i klip); dla jednej postaci nie wystepuje."""
    return ("There are exactly two people in the frame and nobody else. Two pairs of legs. "
            "Their bodies are separate and clearly distinct, not merged.")


def duet_prompt(c: dict, partner: dict, shot: dict, n_refs: int = 2, pose_ref: bool = False, interaction: str = "",
                outfit_a: str = "", outfit_b: str = "", slot_b: str = "partner_face", anatomy: str = "") -> str:
    """Prompt edycji dla pary (Qwen/Krea edit): jawnie wiaze role. Kolejnosc referencji jak w sogni.py: 1. obraz = A (twarz),
    2. = B (twarz), opcjonalnie 3. = tylko ulozenie cial. Partner nigdy nie jest 'the character'; bez zaimkow plci.
    Puste stroje = jak w referencjach. Jedyne zdanie o liczbie osob: two_people() (B2)."""
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    a, b = _roles(c, partner)
    action = _clean(shot.get("action"))
    inter = _clean(interaction or shot.get("interaction"))
    scene = f"Show {a} and {b} together, {cam}."
    if inter:
        scene += f" {inter[0].upper() + inter[1:]}."
    anat = _clean(anatomy)
    if anat:   # stala fraza pozycji z biblioteki, po opisie interakcji i niezalezna od tego, co wpisze uzytkownik
        scene += f" {anat[0].upper() + anat[1:]}."
    if action:
        scene += f" {action[0].upper() + action[1:]}."
    wear = []
    with_pose = pose_ref and n_refs >= 3
    lead_body = slot_b == "lead_body"   # 2. referencja = sylwetka A; B bez referencji, opisany slowami
    for name, ref, outfit, card in ((a, "first", outfit_a or shot.get("outfit"), c), (b, "second", outfit_b or shot.get("outfit_b"), partner)):
        out = wearing(_clean(outfit))
        if lead_body and name == b:
            if out:
                wear.append(f"{name} is {out}.")
            elif _clean(card.get("outfit")):
                wear.append(f"{name} wears {_clean(card.get('outfit'))}.")
            continue
        if out:
            wear.append(f"{name} is {out}.")
        elif with_pose and _clean(card.get("outfit")):
            # obraz ukladu cial przecieka ubraniem osob z obrazu (test 17.10.2026), wiec stroj z karty podajemy slowami
            wear.append(f"{name} wears {_clean(card.get('outfit'))} as in the {ref} reference image, not the clothes of the "
                        "people in the third reference image.")
        else:
            wear.append(f"{name} keeps the outfit from the {ref} reference image.")
    refs = [f"The first reference image shows {a}: use it only for {a}'s face and hairstyle"
            + (f" ({_who(c)})." if _who(c) else ".")]
    if lead_body:
        refs.append(f"The second reference image shows {a}'s body: use it only for {a}'s body shape and skin.")
        refs.append(f"{b} has no reference image; {b} is {_who(partner) or 'an adult'} and must look different from {a}.")
    else:
        refs.append(f"The second reference image shows {b}: use it only for {b}'s face and hairstyle"
                    + (f" ({_who(partner)})." if _who(partner) else "."))
    if pose_ref and n_refs >= 3:
        refs.append("The third reference image shows only the arrangement of the two bodies: copy only that body arrangement and "
                    "ignore the faces, hair, skin and clothes of the people in it.")
    return " ".join([scene, two_people(a, b), frame_guard(), *wear, *refs])


def _unclothed(*outfits: str) -> bool:
    """True, gdy ktorykolwiek ze strojow opisuje brak ubrania (nude/naked/topless/bare...)."""
    return any(_UNCLOTHED.match(_clean(o)) for o in outfits if o and _clean(o))


def video_prompt(c: dict, shot: dict, partner: dict | None = None, interaction: str = "", outfit_a: str = "",
                 outfit_b: str = "", anatomy: str = "") -> str:
    """LTX: jeden plynny akapit w czasie terazniejszym. Z `partner`: liczba mnoga, obie osoby nazwane; niezmienny strój jest
    wymuszany tylko, gdy zaden ze strojow nie opisuje braku ubrania (_UNCLOTHED na polach stroju A i B) i interakcja nie
    opisuje zmiany ubrania (_OUTFIT_CHANGE). Stroje domyslnie z ujecia (pola outfit / outfit_b)."""
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    if partner is not None:
        a, b = _roles(c, partner)
        inter = _clean(interaction or shot.get("interaction"))
        action = _clean(shot.get("action"))
        doing = " ".join(f"{t[0].upper() + t[1:]}." for t in (inter, _clean(anatomy), action) if t) or f"{a} and {b} stand close together and breathe."
        nude = _unclothed(outfit_a or shot.get("outfit"), outfit_b or shot.get("outfit_b"))
        keep = "faces and hairstyles" if (nude or _OUTFIT_CHANGE.search(inter)) else "faces, hairstyles and outfits"
        return (f"A {cam} of {a} and {b}. {doing} The camera moves smoothly and steadily while both people keep their own "
                f"{keep} throughout the entire clip. Both people stay clearly visible and distinct. {frame_guard()}")
    action = (shot.get("action") or "stands still and breathes").strip()
    return (
        f"A {cam} of {character_block(c, shot.get('outfit') or '')}. The character {action}. "
        "The camera moves smoothly and steadily while the character keeps the same face, "
        "hairstyle and outfit throughout the entire clip."
    )
