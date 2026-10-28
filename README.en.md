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

[Wersja polska](README.md)

Retrieves energy consumption and generation data from the unofficial [TAURON eLicznik](https://elicznik.tauron-dystrybucja.pl) API.

A community fork of [Piotr Machowski's](https://github.com/PiotrMachowski) project – thanks for the original and for reverse-engineering the eLicznik API. The fork keeps the original authorship and license and is not affiliated with TAURON.

## Installation




### Using [HACS](https://hacs.xyz/) (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=elgatho&repository=Home-Assistant-custom-components-Tauron-AMIplusplus&category=integration)

* In _Integrations_ section add repository "Tauron Amiplus+" (this fork)
* Install added repository
 
### Manual

Download [*tauron_amiplus.zip*](https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases/latest/download/tauron_amiplus.zip) and extract its contents to `config/custom_components/tauron_amiplus` directory:
```bash
mkdir -p custom_components/tauron_amiplus
cd custom_components/tauron_amiplus
wget https://github.com/elgatho/Home-Assistant-custom-components-Tauron-AMIplusplus/releases/latest/download/tauron_amiplus.zip
unzip tauron_amiplus.zip
rm tauron_amiplus.zip
```

Then restart Home Assistant before applying configuration file changes.

## Configuration

_Settings_ -> _Devices & services_ -> _Add integration_ -> _Tauron Amiplus+_ (or [My Home Assistant](https://my.home-assistant.io/redirect/config_flow_start/?domain=tauron_amiplus)). Enter your eLicznik login and password, pick the meter and options:

| Option | Description |
|---|---|
| Generation sensors | Sensors for energy produced (prosumers). |
| Last 12 months sensors | Rolling 12-month totals. |
| Balanced sensors / yearly | Balance sensors (consumption minus generation). |
| Configurable sensors | Totals from a chosen historical date (more API requests). |
| Settlement factor | Energy storage settlement factor (`0`–`1`, default `0.8`). |
| Energy storage reset date | Storage start date (balance starts at 0 kWh). Empty = last 12 months. |

Hourly statistics are always on (the _Store statistics_ option is kept for compatibility). YAML configuration is deprecated – use the UI.

## How it works

- **Schedule.** Refresh at **06:30** and **14:30** (after Tauron's overnight recalculation). A **22:30** retry runs only when yesterday is still incomplete in the Recorder. The next time is logged (`Next scheduled update at ...`). A refresh also happens after an HA restart, integration reload and configuration change.
- **Recorder as the data store.** Daily, monthly and yearly values (also per zone) are computed from hourly `tauron_importer` statistics. The API is asked only for the tariff, meter readings and missing hours. Two extra series, `tauron_amiplus:<meter>_netto` and `_netto_oze`, feed the energy storage and the 12-month sensors.
- **First run.** 12 months of history are downloaded in the background (a few minutes, one request per day and series) and resumed after interruption.
- **DST changes.** 23- and 25-hour days are normalized to continuous hours so they don't overwrite each other in the Recorder.
- **Self-healing.** Every refresh checks the last 7 full days: missing hours or a decreasing sum trigger a re-download and recalculation from the damaged day. Manual repair is normally not needed.
- **Fewer requests.** Identical requests within one cycle hit the API once.
- **Re-authentication.** On a wrong password HA raises reauth; the new credentials update the existing entry.
- **Tariff** (G11, G12, G12W) is detected on every refresh and shown in the device version (`Tariff G12W`). After a tariff change, zones of the previous tariff are counted separately.

## Sensors

Energy is in `kWh`; names include the meter name. Generation, balance, 12-month and configurable sensors appear when the matching options are enabled.

| Sensor | What it shows |
|---|---|
| `Current consumption reading` | Current meter reading (energy imported, increasing counter). |
| `Current generation reading` | Current meter reading (energy exported). |
| `Daily energy consumption` / `generation` | Energy for the **last completed day** (today is incomplete). |
| `Monthly energy consumption` / `generation` | Total since the start of the current month. |
| `Yearly energy consumption` / `generation` | Total since the start of the current year. |
| `Last 12 months energy consumption` / `generation` | Total over a rolling 12-month window. |
| `Configurable energy consumption` / `generation` | Total since the chosen historical date. |
| `Daily` / `Monthly` / `Yearly` / `Last 12 months` / `Configurable balance` | Balance = consumption − generation over the period. A negative value means a generation surplus. |
| `Domowy magazyn energii` | Estimated energy available in the virtual storage (net-metering): monthly surpluses × settlement factor, consumed oldest first (FIFO), within a 12-month window or from the reset date. Attributes: `uncovered_consumption`, `window`, `tariff`. |
| `Monthly energy consumption zone <n>` | Monthly consumption in zone `<n>` (multi-zone tariffs only; zone name in the `zone` attribute). |
| `Monthly off-peak consumption share` | Share (%) of consumption in the cheaper zone of the current tariff (multi-zone only). |

### Energy dashboard

Use the hourly `tauron_importer` statistics, not the sensors. With a multi-zone tariff add either `..._consumption` or `..._consumption_zone_1` and `_zone_2` – not both (double counting).

## Services

- `tauron_amiplus.download_statistics` – downloads statistics from a given date (fills gaps).
- `tauron_amiplus.clear_cache` – clears the cache of downloaded days.

## FAQ

* **Days are missing in statistics.** Tauron hasn't published that day's hours yet. The integration doesn't invent values and fills them in itself; once the data appears on [eLicznik](https://elicznik.tauron-dystrybucja.pl) you can also run `download_statistics`.
* **Energy storage looks wrong after a time change.** Self-healing fixes the data on the next refresh (06:30, 14:30 or 22:30). If not, run `download_statistics` from the day of the change.
