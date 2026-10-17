# Raport Duet (tryb dwoch osob)

Branch `duet`. Raport rosnie z kazdym etapem; sekcje oznaczone jawnie, co zweryfikowano, a czego nie.
Konwencja jak w `ETAP0_RAPORT.md`: ocena obrazow jest wizualna i na malych probach, testy automatyczne to nie gwarancja jakosci renderu.

## A. Analiza: miejsca zakladajace jedna osobe lub sprzeczne z 18+ dwuosobowym

Przeszukane: `app/prompts.py`, `pipeline.py`, `film.py`, `producer.py`, `guard.py`, `assistant.py`, `director.py`,
`providers/sogni.py`, `runner.py`, `camera.py`, `main.py`, `static/`. Pozycje 1-8 z briefu potwierdzone; 9-22 sa nowe.

### Potwierdzone z briefu
| # | Plik / funkcja | Fragment | Skutek |
|---|---|---|---|
| 1 | `prompts.image_prompt` (obie galezie `with_refs`) | `"Only one person is visible in the frame."` | Model edycji dostaje jawny zakaz drugiej osoby; w Etapie 0 to zdanie bylo poprawka na pojawianie sie drugiej osoby w zblizeniu, wiec przy Duecie dziala dokladnie odwrotnie. |
| 2 | `prompts.pose_prompt` | `"The woman in the first image takes the same body pose..."`, `"Only one person is visible."` | Zaklada jedna kobiete; plec jest wpisana na stale. Kazda poza z referencji ma jedna osobe. |
| 3 | `prompts._described` | `f"{out}, wearing {cloth}"` | `outfit="fully nude"` daje `wearing fully nude`; dotyczy gałęzi bez referencji (generowanie od zera). |
| 4 | `prompts.video_prompt` | `"The character {action}"`, `"keeps the same face, hairstyle and outfit throughout the entire clip."` | Liczba pojedyncza i wymuszony niezmienny strój: sprzeczne ze scenami, w ktorych ubranie sie zmienia. |
| 5 | `pipeline.select_refs` | petla `for role in ("face","body",want)` po jednym `character_id` | Brak slotu na druga osobe; sylwetka i kat zjadaja limit referencji. |
| 6 | `pipeline.plan_pose` | `or "krea" in model` | Odrzuca kazdy model z "krea" w nazwie, takze `dark-beast-krea2-identity-edit` (edycja, 2 referencje) - bez sprawdzenia, czy faktycznie nie przenosi pozy. |
| 7 | `film.create_film` / tabela `films` | jedno `character_id` | Film ma jednego bohatera. |
| 8 | `director.plan_scene` | `d["duration"] = int(max(4, min(8, d["duration"])))` | Klipy zawsze 4-8 s. |

### Uzupelnienia
| # | Plik / funkcja | Fragment | Skutek |
|---|---|---|---|
| 9 | `prompts.image_prompt`, galaz `spatial` | `"the environment extends behind her"` | Plec i liczba osob wpisane na stale (Qwen 2512, generowanie bez kanonu). |
| 10 | `prompts.image_prompt`, galaz `with_refs` | `"Show the same character from the reference image"`, `"Keep her face, hairstyle..."` | "the same character", "her" - w Duecie nie wiadomo, kogo dotyczy. |
| 11 | `prompts.image_prompt`, `role` | `"Use the second reference image only for the character's face and outfit details."` | Przy 2 referencjach zaklada, ze druga to ta sama osoba; przy Duecie druga to inna osoba. |
| 12 | `prompts.pose_prompt` | `keep = f"her face, {who}"` + `"Do not use the second person's face, hair or clothes."` | Zakłada kobiete i jedna osobe w pozie; poza dwuosobowa wymaga innego sformulowania. |
| 13 | `camera.describe` | `"the camera is on the ground at her feet..."`, `"sky behind her head"` | Opis kamery zawiera "her" - przy parze mowi o jednej osobie. |
| 14 | `pipeline.SHEET_ITEMS` | `"stands ... arms at her sides"` | Arkusz kanonu zaklada kobiete i jedna osobe (w porzadku dla kanonu pojedynczej postaci; dotyczy tez minimalnego kanonu partnera). |
| 15 | `pipeline.plan_image` | `refs = select_refs(...)` jedna postac, `prof.max_refs` ucina | Brak sciezki dla dwoch postaci; przy `max_refs=2` sylwetka/kat nie zmieszcza sie obok drugiej twarzy. |
| 16 | `providers/sogni.py::_plan` (`edit`) | `req.refs = req.refs[:2] if "krea" in model else req.refs[:3]` | Limit referencji ustalany przez podciag nazwy, a nie profil modelu. Dla Dark Beast Identity Edit trafia przypadkiem, dla modelu spoza listy zle. |
| 17 | `providers/sogni.py::_poll` | `raise SafetyRejected(...)` przy `safety_review_required` | Kazde wstrzymanie przegladem bezpieczenstwa konczy zadanie, mimo ze `/resume` z `safe_content_filter:false` je odblokowuje (zadanie B1). W scenach 18+ to najczestszy punkt porazki. |
| 18 | `runner.build_request` | `refs` skladane z `canon_assets` jednej postaci + `ref_artifact_ids` | Nie ma pojecia "referencja drugiej postaci"; kolejnosc referencji zalezy od kolejnosci w `params` (najpierw `ref_ids`, potem artefakty). Dla Duetu to jest kolejnosc A, B, poza - wymaga, by A i B byly `ref_ids`, a poza `ref_artifact_ids`. |
| 19 | `runner.measure_artifact` / `guard.similarity` | porownanie z jednym kanonem `canon_face_path(character_id)`; `embedding_bgr` bierze tylko najwieksza twarz | Przy dwoch osobach pomiar dotyczy wylacznie jednej, najwiekszej twarzy i nie mowi nic o drugiej (zadanie C8). |
| 20 | `producer.shot_row` / `request_image` | `film["character_id"]`, `pipeline.submit_image(row, c, ...)` | Producent filmu nie zna partnera; `effective_shot` nie niesie `interaction`. |
| 21 | `assistant.SYSTEM`, `director.SCENE_SYSTEM` | `"co robi bohater"`, `"duration: 4-8 sekund"`, "Bohater filmu jest ten, ktory opisano w kontekscie" | Prompty systemowe zakladaja jednego bohatera i 4-8 s. |
| 22 | `static/app.js`, `static/film.js` | selektor jednej postaci (`S.char`, `fmChar`) | UI Studia i Filmu nie ma pojecia pary. |

### Sprzecznosci z uzyciem 18+ i luki w siatce wieku
| # | Plik / funkcja | Obserwacja | Skutek |
|---|---|---|---|
| 23 | `main.create_character` | Wymaga zaznaczonego pola `adult_fictional`, ale **nie** uruchamia `_has_minor` na polach tekstowych (robi to tylko `patch_character`). | Postac mozna utworzyc z opisem pasujacym do siatki; siatka zadziala dopiero przy edycji. README sugeruje wiecej. Dotyczy tez nowych postaci partnera - w Duecie siatka bedzie uruchamiana juz przy tworzeniu. |
| 24 | `main.create_shot` / `/api/preview` / `generate` | Pola `action` i `outfit` ujecia Studia nie przechodza przez `_has_minor` (robi to `film.clean_shot` tylko dla filmow). | Dla Duetu nowe teksty (`interaction`, stroje A i B, opis partnera) przechodza przez siatke. |
| 25 | `pipeline.submit_refine` | Tylko tu `assistant._has_minor(ins)` w Studiu. | Jak wyzej. |
| 26 | `prompts.image_prompt` (galaz bez `Change her clothing`) | Ujecie bez `outfit` kaze zachowac strój z kanonu: `"Keep her face, hairstyle, outfit ... exactly the same"` | W scenie, gdzie ubranie ma zniknac, puste pole stroju zostawia ubranie z kanonu. To intencja projektu (puste = jak w kanonie), ale dla 18+ trzeba pisac strój jawnie. |
| 27 | `sogni._plan` | `"safe_content_filter": req.safe_filter` ustawiane tylko przy starcie | Rozwiazuje B1 tylko czesciowo: `/resume` ma wlasne pole. |
| 28 | `main.estimate`, `producer.COST` | Koszty szacowane tylko dla jednego obrazu; Duet wysyla 2-4 warianty | Szacunek budzetu dla filmu Duet bedzie zanizony, dopoki `COST["image"]` nie uwzgledni wariantow. |

Nie znaleziono: odwolan do filtra w `film_assemble.py`, `stitch.py` ani `audio.py` (nie dotycza tresci).
