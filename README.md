# Character Studio

Osobisty, lokalny program do tworzenia spójnych postaci, ujęć i klipów przez API.
Postacie muszą być **fikcyjne i dorosłe (18+)**. Program tego pilnuje przy tworzeniu postaci.

## Start

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
run.bat
```

Otwórz http://localhost:8000. Domyślnie działa dostawca `mock` (obrazy zastępcze, klip przez ffmpeg),
więc całość można wypróbować bez konta.

Test dymny: `.venv\Scripts\python -m tests.smoke`

## Podłączenie Sogni (po założeniu konta)

1. Klucz z https://dashboard.sogni.ai/api-key wpisz **samodzielnie** do `.env` jako `SOGNI_API_KEY`.
2. Ustaw `PROVIDER=sogni`.
3. Zrób Etap 0 (poniżej). Adapter `app/providers/sogni.py` powstał z dokumentacji i **nie był testowany na koncie**.

### Co jest niezweryfikowane (sprawdź w Etapie 0)
- Nazwa argumentu `edit_image` z referencjami: `SOGNI_EDIT_REF_ARG` (domyślnie `contextImageIndices`).
- Argumenty rozmiaru/proporcji obrazu i wideo: `SOGNI_IMAGE_ARGS`, `SOGNI_VIDEO_ARGS` (JSON w `.env`).
- Czy `edit_image` i modele wideo respektują wyłączony filtr treści na Twoim koncie.
- Czy sam tekst kąta wystarcza do trafienia w widok z tyłu, z góry i z dołu.

### Filtr treści
`SAFE_CONTENT_FILTER` w `.env` to oficjalne ustawienie Sogni (`safe_content_filter`). `false` wymaga uprawnionego
konta 18+. Przy odrzuceniu (`SAFETY_REJECTED`) program **nie ponawia** z innym filtrem, tylko pokazuje błąd.
Ochrona dzieci działa osobno i nie zależy od tego ustawienia.

### Koszty
`SOGNI_BILLING_MODE=subscription` = tylko plan Unlimited, bez wydawania Spark/SOGNI. Przycisk "Wyceń" wysyła
`confirm_cost: false`. Dzienny limit fair use jest egzekwowany przez Sogni; sprawdzaj app.sogni.ai/usage.
Wyniki u Sogni wygasają po ok. 48 h, więc program pobiera je od razu do `data/outputs`.

## Etap 0 (24 obrazy + 6 klipów)
1. Kąty: 6 ujęć x 2 warianty, jeden model. Sukces: 10/12 trafia w kąt i trzyma tożsamość.
2. Krea Identity Edit vs Qwen Edit (`EDIT_MODEL=krea-identity-edit` / `qwen`): 6 ujęć na model. Sukces: 5/6.
3. Wideo: najazd, okrążenie, zmiana kąta. `VIDEO_MODEL=ltx25` vs MiniMax H3. Sukces: 4/6 klipów.

## Struktura
- `app/` backend (FastAPI, SQLite, kolejka z limitami 4 obrazy / 1 wideo / 2 dźwięk, dostawcy w `app/providers`):
  `pipeline.py` (zlecanie zadań), `film.py` + `films_api.py` (model i API filmu), `director.py` (reżyser AI),
  `producer.py` (produkcja seryjna), `film_assemble.py` (montaż), `stitch.py` / `audio.py` (ffmpeg), `assistant.py`,
  `guard.py` (miara twarzy), `models.py` (profile modeli)
- `static/` interfejs (Studio: kamera 3D w three.js, kanon, galeria, dźwięk; Film: `film.js`)
- `data/` baza, kanon i wyniki (lokalnie)
- `tests/` testy (`smoke`, `models_test`, `assistant_test`, `audio_test`, `audio_api_test`, `film_test`, `director_test`,
  `film_assemble_test`) i skrypty doświadczalne z prawdziwym Sogni (`voice_experiment`, `live_film`, ...)

## Sklejanie klipów
W galerii zaznacz klipy (w kolejności, w jakiej mają iść) i kliknij "Sklej zaznaczone klipy". `app/stitch.py`
normalizuje rozmiar, 24 fps, format pikseli i dźwięk (AAC 48 kHz), a opcjonalne przenikanie (sekundy) przenika obraz
i dźwięk. Program podaje też skok wizualny na granicach klipów (różnica pikseli 0-255; to miara kompozycji/koloru,
nie tożsamości twarzy). Opcjonalnie `face_similarity` używa InsightFace, jeśli go sam zainstalujesz
(wagi na licencji niekomercyjnej; nie działa dla widoku z tyłu).

## Pomiar twarzy (opcjonalny)
`pip install -r requirements-face.txt` (InsightFace, wagi na licencji niekomercyjnej; model ok. 280 MB pobiera się sam).
Przy miniaturze wyniku pojawia się liczba (ArcFace): obraz vs kanon, klip vs własny kadr źródłowy (średnia i minimum
z 8 klatek). To miara **orientacyjna**: na stylizowanych twarzach nie odróżnia tej samej postaci od nowej o tym samym
opisie (kontrola dała 0,58, więcej niż poprawne edycje), a kąt kamery obniża wynik. Dobra do oceny trendu dryfu w klipie,
zła jako próg akceptacji. `FACE_GUARD=false` w `.env` wyłącza pomiar.

## Wybór modelu obrazu
Pod kamerą są dwa pola: **model obrazu** (generowanie bez kanonu) i **model edycji** (z kanonem jako referencją), oraz
przełącznik "Użyj kanonu jako referencji" (odznaczony = sam opis, tożsamość tylko z opisu). Pola mają listę znanych modeli
i przyjmują też własny identyfikator z katalogu Sogni (`GET /v1/model-catalog`). Wybór zapamiętuje się w przeglądarce;
domyślne modele ustawia `.env` (`IMAGE_MODEL`, `EDIT_MODEL`).
Program buduje prompt w stylu oczekiwanym przez model (wg oficjalnego przewodnika Sogni): Krea 2 - gęsty, płynny opis;
Z-Image - zwięzły opis; Chroma i FLUX schnell - jeden spójny opis; Qwen 2512 - opis z relacjami przestrzennymi; modele
edycji (Krea Identity Edit, Qwen Edit) - krótka instrukcja zmiany (co się zmienia, co zostaje, rola referencji, bez promptu
negatywnego). Model tylko do generowania nie przyjmie edycji (i odwrotnie) - program zgłasza to jako błąd przed wysłaniem.
Sprawdzone prawdziwym renderem (16.10.2026): wszystkie 13 modeli z listy generują obraz 1280x720; jakość oceniona tylko wizualnie.
Prompt negatywny NIE jest wysyłany: argument nie jest w dokumentacji, a test (`negativePrompt`, `negative_prompt`) na Qwen 2512 nie
usunął wskazanych obiektów. Własny identyfikator dostaje ogólny styl "jeden spójny opis". Testy: `python -m tests.models_test` (26).
Uwaga: bez referencji każdy render daje inną twarz - dla spójności postaci używaj modeli edycji z kanonem.

## Asystent
Panel "Asystent" (lewa kolumna): piszesz po polsku, co chcesz (nowa postać, seria ujęć, okrążenie), a asystent proponuje
pola postaci i listę ujęć (kąt, wysokość, dystans, format, akcja, strój). Karty wczytujesz do formularza przyciskiem;
**asystent niczego nie generuje ani nie zapisuje** - "Generuj" klikasz sam (kontrola zużycia limitu). Działa na modelu
językowym Sogni z planu (`LLM_MODEL` w `.env`; lista: `GET /v1/models`), wymaga `PROVIDER=sogni`.
Program nie dodaje własnych ograniczeń treści dla fikcyjnych dorosłych postaci; zachowanie zależy od wybranego modelu.
Twarde granice (w prompcie systemowym i w formularzu postaci): wyłącznie postacie fikcyjne i dorosłe (18+), bez prawdziwych
osób i bez postaci niepełnoletnich - przy takiej prośbie asystent odmawia (sprawdzone testem).

Testy asystenta: `STUDIO_URL=http://localhost:8001 python -m tests.assistant_test` (16 testów bez modelu + 17 z modelem; odpowiedzi
modelu są zmienne, więc asercje dotyczą struktury i zakresów). Po stronie programu (niezależnie od modelu): archetyp zawsze
dostaje `adult`, a propozycje zawierające słowa wskazujące na postać niepełnoletnią są odrzucane. Przy złym formacie odpowiedzi
asystent ponawia zapytanie raz.

## Strój w ujęciu
Pole "Strój w tym ujęciu" zmienia ubiór tylko w tym ujęciu. Puste: prompt każe zachować strój z kanonu. Wypełnione: prompt
nie wymusza starego stroju ("Change her clothing: ...", twarz i włosy zostają). Wcześniej szablon sprzeciwiał się każdej zmianie
stroju (test z 16.10: model zostawiał strój z kanonu). Sprawdzone na zwykłej zmianie ubioru; wynik dla innych opisów zależy od
modelu i ustawienia filtra treści.

## Poza z referencji
Panel "Poza z referencji" (kolumna postaci): dodajesz obraz pozy (plik albo gotowy szkielet: stoi, rece_w_gore, rece_skrzyzowane,
T, klek, siedzi, biegnie, luk), wybierasz go z listy i klikasz "Generuj obraz". API: `POST/GET /api/characters/{id}/poses`,
`pose_artifact_id` w `POST /api/shots/{id}/generate`. Poza z biblioteki to obraz w galerii z etykietą `poza:<nazwa>`.
Pod spodem: edycja modelem **Qwen Image Edit** z dwoma obrazami (1. kanon = twarz i włosy, 2. poza) i promptem "skopiuj tylko pozę".
Wymaga kanonu i wypełnionych cech/stroju w karcie postaci: prompt wymienia je konkretnie (bez opisu włosów i stroju model oddawał obraz pozy prawie bez zmian — sprawdzone 17.10). Wgrywaj wyłącznie obrazy wygenerowane lub rysunki — nie zdjęcia prawdziwych osób (liczy się tylko poza).

Wyniki testów 17.10.2026 (to nie jest gwarancja):
- **Krea Identity Edit nie przenosi pozy** z drugiego obrazu (ani jako baza, ani jako referencja) — program odrzuca taką kombinację.
- **Qwen + zdjęcie pozy**: poza przenosi się dobrze, ale potrafi "przeciekać" ubraniem i sylwetką osoby ze zdjęcia (w teście: zbroja
  wojownika zmieszana z zielonym płaszczem postaci). Najlepsze, gdy poza pochodzi od postaci w podobnym stroju.
- **Qwen + szkielet OpenPose**: niepewne (siedzenie wyszło mniej więcej, klęk/ukłon/T nie). Szkielety traktuj jako eksperyment.
- **Dwa kroki** (hybryda Qwen → przeniesienie osoby Krea/Qwen) nie zadziałały — poza ginęła.
Gdy poza ma być pewna, rozważ też opis słowny w polu akcji i kilka wariantów (liczba wyników 2-4), wybierając najlepszy.

## Jak program pomaga ustawić postać
- **Kreator cech**: listy wyboru (kolor/fryzura włosów, oczy, skóra, budowa, wiek dorosły, znak szczególny) dopisują angielskie
  frazy do pola "Cechy" — bez pisania z głowy. Ten sam wybór w grupie zastępuje poprzedni.
- **Edycja karty** (PATCH) i **szafa** (nazwane stroje do wyboru w ujęciach i filmie).
- **Arkusz postaci**: 4 widoki + 4 miny z kanonu (8 obrazów); najlepsze zatwierdzasz do kanonu.
- **Poprawka obrazu**: opisujesz jedną zmianę ("make her braid longer"), reszta kadru zostaje; do 4 wariantów.
- **Pomiar twarzy** (InsightFace) i limit prób na ujęcie pilnują spójności; asystent uzupełnia pola z opisu.
- **Poza z referencji** (wyżej) i **kamera 3D** (kąt, wysokość, dystans, FOV) dają kontrolę nad ujęciem.

## Klip start → koniec (okrążenie, zmiana kąta)
W wynikach kliknij "start" przy jednym obrazie i "koniec" przy drugim (muszą mieć te same proporcje), potem
"Klip start→koniec". Używa MiniMax H3 (`FLF_MODEL` w `.env`, argument `frameRole: "both"`). Zakończenie ruchu jest
zadane obrazem końcowym, więc to pewniejsze niż sam opis okrążenia w LTX.

## Dźwięk i głos
**Dźwięk wbudowany w klipy (LTX/H3) jest bardzo cichy i różny w każdym klipie** (zmierzone: od −57 do −33 LUFS, jeden klip
całkiem niemy, standard to −16), więc sama sklejka daje skoki głośności. Program robi to inaczej (`app/audio.py`):
- **Normalizacja** klipów do −16 LUFS (klipy poniżej −50 LUFS traktuje jako ciszę), a całość dwuprzebiegowym `loudnorm`
  (cel −16 LUFS, szczyt rzeczywisty ≤ −1,5 dBTP). Uwaga: `alimiter` ma domyślnie `level=enabled` i podbija dźwięk - zawsze `level=disabled`.
- **Podkład muzyczny** (Sogni `generate_music`, MiniMax Music 3, 10-300 s) przycięty do długości wideo, z płynnym wejściem
  i wyjściem, **ściszany pod lektorem** (sidechain).
- **Lektor** (Qwen3-TTS): kwestie po angielsku (lektor nie obsługuje polskiego, a program wykrywa polski tekst i go pomija).
  **Spójny głos:** tryb `design` tworzy NOWY głos przy każdym wywołaniu (ostrzega dokumentacja Sogni; zmierzone: rozrzut
  wysokości głosu 74 Hz). Program projektuje głos **raz** i klonuje próbkę do każdej kwestii (rozrzut 8,6 Hz). Można też
  wybrać stały głos studyjny (`serena`, `ryan`, ...). Ocena była obiektywna (F0), nie słuchowa - posłuchaj sam.
Panel "Dźwięk" w Studiu: głos, kwestie, muzyka; w sklejce: tryb dźwięku, podkład, kwestie.

## Film (widok "Film")
Całe filmy: **projekt → sceny → ujęcia**. Scena ma stałe miejsce i światło (wchodzą do każdego promptu ujęcia, więc
otoczenie jest spójne), ujęcie ma kamerę, akcję, strój, kwestię, czas 2-20 s i flagę "płynnie w następne" (klip start→koniec).
1. **Reżyser AI** ("Zaplanuj"): z pomysłu po polsku planuje zarys (tytuł, fabuła, podkład, sceny), potem ujęcia każdej sceny
   (dwa etapy, każdy krótki i walidowany). Tylko planuje - niczego nie generuje.
2. **Producent** ("Produkuj wszystko"): obrazy (edycja z kanonu), wybór najlepszego obrazu (auto), klipy, kwestie, podkład.
   Działa w tle i **przeżywa restart**. Kontrola kosztu: potwierdzenie z szacunkiem, **budżet** liczony z prawdziwego licznika
   zużycia planu (`/v1/subscriptions/usage`), limit 3 prób na zadanie, przerwa przy błędach sieci/limitach (ponowienie bez zużycia
   próby). Limity dobowe okresu próbnego ("... per UTC day"): H3 → ujęcie dostaje zwykły klip LTX (jawna notatka), inne →
   czekanie do północy UTC.
3. **Montaż** ("Zmontuj film"): kolejność z planu, przenikanie, dźwięk jak wyżej, napisy z kwestii (SRT albo wypalone przez libass),
   odtwarzacz w widoku.
Edycja ręczna: każde pole ujęcia/sceny, przenoszenie, usuwanie, "Obraz/Klip/Kwestia" osobno, "Reset" (zaczyna od zera), wybór
obrazu spośród kandydatów. Testy: `python -m tests.film_test` (42), `director_test` (17), `film_assemble_test` (18).

## Limity okresu próbnego Sogni (zmierzone 16.10.2026)
- **MiniMax H3: 6 klipów na dobę UTC w okresie próbnym** ("Start your paid Unlimited plan to keep creating"). Dotyczy przejść
  start→koniec (`FLF_MODEL`). Po wyczerpaniu program robi zwykłe klipy LTX.
- Dzienny limit "fair use" na szybkiej sieci istnieje, ale Sogni nie podaje jego wielkości (`fairUse: None`).
- Konto musi mieć zweryfikowany e-mail (inaczej zadania kończą się błędem "account session ended").
- Lektor Qwen3-TTS nie obsługuje polskiego.

## Ograniczenia i plany
Jeden bohater na film (kanon jednej postaci); podkład jeden na cały film; wynik oceniany wizualnie (twarz: miara orientacyjna);
brak upscalingu (FlashVSR), keyframes pośrednich H3 i ruchu kamery sterowanego geometrią. Szczegóły i pomiary: ETAP0_RAPORT.md.
