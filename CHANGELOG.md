# Changelog

## Unreleased

### ⚠️ Breaking change
- **Nowy ekran startowy przy dodawaniu integracji.** Zamiast od razu prosić o login, kreator pyta, czy dodajesz
  licznik eLicznik, czy adres wyłączeń. Istniejące wpisy działają bez zmian, ale nowe dodanie licznika ma dodatkowy krok.
- **Wyłączenia w tej integracji zastępują osobną integrację `tauron_outage_notifier`.** Jeśli z niej korzystasz,
  dodaj adres ponownie jako nowy wpis „Powiadomienia o wyłączeniach". Nie ma automatycznej migracji: encje dostaną
  nowe `entity_id`, więc popraw automatyzacje i pulpity, które się do nich odwołują.
- **Stały interwał 8h30 zniknął.** Odświeżanie licznika działa wg harmonogramu (06:30, 14:30, ewentualnie 22:30),
  więc nie odświeża się już co 8h30.
- **Usługi `download_statistics` i `clear_cache`** zgłoszą błąd, jeśli wskażesz wpis adresu wyłączeń zamiast licznika.

### Dodano
- **Powiadomienia o wyłączeniach prądu** dla dowolnego adresu w Polsce, bez logowania do eLicznika. Wpis
  „Powiadomienia o wyłączeniach" ma sensory: status, następne wyłączenie (początek, koniec, czas trwania, opis),
  liczba wyłączeń w ciągu 30 dni. Jest też binary sensor „Trwa wyłączenie", kalendarz wyłączeń i zdarzenie
  `new_outage` dla nowych komunikatów. Opcjonalnie wybierasz urządzenie `notify`, na które przyjdzie powiadomienie.
  Interwał sprawdzania (domyślnie 60 min, 15–1440) ustawiasz w opcjach.

### Naprawione
- **Zmiana czasu (DST).** Doba 25-godzinna (jesień) i 23-godzinna (wiosna) jest teraz normalizowana do ciągłej
  sekwencji godzin `1..N` (`hourly_data.normalize_daily_data`). Wcześniej API Tauron potrafiło zwrócić zdublowaną
  godzinę `3` albo 24 pozycje z połączoną godziną 02:00–03:00, przez co godziny nadpisywały się w Recorderze,
  suma narastająca malała, a magazyn energii spadał poniżej zera.
- **Samonaprawa statystyk.** Przy każdym odświeżeniu integracja skanuje ostatnie 7 pełnych dni w Recorderze
  (`statistics.find_damaged_day`). Dzień z brakującymi godzinami (23/24/25 zależnie od doby) albo ze spadkiem sumy
  jest pobierany ponownie i nadpisywany, z sumą liczoną od godziny poprzedzającej uszkodzony dzień. Ręczne
  `download_statistics` nie jest już potrzebne.
- **Strefy bez danych.** `add_all_data` nie rzuca już `IndexError`, gdy API nie zwróci żadnej strefy
  (np. taryfa G13 lub dzień bez danych).
- **Reauth.** Ponowne uwierzytelnienie aktualizuje dane logowania w istniejącym wpisie
  (`async_update_reload_and_abort`) zamiast uruchamiać od nowa kreator dodawania integracji. Formularz pyta o
  login i hasło, sprawdza je i przeładowuje integrację.

### Zmienione
- **Deduplikacja żądań w cyklu odświeżania.** Identyczne zapytania (ten sam adres i parametry) w jednym cyklu trafiają
  do API tylko raz (`TauronAmiplusConnector._cycle_cache`). Odpowiedzi nieudane nie są zapamiętywane, a wywołujący
  dostają kopię, więc modyfikowanie wyniku nie psuje cache. Mniej żądań oznacza mniejsze ryzyko limitu
  „Przekroczono maksymalną liczbę logowań".

- **Smart polling.** Stały interwał 8h30 zastąpiono oknami 06:30 i 14:30 (czas warszawski, `schedule.next_update`), czyli
  po nocnym przeliczeniu danych przez Tauron i po popołudniowej synchronizacji. Dodatkowe okno 22:30 jest używane
  tylko wtedy, gdy wczorajsza doba jest niepełna w Recorderze (`statistics.is_yesterday_complete`). Kolejny termin
  trafia do logu INFO. Interwał przestał dryfować, a zapytania nocne nie obciążają konta.

### Dokumentacja
- README (PL/EN) skrócone i uporządkowane; usunięto przykład „Jak obliczyć dostępną energię jako prosument"; dodano tabelę sensorów z opisem działania oraz opis harmonogramu, samonaprawy i usług; poprawiono link między wersjami językowymi.

### Testy
- `tests/test_outage.py`: parsowanie wyłączeń (sortowanie, filtr ulicy) i powiadomienia.
- Nowe: `tests/test_hourly_data.py` (normalizacja DST, wykrywanie uszkodzonego dnia),
  `tests/test_self_healing.py` (Recorder w pamięci), `tests/test_connector_cycle.py` (deduplikacja, strefy),
  `tests/test_schedule.py` (harmonogram, także przy zmianie czasu).
- Dodano `pytest.ini` (`asyncio_mode = auto`). Testy wymagają `pytest-homeassistant-custom-component` i Pythona 3.13.

### Bez zmian (sprawdzone)
- `via_device` nie jest używane w kodzie, więc zmiana HA 2026.9+ nie wymaga poprawki.
