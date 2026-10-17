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


def video_prompt(c: dict, shot: dict) -> str:
    """LTX: jeden plynny akapit w czasie terazniejszym."""
    cam = describe(shot["az"], shot["el"], shot["dist"], shot["fov"])["en"]
    action = (shot.get("action") or "stands still and breathes").strip()
    return (
        f"A {cam} of {character_block(c, shot.get('outfit') or '')}. The character {action}. "
        "The camera moves smoothly and steadily while the character keeps the same face, "
        "hairstyle and outfit throughout the entire clip."
    )
