[![HACS Default][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Installations][installations_shield]][releases]


[hacs_shield]: https://img.shields.io/static/v1.svg?label=HACS&message=Default&style=popout&color=green&labelColor=41bdf5&logo=HomeAssistantCommunityStore&logoColor=white
[hacs]: https://hacs.xyz/docs/default_repositories

[latest_release]: https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases/latest
[releases_shield]: https://img.shields.io/github/release/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus.svg?style=popout

[releases]: https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases
[downloads_total_shield]: https://img.shields.io/github/downloads/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/total

[installations_shield]: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.tauron_amiplus.total&style=popout&color=41bdf5&label=analytics


# Tauron Amiplus+

[English version](README.en.md)

Integracja pobiera dane o zużyciu i produkcji energii z nieoficjalnego API [TAURON eLicznik](https://elicznik.tauron-dystrybucja.pl).

Społecznościowy fork projektu [Piotra Machowskiego](https://github.com/PiotrMachowski) – dziękuję za oryginał i rozpracowanie API eLicznika. Fork zachowuje autorstwo i licencję oryginału, nie jest powiązany z TAURON.

## Instalacja


### Przez [HACS](https://hacs.xyz/) (zalecane)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=elgatho&repository=Home-Assistant-custom-components-Tauron-AMIplusplus&category=integration)

* W sekcji _Integracje_ dodaj repozytorium „Tauron Amiplus+” (ten fork)
* Zainstaluj dodane repozytorium

### Ręcznie

Pobierz [*tauron_amiplus.zip*](https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases/latest/download/tauron_amiplus.zip) i rozpakuj do katalogu `config/custom_components/tauron_amiplus`:
```bash
mkdir -p custom_components/tauron_amiplus
cd custom_components/tauron_amiplus
wget https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases/latest/download/tauron_amiplus.zip
unzip tauron_amiplus.zip
rm tauron_amiplus.zip
```

Następnie zrestartuj Home Assistanta przed zastosowaniem zmian w pliku konfiguracyjnym.

## Konfiguracja

_Ustawienia_ -> _Urządzenia i usługi_ -> _Dodaj integrację_ -> _Tauron Amiplus+_ (lub [My Home Assistant](https://my.home-assistant.io/redirect/config_flow_start/?domain=tauron_amiplus)). Podaj login i hasło do eLicznika, wybierz licznik i opcje:

| Opcja | Opis |
|---|---|
| Generation sensors | Sensory energii wyprodukowanej (prosumenci). |
| Last 12 months sensors | Sumy z ostatnich 12 miesięcy. |
| Balanced sensors / yearly | Sensory bilansu (zużycie minus produkcja). |
| Configurable sensors | Sumy od wybranej daty historycznej (więcej zapytań do API). |
| Settlement factor | Współczynnik rozliczenia magazynu (`0`–`1`, domyślnie `0.8`). |
| Energy storage reset date | Data startu magazynu (saldo od 0 kWh). Puste = ostatnie 12 miesięcy. |

Statystyki godzinowe są zawsze włączone (opcja _Store statistics_ jest pozostawiona dla zgodności). Konfiguracja przez YAML jest przestarzała – użyj interfejsu.

## Jak to działa

- **Harmonogram.** Odświeżenie o **06:30** i **14:30** (po nocnym przeliczeniu danych przez Tauron). Okno **22:30** działa tylko wtedy, gdy wczorajsza doba jest jeszcze niepełna w Recorderze. Kolejny termin jest w logu (`Next scheduled update at ...`). Odświeżenie następuje też po restarcie HA, przeładowaniu integracji i zmianie konfiguracji.
- **Recorder jako magazyn danych.** Wartości dzienne, miesięczne i roczne (także per strefa) są liczone ze statystyk godzinowych `tauron_importer`. Z API pobierane są tylko taryfa, odczyty licznika i brakujące godziny. Dwie dodatkowe serie `tauron_amiplus:<licznik>_netto` i `_netto_oze` zasilają magazyn energii i sensory 12-miesięczne.
- **Pierwsze uruchomienie.** Historia 12 miesięcy pobierana jest w tle (kilka minut, jedno zapytanie na dzień i serię) i wznawiana po przerwie.
- **Zmiana czasu.** Doby 23- i 25-godzinne są normalizowane do ciągłych godzin, żeby nie nadpisywały się w Recorderze.
- **Samonaprawa.** Przy każdym odświeżeniu sprawdzane jest 7 ostatnich pełnych dni: brakujące godziny lub malejąca suma powodują ponowne pobranie i przeliczenie od uszkodzonego dnia. Ręczna naprawa zwykle nie jest potrzebna.
- **Mniej zapytań.** Identyczne zapytania w jednym cyklu trafiają do API raz.
- **Ponowne logowanie.** Przy błędnym haśle HA zgłasza reauth; nowe dane aktualizują istniejący wpis.
- **Taryfa** (G11, G12, G12W) jest wykrywana automatycznie przy każdym odświeżeniu i widoczna w wersji urządzenia (`Tariff G12W`). Przy zmianie taryfy strefy poprzedniej taryfy są liczone osobno.

## Sensory

Energia w `kWh`; nazwa zawiera nazwę licznika. Sensory produkcji, bilansu, 12-miesięczne i konfigurowalne pojawiają się po włączeniu odpowiednich opcji.

| Sensor | Co pokazuje |
|---|---|
| `Current consumption reading` | Bieżący stan licznika (energia pobrana, licznik rosnący). |
| `Current generation reading` | Bieżący stan licznika (energia oddana). |
| `Daily energy consumption` / `generation` | Energia za **ostatni zakończony dzień** (bieżący jest niepełny). |
| `Monthly energy consumption` / `generation` | Suma od początku bieżącego miesiąca. |
| `Yearly energy consumption` / `generation` | Suma od początku bieżącego roku. |
| `Last 12 months energy consumption` / `generation` | Suma z kroczącego okna 12 miesięcy. |
| `Configurable energy consumption` / `generation` | Suma od wybranej daty historycznej. |
| `Daily` / `Monthly` / `Yearly` / `Last 12 months` / `Configurable balance` | Bilans = zużycie − produkcja w danym okresie. Wartość ujemna oznacza nadwyżkę produkcji. |
| `Domowy magazyn energii` | Szacowana energia dostępna w wirtualnym magazynie (net-metering): nadwyżki miesięczne × współczynnik rozliczenia, zużywane od najstarszych (FIFO), w oknie 12 miesięcy lub od daty resetu. Atrybuty: `uncovered_consumption`, `window`, `tariff`. |
| `Monthly energy consumption zone <n>` | Zużycie w miesiącu w strefie `<n>` (tylko taryfy wielostrefowe; nazwa strefy w atrybucie `zone`). |
| `Monthly off-peak consumption share` | Udział (%) zużycia w tańszej strefie w bieżącej taryfie (tylko wielostrefowe). |

### Panel Energia

Używaj godzinowych statystyk `tauron_importer`, nie sensorów. Przy taryfie wielostrefowej dodaj albo `..._consumption`, albo statystyki `..._consumption_zone_1` i `_zone_2` – nie obie naraz (podwójne liczenie).

## Usługi

- `tauron_amiplus.download_statistics` – pobiera statystyki od podanej daty (uzupełnienie luk).
- `tauron_amiplus.clear_cache` – czyści pamięć podręczną pobranych dni.

## FAQ

* **W statystykach brakuje dni.** Tauron nie opublikował jeszcze godzin z tego dnia. Integracja ich nie zmyśla i uzupełni je sama; po pojawieniu się danych w [eLiczniku](https://elicznik.tauron-dystrybucja.pl) możesz też użyć `download_statistics`.
* **Magazyn energii ma dziwną wartość po zmianie czasu.** Samonaprawa poprawi dane przy najbliższym odświeżeniu (06:30, 14:30 lub 22:30). Jeśli nie, uruchom `download_statistics` od dnia zmiany czasu.
