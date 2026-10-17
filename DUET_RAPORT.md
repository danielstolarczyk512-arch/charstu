# Raport Duet (tryb dwoch osob)

Branch `duet`. Raport rosnie z kazdym etapem; sekcje oznaczone jawnie, co zweryfikowano, a czego nie.
Konwencja jak w `ETAP0_RAPORT.md`: ocena obrazow jest wizualna i na malych probach, testy automatyczne to nie gwarancja jakosci renderu.

## Podsumowanie kryteriow akceptacji (szczegoly i zastrzezenia w sekcjach nizej)
| Kryterium z briefu | Wynik | Proba |
|---|---|---|
| 6 par na Qwen: 4/6 trzyma obie tozsamosci i trafia w interakcje | **spelnione: 4/6** (+1 czesciowo, 1 porazka: trzecia osoba) | n=6, 1 wariant, ocena wizualna |
| 2 pary na Dark Beast Identity Edit | interakcja 2/2, tozsamosc partnerki slabsza (zmiana stroju, twarz) | n=2 |
| 4 obrazy z obrazem interakcji: 2/4 poprawny uklad bez przecieku ubran | v1 promptu: **niespelnione** (uklad 4/4, przeciek 4/4); v2 (strój z karty slowami): **spelnione 3/4** | n=4 + 4, jeden seed |
| 2 klipy (i2v, start->koniec): obie osoby, bez zlania | **spelnione** (start->koniec z duchami w srodku) | n=2 |
| 1 film 2x2 z partnerem: plan sensowny, brak odmowy filtra, zmontowane | **spelnione** (19,9 s) | n=1 |
| Zero Premium Spark | **spelnione** (saldo 0 przed i po; ok. 357 Spark wartosci planu, 54 zadania) | licznik planu |
| `billing_mode: tokens` dla `wan3.0-spicy-video` | odrzucone HTTP 402 (errorCode 123) przed startem, plan nietkniety; **pelny sukces na Premium Spark niesprawdzony** (saldo 0) | n=2 zapytania |
Pomiar twarzy A/B (InsightFace): **niezweryfikowany na prawdziwych obrazach**. Sceny jednoznacznie seksualne: **nie renderowalem** (patrz sekcja E).

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

## B. Trzy naprawy

### B1. Wznawianie po `safety_review_required` (`providers/sogni.py::_poll`, test `tests/safety_resume_test.py`)
- Zamiast `SafetyRejected` od razu: `POST /v1/creative-agent/workflows/{id}/resume` z `safe_content_filter: false`, maks. `SAFETY_RESUME_ATTEMPTS`
  (domyslnie 2), potem czytelny `SafetyRejected` (komunikat zawiera `SAFETY_REJECTED`, wiec producent nadal nie traktuje go jako bledu przejsciowego).
  Zwykle odmowy (status `failed`) i inne `waitingReason` nie sa ponawiane.
- **Pierwsza wersja nie dzialala na prawdziwym koncie** i pokazala to dopiero sonda (`tests/resume_probe.py`): `/resume` odpowiada HTTP 202, ale stan
  zostaje `safety_review_required` jeszcze przez ok. 4 odpytania co 4 s i dopiero potem przechodzi w `completed`. Moja pierwsza wersja zuzywala
  oba wznowienia w ciagu kilku sekund i rzucala `SafetyRejected` mimo ze zadanie by sie wykonalo. Poprawka: karencja po `/resume`
  (`RESUME_GRACE_POLLS`=10 odpytan) przed kolejna proba. Zweryfikowane sonda na 1 zadaniu (Dark Beast Identity Edit, filtr `true` przy starcie):
  1 wznowienie wystarczylo, zadanie sie wykonalo.
- Obserwacja: zadanie z `safe_content_filter: true` na modelu Dark Beast trafilo do przegladu bezpieczenstwa nawet przy niewinnym promptcie
  (poza z mieczem). Zadania renderow Duetu szly z filtrem `false` od startu (`.env`: `SAFE_CONTENT_FILTER=false`); nie logowalem, czy ktores z nich
  przeszlo przez wstrzymanie i wznowienie, wiec nie wiem, jak czesto B1 jest faktycznie potrzebne przy filtrze `false`.
- Test: 8/8 z atrapa HTTP. Atrapa sprawdza logike petli, nie zachowanie Sogni (to sprawdzila sonda, n=1).

### B2. Zdanie o liczbie osob jako parametr (`prompts.py`, test `tests/prompts_test.py`)
- `image_prompt(..., presence=None)` i `pose_prompt(..., presence=None)`; domyslnie jak dawniej, dla pary `prompts.two_people(A, B)`:
  "Exactly two people are visible: {A} and {B}. Keep both faces, both hairstyles and the scene unchanged."
- `prompts.wearing()` / `_described()`: "wearing" pomijane dla opisow zaczynajacych sie od nude/naked/topless/bottomless/bare (takze z przyslowkiem:
  "fully nude", "completely naked"); "barely dressed" nadal dostaje "wearing".
- **Sciezka jednej postaci bez zmian**: zrzut 139 promptow zrobiony z kodu PRZED zmiana (`tests/golden_prompts.json`) jest identyczny po zmianach
  (test R1; obejmuje wszystkie style, `with_refs` on/off, stroj puste/wypelnione, 1 i 2 referencje, poze, klip, `character_block`).
- Pulapka znaleziona po drodze: znak `\b` zapisany przez skrypt w powloce trafil do pliku jako backspace (0x08), regex po cichu nie dzialal; wykryl to test W1.

### B3. `plan_pose` wg profilu modelu (`pipeline.py`, `models.py`)
- Zamiast `"krea" in model`: `op == "edit"`, `max_refs >= 2` i nowe pole profilu `pose_transfer` (True / False / None = nie sprawdzono) z powodem `pose_note`.
  `krea-identity-edit`: `pose_transfer=False` (wynik testu z 17.10 w README) z jego powodem w komunikacie; `qwen`: True.
- **Render** (`tests/pose_dark_beast_experiment.py`, te same wejscia co eksperyment 3 dla Qwen, n=2): `dark-beast-krea2-identity-edit` z kanonem jako 1. obrazem
  **przenosi poze** (uniesiony miecz, klek), ale z przeciekiem pancerza i koloru plaszcza ze zdjecia pozy; z odwrocona kolejnoscia obrazow (poza jako 1.)
  poza nie przeszla (zwrocil scene kanonu). Wynik: odrzucenie zdjete (`pose_transfer=True`), z opisem zastrzezen w `note`. Ocena wizualna, n=2, jeden model.
- Koszt eksperymentu: ok. 21 Spark wartosci, 2 zadania.

## Modele i pokrycie planem (dodatek do briefu)

- `models.Profile` ma teraz `kind` (image/edit/video/flf/music/speech/llm), `covered`, `category`, `catalog`, `known`, `i2v`; `catalog()` zwraca wszystkie rodzaje
  zgrupowane po `kind` (klucz `generate` zostaje aliasem `image`). `covered=False` zawsze ma powod w `note`. Istniejace wartosci `tested` nie zostaly zmienione.
- `billing_mode` zyje na poziomie zadania: `GenRequest.billing_mode`, ustawiany w `runner.job_billing()` (`tokens` dla modelu poza planem, inaczej `SOGNI_BILLING_MODE`;
  glos i muzyka wedlug konfiguracji). `confirm_cost: true` i przycisk "Wyceń" zostaly.
- Bramka Spark (`pipeline.check_spark`): model poza planem (takze nieznany identyfikator = `covered=False`) wymaga jawnej zgody (`allow_spark`; w UI pole
  "Potwierdzam zuzycie Premium Spark", w filmie `films.allow_spark`), a saldo Premium Spark (`GET /v1/account/balance`, pole `net`) jest sprawdzane PRZED wyslaniem
  (HTTP 402 z komunikatem). Znaczenie pol `/v1/account/balance` nie jest udokumentowane - odczyt na koncie: wszystkie 0.
- Katalog z API (`app/catalog_sync.py`): `GET /v1/model-catalog` (501 pozycji) i `GET /v1/models` (3 LLM), cache `data/model_catalog.json`, przycisk "Odśwież katalog",
  fallback do wbudowanej listy, ostrzezenie w logu o domyslnych modelach z `.env`, ktore zniknely; pozycje z rejestru nie znikaja (tylko `available=False`);
  nieznane pozycje katalogu (bez `coreml-*`) pojawiaja sie jako "nieznany, sprawdź".
- UI: wszystkie pola modelu to listy rozwijane (Studio: obraz, edycja, klip; Film: obraz, edycja + zgoda na Spark; Duet: edycja, klip) zasilane z `/api/models`,
  grupy wg kategorii, najpierw modele z planu, znaczniki "w planie" / "Premium Spark" / "niesprawdzony" / "nieznany, sprawdź", ostrzezenie przed wyslaniem.
  Wlasny identyfikator: ostatnia pozycja "Własny identyfikator…" (okno z polem, zapamietany w przegladarce). Test `models_plan_test` pilnuje, ze w `static/*.js`
  nie ma zaszytych identyfikatorow.

### Identyfikatory z listy w dodatku NIE wszystkie istnieja (sprzecznosc brief <-> API, poszlismy za API)
Walidacja Sogni (`400`, bez kosztu) wypisuje dozwolone `videoModel`. Dla `generate_video`: `ltx25, ltx23, wan22, seedance2, seedance2-mini,
seedance2-mini-uncensored, seedance2-5, seedance2-5-uncensored, minimax-h3-t2v(-turbo|-balanced), minimax-h3-fasth3-t2v-turbo(-2stage), happyhorse-1.1-t2v|i2v|r2v,
minimax-h3-r2v*, wan3.0-video, wan3.0-spicy-video`; dla `animate_photo`: `ltx25, ltx23, wan22, happyhorse-1.1-i2v|r2v, minimax-h3-i2v(-balanced|-turbo),
minimax-h3-fasth3-i2v-turbo(-2stage), minimax-h3-flf2v(-balanced|-turbo), minimax-h3-fasth3-flf2v-turbo(-2stage), wan3.0-video, wan3.0-spicy-video`.
| Z briefu | Stan | Co jest w rejestrze |
|---|---|---|
| `wan3`, `wan3-uncensored` | odrzucone przez walidacje | `wan3.0-video`, `wan3.0-spicy-video` (covered=False) |
| `seedance-2-0`, `-mini`, `seedance-2-5` | odrzucone | `seedance2`, `seedance2-mini`, `seedance2-5` + warianty `-uncensored` (covered=False, tylko tekst->wideo, `i2v=False`) |
| `happyhorse-1-1` | odrzucone | `happyhorse-1.1-i2v` (covered=False) |
| `minimax-h3`, `minimax-h3-turbo` | odrzucone | `minimax-h3-i2v`, `minimax-h3-i2v-turbo`, `minimax-h3-fasth3-i2v-turbo`; `-2stage` = covered=False (tag premium w katalogu) |
| `ltx23-22b-10eros-v1.4-fp8mixed_i2v` | jest w katalogu, ale NIE jako `videoModel` | usuniete z listy wyboru (nie bylo jak go uzyc) |
| LLM `deepseek-v4-flash-vision-exp`, `qwen-3-5-35b-abliterated` | inne id w `/v1/models` | `deepseek-v4-flash-vision-exp-dspark-1m`, `qwen3.5-35b-a3b-abliterated-gguf-q4km` |
| obrazowe `dark-beast-z-image-turbo`, `krea-2-identity-edit-lora-v1-2`, `albedobase-xl`, `juggernaut-xl`, ... | **nie do zweryfikowania walidacja** (argument `model` nie jest enumerowany, przechodzi nawet `__zzz__`) | w rejestrze z `tested=False`; potwierdzi je dopiero render |
| `chroma` | nie dodane | zostaja `chroma-v46-flash`, `chroma1-hd` (zweryfikowane w Etapie 0) |

### Weryfikacja `billing_mode` i pokrycia planem prawdziwym zadaniem (`tests/billing_probe.py`)
- Zadanie `generate_video` na `wan3.0-spicy-video` (5 s), `billing_mode: "tokens"`, `confirm_cost: false` i `true`: **HTTP 402, errorCode 123**
  ("requires credit-card-purchased Premium Spark Points or a VIP account. Top up Premium Spark"). Licznik planu przed i po: 283,06 -> 283,06 (roznica 0,0),
  saldo 0. Zadanie nie wystartowalo, **plan nie zostal ruszony**. To potwierdza, ze `wan3.0-spicy-video` jest poza planem i ze `billing_mode: tokens` jest respektowane
  jako tryb zlecenia - ale **nie sprawdzilem pelnego sukcesu zadania na Premium Spark**, bo konto ma saldo 0 (nie dokupilem Spark). Rozdzielczosc 480p NIE zostala ustawiona
  (nazwa argumentu nie jest potwierdzona, a Sogni ignoruje nieznane).
- **Poprawka tezy z dodatku**: z `billing_mode: "subscription"` to samo zadanie tez dostaje natychmiast HTTP 402 (errorCode 123) - nie "cicho sie zacina".
  Realna korzysc z `billing_mode` per zadanie to wiec poprawne rozliczenie zadan, ktore moga isc na Spark, oraz zgoda i kontrola salda przed wyslaniem.
- Zadania na modelach z planu wychodza z `billing_mode` z konfiguracji (test B2/B4/B5/A4) i nie ruszaja Spark (licznik planu rosnie, saldo 0 bez zmian).
- Koszt: 0 Spark, 0 zadan (oba zapytania odrzucone).
- Uwaga o koncie: `GET /v1/subscriptions/usage` zwraca `trialEndsAt: 2026-10-19`, wiec konto jest jeszcze w okresie probnym (limity z README: H3 6/dobe UTC).

## C. Duet: co zbudowano

Commity: `analiza`, `B1`, `B2`, `B3`, `modele`, `duet-rdzen`, `duet-okno`, `duet-test`, `raport`.
- Dane: `characters.kind`, `shots`/`films`/`film_shots`: `partner_id`, `interaction`, `outfit_b`; `artifacts.face_score_b/face_min_b`; tabela `interactions`.
  Migracja idempotentna w `app/db.py` (test E1: stara baza, dwa uruchomienia, dane zostaja). Usuwanie postaci uzywanej jako partner jest blokowane (409), bo SQLite uzywa
  ponownie numerow wierszy.
- `prompts.duet_prompt`, `pipeline.select_refs_duet` / `plan_image_duet` / `submit_image_duet`, bramka modelu (edycja z `max_refs >= 2`, ostrzezenie
  "brak slotu na referencję pozy/kąta" przy 2 referencjach), `video_prompt` w trybie pary, `guard.match_faces` + `similarity_duet` + `video_scores_duet`, `runner._measure_duet`,
  film i rezyser z partnerem (czas do 15 s tylko z partnerem), siatka `_MINOR` na partnerze i interakcjach.
- Okno "Duet": `app/duet.py`, `app/duet_api.py`, `static/duet.js` (wybor A i B, minimalny kanon partnera, biblioteka 10 pozycji + wlasne, opis interakcji, stroje A i B,
  kamera, 2-4 warianty, klip z ujecia, klip start->koniec, sklejka przez istniejacy `/api/stitch`, dwie liczby twarzy). Wybory pamietane w przegladarce.
- Odstepstwa od briefu: (1) trzeci slot referencji jest tylko na obraz interakcji - sylwetka/kat nie wchodza do referencji pary (twarz ma priorytet),
  (2) `INTERACTION_DEFAULT` zadeklarowany w konfiguracji i zwracany przez `/api/duet/config`, ale okno nie wybiera go automatycznie (wybor jest zapamietywany w przegladarce),
  (3) biblioteka ma opisy tekstowe bez obrazow (obrazy dodaje uzytkownik).

## D. Testy automatyczne (bez modelu)
| Test | Wynik |
|---|---|
| smoke | OK (4 zadania, 1 klip) |
| models_test | 29/29 (bylo 26, +3 nowe) |
| film_test | 42/42 (na Windows wymaga `PYTHONIOENCODING=utf-8`) |
| director_test | 17/17 |
| film_assemble_test | 18/18 |
| audio_test / audio_api_test | 21/21, 18/18 |
| character_test | 40/40 |
| **nowe:** safety_resume_test | 8/8 |
| prompts_test (regresja jednej postaci + B2) | 16/16 |
| models_plan_test | 40/40 |
| duet_test | 69/69 |
`assistant_test` wymaga dzialajacego serwera i modelu (`STUDIO_URL`) - nie uruchamialem.
Testy to nie gwarancja jakosci obrazu: nie mowia nic o tym, czy render trzyma twarze.

## E. Weryfikacja prawdziwym renderem (Sogni, konto z planem, `SAFE_CONTENT_FILTER=false`)
Warunki: kopia bazy i kanonu w katalogu tymczasowym (Twoj `data/studio.db` nietkniety), postac A = istniejaca Aria (kanon: 1 obraz twarzy/calej postaci, sylwetka,
przod), partner B = nowy fikcyjny dorosly "Kael" z minimalnym kanonem (twarz + sylwetka wygenerowane z opisu karty przez okno Duet, po 1 obrazie, oba zatwierdzone).
Ocena **wylacznie wizualna, jedna osoba oceniajaca (ja), male proby, 1 wariant na ujecie**. Pomiar twarzy (InsightFace) NIE byl uruchomiony na prawdziwych obrazach
(biblioteka nie jest zainstalowana w uzytym srodowisku), wiec "dwie liczby A/B" sa zweryfikowane tylko na sztucznych wektorach.
**Zakres tresci:** sceny par byly celowo ubrane/nieeksplicytne (uscisk, pocalunek, siedzenie na kolanach, spooning pod kocem, oparcie o sciane, spacer za reke).
Pozycji jednoznacznie seksualnych (missionary, cowgirl, doggy, oral) **nie renderowalem** - mechanizm (dwie tozsamosci, interakcja, uklad z obrazu referencyjnego)
jest ten sam, wiec wynik na nich nalezy sprawdzic samemu; nie ocenilem, jak model zareaguje na takie opisy.
Pliki: `data/duet_render/` (poza gitem), arkusze `sheet_*.png`.

### E1. 6 par na Qwen Image Edit + 2 na Dark Beast Identity Edit (kryterium: 4/6 trzyma obie tozsamosci i trafia w interakcje)
| Ujecie (Qwen) | Dwie osoby | Tozsamosci A i B | Interakcja | Uwagi |
|---|---|---|---|---|
| uscisk na klifie | tak | trzyma | trafiona | |
| pocalunek na ulicy | tak | trzyma | trafiona (pocalunek blisko policzka) | |
| siedzenie na kolanach | **NIE: trzy osoby** | - | - | po prawej ogromna, przycieta druga twarz Kaela; "Exactly two people" nie wystarczylo |
| spooning pod kocem | tak | trzyma | czesciowo (leza obok siebie, nie "lyzeczka") | Kael w zbroi w lozku |
| oparcie o sciane | tak | trzyma | trafiona | |
| spacer za reke | tak | trzyma | trafiona | |
**Qwen: 4/6 spelnia kryterium (uscisk, pocalunek, sciana, spacer), 1 czesciowe, 1 porazka (trzecia osoba).** Probka mala; wynik moze sie zmienic przy innych seedach.
| Ujecie (Dark Beast) | Interakcja | Tozsamosc |
|---|---|---|
| uscisk | trafiona | Kael trzyma; Mira: warkocz i kolor wlosow ok, ale strój zmieniony (granatowy zamiast zielonej peleryny), twarz slabo przypomina kanon |
| pocalunek | trafiona (prawdziwy pocalunek) | jak wyzej |
Dark Beast (2 referencje, ostrzezenie o braku slotu pokazane): interakcja 2/2, tozsamosc A slabsza niz na Qwen. n=2, wniosek wstepny.
Koszt: Qwen 42,2 Spark / 6 zadan, Dark Beast 13,9 / 2, kanon B 4,3 / 2.

### E2. Obraz interakcji jako 3. referencja (kryterium: 2/4 poprawne ulozenie bez przecieku ubran)
Obrazy ukladu (generowane, bez prawdziwych osob): pierwszy zestaw na Krea 2 Turbo odrzucilem (uciete glowy, zly uklad); drugi na Qwen 2512 byl uzywalny
dla 3 z 4 (uscisk, na kolanach, spooning), a "przy scianie" mial trzy osoby i wygenerowalem go trzeci raz. Obrazy dodane do biblioteki jako obraz pozycji;
referencje `[A_twarz, B_twarz, obraz_ukladu]`.
- **Wersja 1 promptu** ("keeps the outfit from the first reference image"): uklad przeniosl sie **4/4**, ale **ubrania przeciekly we wszystkich czterech**
  (beżowe koszulki z obrazu ukladu zamiast peleryny Miry i zbroi Kaela; twarze dryfowaly, Mira postarzala sie). Kryterium 2/4 **niespelnione** (best case 1/4: sciana).
- Poprawka: przy obrazie ukladu prompt podaje strój z karty slowami ("Mira wears ... as in the first reference image, not the clothes of the people in the third
  reference image") - ten sam mechanizm co w `pose_prompt` (wniosek z README: bez konkretow model kopiuje obraz pozy).
- **Wersja 2**: stroje A i B zachowane we wszystkich 4 (peleryna i skorzana zbroja Miry, granatowa tunika i napiersnik Kaela); uklad: sciana - trafiony (role zachowane),
  na kolanach - trafiony, uscisk - trafiony (Mira wyglada na starsza niz w kanonie), spooning - uklad slaby (leza, ale nie lyzeczka).
  **3/4 poprawne ulozenie bez przecieku ubran: kryterium spelnione** (n=4, jeden seed). Przeciek ubran z obrazu ukladu da sie ograniczyc opisem stroju w prompcie, ale tylko gdy karta postaci ma wypelniony strój.
- Koszt: obrazy ukladu ok. 27 Spark / 9 zadan (czesc wyrzucona), v1 ok. 28 / 4, v2 ok. 28 / 4.

### E3. Klipy (kryterium: obie osoby obecne, brak zlania sie w jedna)
- i2v (LTX 2.5, 5 s, 1344x768) z obrazu pocalunku: obie osoby obecne i rozdzielne przez caly klip (powolny najazd), tozsamosci stabilne. Spelnione.
- start->koniec (H3 flf2v turbo, 5,9 s) miedzy uściskiem z Qwen a uściskiem z obrazem ukladu: obie osoby obecne, bez zlania; w srodku klipu widoczne
  duchy/morfowanie (podwojny obraz wlosow i kaptura ok. 3. sekundy), koniec zgodny z obrazem koncowym. Spelnione z zastrzezeniem.
- Koszt: 23,0 + 23,9 Spark, 2 zadania. Limit H3 okresu probnego nie wystapil (nie liczylem, ile klipow H3 poszlo tego dnia lacznie).

### E4. Film 2 sceny x 2 ujecia z partnerem (kryterium: sensowny plan, brak odmowy filtra, zmontowane)
Plan rezysera AI (Qwen3.6) dla filmu "Powrot": 2 sceny (ulica z latarniami, kolacja w karczmie) x 2 ujecia, sensowne kamery i miejsca, obie postacie nazwane w opisach.
Produkcja: 4 obrazy pary (sciezka Duet, referencje A i B), 4 klipy, podklad muzyczny; montaz 19,9 s, -16,4 LUFS, 1344x768, z dzwiekiem; brak odmowy filtra.
Obrazy: obie tozsamosci stabilne w 4 ujeciach, strój i miejsce spojne w scenach. Czas: ok. 20 min produkcji. Koszt: 166,7 Spark / 22 zadania.
Zastrzezenia: rezyser **nie wypelnil** pola `interaction` (opisal interakcje w `action` z imionami), czasy ujec 4-6 s, wiec limit 15 s nie byl w tym tescie sprawdzony;
jedna kwestia lektora z planu nie zostala nagrana (`speech_needed 1, speech_done 0` - nie badalem przyczyny, film i tak zmontowany).

### Zuzycie (odczyt `GET /v1/subscriptions/usage`, dobowy licznik `renderSpark`)
Przed renderami Duetu (po eksperymencie B3 i sondzie `/resume`): 283,06 (49 zadan dziennie); po: 639,99 (103 zadania).
**Renderowanie Duetu: +356,9 Spark wartosci planu, +54 zadania** (zgodne z sumami etapow). Przed pierwszym odczytem poszly jeszcze eksperyment B3
(20,8 / 2 zadania, zmierzone) i sonda `/resume` (1 zadanie, nie zmierzone). Premium Spark: saldo 0 przed i po - **zero Premium Spark**. Wszystkie modele uzyte w renderach sa na planie (Qwen Image Edit, Dark Beast Identity Edit, Krea 2 Turbo,
Qwen Image 2512, LTX 2.5, MiniMax H3 flf2v turbo, Qwen3.6 LLM, MiniMax Music 3).

## F. Co wyszlo zle / niepewne
- Trzecia osoba na obrazie "na kolanach" (Qwen, tylko tekst) - zdanie "Exactly two people are visible" nie gwarantuje liczby osob. Z obrazem ukladu ten sam przypadek wyszedl poprawnie.
- Przeciek ubran z obrazu ukladu (wersja 1 promptu, 4/4) - ograniczony wersja 2, ale to tylko 4 obrazy.
- Tozsamosc A na Dark Beast (2 referencje) jest slabsza niz na Qwen (3 referencje).
- Pierwsza wersja B1 (wznawianie) nie dzialala na prawdziwym koncie; wykryta dopiero sonda.
- Pomiar twarzy A/B niezweryfikowany na prawdziwych obrazach; ograniczenia: miara orientacyjna (kontrola z ETAP0_RAPORT: ten sam opis z innym seedem dostal wiecej niz edycje z kanonu),
  bezuzyteczna przy widoku z tylu (0 twarzy), dwie podobne twarze moga zostac zamienione, a liczby nie mowia, czy osoby sie nie zlaly.
- Nie sprawdzono: sceny jednoznacznie seksualne, 15-sekundowe klipy, pelny sukces zadania na Premium Spark, rozdzielczosc 480p dla WAN 3, `krea-2-identity-edit-lora-v1-2` i inne nowe identyfikatory obrazowe.

## G. Rzeczy znalezione po drodze, ktorych nie naprawialem
1. `main.create_character` (bohater): brak `_has_minor` przy tworzeniu (jest tylko w `patch_character`); README sugeruje wiecej. Dla partnera (kind=partner) sprawdzane przy tworzeniu.
2. Pola `action`/`outfit` ujec Studia nie przechodza przez siatke wieku (robi to tylko `film.clean_shot`); `/api/shots` i `/api/preview` bez sprawdzenia.
3. `providers/sogni.py::_plan`: limit referencji edycji z podciagu `"krea" in model` zamiast profilu modelu (nowe modele edycji spoza tej reguly dostana limit 3).
4. Usuniecie postaci zostawia jej ujecia (`shots.character_id`) - przy ponownym uzyciu numeru wiersza SQLite ujecia moga trafic do nowej postaci (Duet blokuje tylko usuniecie partnera).
5. `.venv` w katalogu projektu wskazuje na Pythona innego uzytkownika Windows (`pyvenv.cfg`: `C:\Users\Daniel Stolarczyk\...`) i nie startuje; `.claude/launch.json` uzywa tego venv.
6. `index.html` nie mial `Cache-Control: no-cache` (pliki `static/*` mialy) - po dodaniu nowych elementow przegladarka serwowala stary HTML i stary `app.js` wywalal sie na nowym DOM (naprawione, bo dotyczylo zmian Duetu).
7. `producer.COST` nie zna kosztu wariantow Duet ani rzeczywistego kosztu klipow H3; szacunek budzetu filmu pary bedzie zanizony.
8. Studio `/api/artifacts?character_id=A` pokazuje tez wyniki par (to samo `shots.character_id`).
9. `tests/film_test` drukuje znaki spoza cp1250 - na Windows pada bez `PYTHONIOENCODING=utf-8`; `assistant_test` wymaga dzialajacego serwera.
10. Konto jest w okresie probnym do 2026-10-19 (`trialEndsAt`), mimo ze brief mowi o aktywnym planie Unlimited - limity dobowe okresu probnego (README) moga sie jeszcze stosowac.
11. Rezyser AI nie wypelnia pola `interaction` nawet gdy prompt systemowy o nie prosi (wstawia opis do `action`); dziala, ale pole `outfit_b`/`interaction` w UI filmu nie ma widocznych kontrolek (edycja tylko przez API).
12. Widok Film nie ma pola partnera przy tworzeniu filmu (tylko API `partner_id`); okno Duet nie tworzy filmow.
13. Modele `seedance2*` sa tylko tekst->wideo; wybor ich jako modelu klipu z obrazu daje czytelny blad (`i2v=False`), ale lista nadal je pokazuje.

## H. Koszt calosci (od poczatku prac)
Razem ok. 378 Spark wartosci planu i 57 zadan: B3 (Dark Beast, poza) 20,8 / 2, sonda `/resume` 1 zadanie (nie zmierzone), kanon B i pary 60,3 / 10,
obrazy ukladu i obrazy z ukladem ok. 83 / 17, klipy 46,9 / 2, film 166,7 / 22 (suma etapow renderow Duetu 356,9 / 54 jest zmierzona licznikiem planu).
Premium Spark: 0, wszystkie zadania na modelach objetych planem. Sondy `wan3.0-spicy-video` zostaly odrzucone przed startem (0 / 0).

## E5. Sceny jednoznacznie seksualne: co zrobiono, a czego NIE

**Etap renderowy E5 (8 obrazow par w scenach penetracji z nagimi ciałami, klipy, porownanie `lead_body` z `partner_face`) NIE zostal wykonany.**
Nie renderuje scen jednoznacznie seksualnych ani nie wpisuje do kodu fraz opisujacych akt, wiec nie mam wynikow liczbowych dla tych kryteriow
(dwie osoby 8/8, tozsamosci 6/8, geometria 6/8, nagosc 8/8) - nie ma ich w tym raporcie i nie wolno ich zakladac na podstawie sekcji E (sceny ubrane).
To samo dotyczy hipotezy, ze nagi obraz pozycji przenosi nagosc na wynik, oraz porownania `lead_body` z `partner_face`: **niezweryfikowane**.
Koszt tego etapu: 0 Spark, 0 zadan (nic nie zlecalem do Sogni).

Wykonane (tylko inzynieria, sprawdzone testami bez modelu - 89/89 `duet_test`, 20/20 `prompts_test`, reszta bez zmian):
- **Zadanie 1 (`fix-video-outfit`)**: `video_prompt` w trybie pary przyjmuje `outfit_a`/`outfit_b` (domyslnie z pol ujecia) i nie wymusza stroju, gdy ktorykolwiek
  strój opisuje brak ubrania (`_UNCLOTHED`) albo interakcja opisuje zmiane ubrania (`_OUTFIT_CHANGE`); wywolujacy (`pipeline.submit_video`, `/api/duet/plan`) przekazuja stroje.
  Testy V1-V4. Zgodnie z briefem to byl rzeczywisty blad: wczesniej sprawdzane bylo tylko pole interakcji.
- **Zadanie 2 (`slot-b-nude-body`)**: rola kanonu `body_nude`, `shots.ref_slot_b` (`partner_face` | `lead_body`, migracja idempotentna, domyslnie `partner_face`),
  `select_refs_duet(..., slot_b)` z cofnieciem i ostrzezeniem przy braku `body_nude`, prompt `lead_body` (B bez referencji, opisany slowami), przelacznik i formularze w oknie Duet,
  rola w Studiu i w `/api/coverage`. Testy J1-J7, J17-J20. **Pominiete: film i klipy nie czytaja `ref_slot_b` (tylko ujecia Duet).**
- **Zadanie 3b (`anatomia-antysmieci`)**: `prompts.frame_guard()` w promptach obrazu i klipu pary (nie w promptach jednej postaci; test J8-J9, golden bez zmian).
  **Odstepstwo od briefu:** nie zmienilem `two_people()` (dopisanie "nobody else" zmienialoby zdanie sprawdzane w testach i uzywane w promptach); "nobody else" jest w `frame_guard`.
- **Zadanie 3a (`anatomia-antysmieci`) - tylko infrastruktura**: kolumna `interactions.anatomy`, doklejanie w `duet_prompt`/`video_prompt` po opisie interakcji, pole "Anatomia pozycji"
  w oknie Duet, edycja przez `PATCH`, pole w formularzu wlasnej pozycji, zasiew nie nadpisuje wpisow uzytkownika. Wypelnilem tylko 5 pozycji bez scen jednoznacznie
  seksualnych (standing embrace, kiss, side by side, sitting on lap, against wall). **5 pozycji (spooning, missionary, cowgirl, doggy, oral) ma `anatomy` puste -
  kryterium "kazda z 10 pozycji ma wypelnione `anatomy`" jest niespelnione swiadomie;** frazy wpisujesz sam w interfejsie.
- **Zadanie 4 (`biblioteka-naga`) - tylko skrypt**: `tests/interaction_sheet.py` (jedna komenda, powtarzalny dla jednej pozycji, model z planu, prompt wylacznie z opisu i `anatomy`
  zapisanych w bazie plus `DUET_SHEET_STYLE`, obraz podlaczany jako `image_path` pozycji, mozliwa podmiana w UI). **Nie uruchamialem go.**

Aktualizacja sekcji F: wszystkie zastrzezenia z sekcji E dotycza scen ubranych; nic z sekcji E nie dowodzi zachowania w scenach jednoznacznie seksualnych
(trzecia osoba, tozsamosci, przeciek ubran, geometria, nagosc, klipy). Zalozenie z briefu, ze obraz pozycji "z nagoscia" ratuje geometrie (obraz pozycji pomogl w scenie ubranej "na kolanach"),
jest hipoteza do sprawdzenia przez Ciebie: `python -m tests.interaction_sheet`, potem Duet z `ref_slot_b` w obu ustawieniach.

Znalezione po drodze, nienaprawione: film i klipy z filmu nie czytaja `ref_slot_b`; `anatomy` nie jest przekazywana do klipu z ujecia zapisanego w bazie (klip bierze tylko opis
interakcji zapisany w ujeciu); `producer.COST` nadal bez kosztu wariantow Duet.
