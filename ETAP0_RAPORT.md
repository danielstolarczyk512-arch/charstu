# Raport Etapu 0 (16.10.2026)

Postac testowa: fikcyjna dorosla lowczyni (srebrny warkocz, zielona peleryna, skorzana zbroja).
Wszystkie wyniki ocenione wizualnie przez Claude'a; to male proby (1 wariant na ujecie), nie statystyka.

## Obrazy (Krea Identity Edit, 1 referencja = kanon z przodu)
| Ujecie | Wynik | Uwagi |
|---|---|---|
| Tyl | TRAFIONE | warkocz i peleryna zgodne, ta sama sceneria |
| 3/4 | TRAFIONE | |
| Profil | TRAFIONE | czysty widok z boku |
| Z gory (el 55, dystans 6) | TRAFIONE | wyrazna perspektywa z gory |
| Zblizenie twarzy | TRAFIONE po poprawce | bez "Only one person is visible" pojawila sie druga osoba na kadrze |
| Z dolu (el -25) | CZESCIOWO | wychodzi niemal na poziomie oczu; Krea slabo zmienia wysokosc kamery na niska |

Wynik: 5 z 6 poprawnych po poprawkach (kryterium sukcesu z planu: 10 z 12 - za mala proba, by orzec).

## Krea Identity Edit vs Qwen Edit (widok z tylu)
Krea wyraznie lepsza: Qwen zmienil tlo, byl mniej ostry i bardziej skrecony. Przy 1 probie - wstepne.

## Wideo (LTX 2.5, 5 s, 24 fps)
- A (i2v, najazd): tozsamosc trzyma; kamera zmienia kat (lekki obrot do profilu) zamiast czystego najazdu. 117 s.
- C (i2v, okrazenie z samego promptu): przod -> profil -> tyl, tozsamosc spojna. 53 s. Najlepszy wynik testu.
- B (MiniMax H3 first/last frame): NIEROZWIAZANE - blad "requires both first- and last-frame images"
  dla 6 kombinacji indeksow i 2 selektorow modelu. Dokumentacja nie podaje, jak przekazac ostatnia klatke.
- Rozdzielczosc wyjscia LTX zalezy od obrazu wejsciowego: 16:9 -> 1344x768, kwadrat -> 768x768.

## Ustalenia techniczne (zweryfikowane testem)
- Generate/edit image: argument `aspectRatio` ("16:9") dziala (1280x720); domyslnie 1024x1024.
- `edit_image`: referencje przez `media_references` + `contextImageIndices: [-1]` dzialaja.
- Krea Identity Edit: max 2 obrazy referencyjne; Qwen: do 3 (dokumentacja Sogni).
- `change_angle` z opisem tekstowym NIE zmienil kata (wymaga innego formatu, niezbadane).
- Walidacja przed startem ignoruje nieznane argumenty - nazwy trzeba sprawdzac prawdziwym renderem.
- Blad "account session ended" = niezweryfikowany e-mail konta Sogni.

## Koszt/limity
Po calym etapie: patrz ostatni odczyt /v1/subscriptions/usage (ok. 3-4 Spark na obraz, klip ok. kilkanascie Spark).
Dzienny limit fair use nie jest jawnie podawany (`fairUse: None`).

## Sklejanie i dryf (3 klipy LTX 2.5 z zatwierdzonych stillow: 3/4, profil, zblizenie; 5 s kazdy)
- Sklejka ffmpeg (app/stitch.py): twarde ciecie 15,13 s i przenikanie 0,5 s 14,13 s; dlugosci zgodne z obliczeniami;
  audio vs wideo rozni sie o 32 ms (ciecie) i 95 ms (przenikanie) - bez zauwazalnego rozjazdu.
- Skok wizualny na granicach: roznica pikseli 46 i 58 (skala 0-255), przesuniecie koloru ok. 25-28. Duzy,
  bo kazdy klip startuje z innego kadru - to ciecie montazowe, nie ciaglosc. Przenikanie go lagodzi.
- Dryf tozsamosci WEWNATRZ klipow (ocena wizualna, 5 klatek na klip): warkocz, peleryna i zbroja stabilne.
  Klip profil->tyl: warkocz robi sie luzniejszy/bardziej rozwiany w drugiej polowie (lagodny dryf wlosow), pojawia sie flare.
  Klip zblizenie: twarz stabilna, na koncu rozmycie ruchu przy obrocie.
- Miedzy klipami: ta sama postac rozpoznawalna (warkocz, peleryna, scenografia), ale twarz w zblizeniu wyglada
  nieco mlodziej/miekko niz w ujeciu srednim - lagodny dryf miedzy klipami.
- NIE zmierzono podobienstwa twarzy liczbowo (brak InsightFace; wymaga pobrania modeli ok. 280 MB, licencja
  niekomercyjna) - ocena jest wizualna i subiektywna.
- Koszt: 3 klipy ok. 69 Spark wartosci lacznie (ok. 23 Spark/klip); razem w calym Etapie 0: 40 zadan, ok. 198 Spark (0,99 USD).

## Pomiar twarzy (InsightFace buffalo_l, ArcFace) - kalibracja i wnioski
Zainstalowano onnxruntime + insightface; model buffalo_l (ok. 280 MB) pobrany za zgoda uzytkownika. Licencja wag: niekomercyjna.
- Wykrywanie: twarz znaleziona na wszystkich obrazach poza widokiem z tylu (0 twarzy) - brak twarzy NIE jest porazka.
- KONTROLA NEGATYWNA: obraz wygenerowany z tego samego opisu, ale z innym seedem (inna twarz) dostal 0,58 -
  WYZEJ niz wszystkie obrazy edytowane z kanonu (0,28-0,48), ktore wizualnie sa ta sama postacia.
  => Na stylizowanych twarzach fantasy ArcFace NIE odroznia "tej samej postaci pod innym katem" od "nowej postaci o tym
  samym opisie", a kat kamery silnie obniza wynik. Nie wolno uzywac progu do automatycznego odrzucania/akceptacji.
- Co dziala: trend w klipie wzgledem WLASNEGO kadru zrodlowego (ta sama poza na starcie):
  klip 3/4: 0,70 -> 0,37 | klip profil->tyl: 0,72 -> 0,21 | klip zblizenie: 0,92 -> 0,38 (na koncu obrot i rozmycie) |
  okrazenie z przodu na tyl: 0,58 -> -0,01 (twarz znika z kadru). Zgadza sie z ocena wizualna (dryf rosnie z obrotem).
- W programie: pomiar po kazdym wyniku (FACE_GUARD=true), przycisk "zmierz twarz" dla starszych, liczba przy miniaturze
  z opisem ograniczen. Miara orientacyjna - decyzja o akceptacji zostaje po stronie czlowieka.

## Naprawione: H3 first/last frame i ujecie z dolu
- **MiniMax H3 first/last frame - DZIALA.** Brakujacy argument: `frameRole: "both"` (w dokumentacji tylko w przykladzie
  z keyframes). Poprawna konfiguracja: `animate_photo`, `videoModel: "minimax-h3-fasth3-flf2v-turbo"`,
  `frameRole: "both"`, `sourceImageIndex: -1`, `endImageIndex: -2`, `duration: 6`; media_references w kolejnosci start, koniec.
  Wynik: pelne okrazenie przod -> 3/4 -> profil -> tyl, ostatnia klatka zgodna z zadanym obrazem (pewne zakonczenie ruchu,
  czego nie gwarantuje okrazenie z samego promptu w LTX). Czas 54-95 s na klip 5,9 s (1344x768, 24 fps, z dzwiekiem).
- **Pulapka proporcji:** kwadratowy kadr startowy + kadr koncowy 16:9 -> klip z przycieta glowa na poczatku.
  Program odrzuca teraz pary obrazow o roznych proporcjach.
- **Ujecie z dolu - DZIALA z mocnym opisem kamery** (Krea Identity Edit): "extreme worm's-eye view, the camera is on the
  ground at her feet tilted steeply upward..." daje prawdziwy widok od dolu z zachowana postacia; "heroic low-angle shot from
  ground level..." daje umiarkowany niski kat. Lagodne "low angle, shot from below" bylo ignorowane. Qwen przy tym samym
  prompcie zmienil postac (ciemne wlosy, dziwna poza) - slabszy.
  W programie: el < -35 = skrajnie z dolu, -35..-15 = heroiczny niski kat (app/camera.py).
- Test w programie: 3 obrazy (przod, tyl, z dolu el -45) + klip start->koniec - wszystkie poprawne.
- Zuzycie po calym Etapie 0 i poprawkach: 53 zadania, ok. 311 Spark wartosci (1,56 USD); klip H3 ok. 25-30 Spark.

## Dzwiek i glos (16.10.2026)
- Pomiar klipow LTX/H3: wbudowany dzwiek jest bardzo cichy i rozny (-56,9 / -inf (cisza) / -38,1 / -44,9 / -33,5 / -37,5 / -32,9 LUFS;
  standard -16). Sklejka bez obrobki = skoki glosnosci i znikanie dzwieku -> normalizacja + wspolny podklad + lektor.
- Eksperyment glosu (Qwen3-TTS, 3 kwestie, rozrzut mediany F0 miedzy kwestiami; przyblizenie obiektywne, nie sluchowe):
  design osobno dla kazdej kwestii 74,3 Hz (kwestia #2 wyraznie inny mowca), glos studyjny (ryan) 52,5 Hz,
  design raz + klon 8,6 Hz (klony 91-100 Hz vs probka 87 Hz). Potwierdza ostrzezenie dokumentacji; program robi "design raz + klon".
- Qwen3-TTS nie obsluguje polskiego (lista jezykow w dokumentacji Sogni).
- Pulapki ffmpeg: `alimiter` ma domyslnie level=enabled (podbija sygnal do 0 dB - glosnosc o ok. 2 dB za duza, szczyt 0 dBTP);
  jednoprzebiegowy loudnorm chybial cel o ok. 3 LU. Rozwiazanie: level=disabled + dwuprzebiegowy loudnorm liniowy (cel -16 LUFS, TP -1,5).
  Wynik na prawdziwym filmie: -16,1 LUFS, szczyt -1,37 dBTP.

## Pierwszy caly film na Sogni (przez program, 16.10.2026)
Pomysl po polsku -> Rezyser AI (model Qwen3.6 z planu) zaplanowal "Ostatni Swit Doliny": 3 sceny x 2 ujecia, kamera, kwestie po angielsku,
podklad, 3 przejscia start->koniec. Produkcja: 6 obrazow (edycja z kanonu), 6 klipow, 3 kwestie (klon glosu), podklad 20 s; montaz 32,2 s,
napisy wypalone, 15,5 MB. Czas: ok. 15 min produkcji + 3 min odzyskania jednego ujecia. Zuzycie: ok. 286 Spark wartosci z licznika planu
(debit na koncie 0). Ocena wizualna: bohaterka spojna (warkocz, peleryna, zbroja), stale miejsce i swiatlo w scenach; w scenie klifu wlosy
jasniejsze (lagodny dryf), zmiany kadru miedzy klipami widoczne jako ciecia/przenikania.
Bledy znalezione dopiero przez prawdziwa produkcje i testy (wszystkie naprawione):
1. Limit okresu probnego "MiniMax H3: 6 videos per UTC day" -> ujecie wyczerpalo 3 proby. Teraz: bez zuzycia prob, awaryjny klip LTX z notatka.
2. Brak komunikatu przyczyny przy `waiting_for_user` (tylko "permission_required") -> adapter dolacza ostatni komunikat workflow.
3. Reset ujecia nie zerowal licznika prob -> ujecie padalo od razu ponownie (teraz stare proby = 'superseded').
4. SQLite uzywa ponownie numerow usunietych wierszy -> nowy film dziedziczyl historie bledow starego (teraz zadania odlaczane przy usuwaniu).
5. Chwilowe bledy (429/siec) moglyby wstrzymywac produkcje w nieskonczonosc -> limit 3 ponowien bez proby, potem licza sie.
6. Interfejs: sceny wyswietlaly sie jako "[object HTMLDivElement]" (tablica do natywnego append) i przegladarka trzymala stare pliki (teraz no-cache).

## Ograniczenia do dalszych prac
- Ujecie z dolu, first/last frame w H3, change_angle, dryf twarzy przy wielu klipach, sklejanie, dzwiek - nie przetestowane.
- Brak testu na stylu realistycznym i anime; brak testu LoRA postaci.

## Poza z referencji (17.10.2026)
Eksperymenty `tests/pose_ref_experiment*.py` (arkusze `data/outputs/sheet_poseref*.png`): Krea Identity Edit nie przenosi pozy w żadnej
roli obrazu; Qwen Image Edit przenosi pozę ze zdjęcia (z przeciekiem ubrania/sylwetki), ze szkieletu OpenPose niepewnie; dwustopniowa
hybryda nie zadziałała. Naprawiono też kolejność indeksów referencji edycji w adapterze Sogni: `[-1,-2,...]` (-1 = pierwszy wgrany obraz;
wcześniej odwrócona, co mogło mylić role "pierwszy/drugi obraz" w promptach).
