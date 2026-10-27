import datetime
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMetaData, StatisticMeanType
from homeassistant.components.recorder.statistics import (async_add_external_statistics, get_last_statistics,
                                                          statistics_during_period)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import as_utc, get_time_zone, utc_from_timestamp

from .hourly_data import find_damaged_day, hour_start
from .history_import import build_metadata, statistic_id
from .connector import TauronAmiplusConnector, TauronAmiplusRawData
from .const import (CONF_METER_ID, CONF_METER_NAME, CONF_SHOW_BALANCED, CONF_SHOW_GENERATION, CONST_BALANCED,
                    CONST_CONSUMPTION, CONST_GENERATION, DEFAULT_NAME, STATISTICS_DOMAIN)

_LOGGER = logging.getLogger(__name__)
MAX_AUTOMATIC_STATISTICS_DAYS = 31
SELF_HEALING_DAYS = 7
RECORDER_SERIES = ("netto", "netto_oze")
PREVIOUS_TARIFF_ZONE = "prev_tariff"
HISTORY_MONTHS = 12


def history_start_day(today: datetime.date | None = None) -> datetime.date:
    """First day of the month HISTORY_MONTHS months before the current one (history imported on first run)."""
    today = today or datetime.date.today()
    return datetime.date(today.year - HISTORY_MONTHS // 12, today.month, 1)


class TauronAmiplusStatisticsUpdater:

    def __init__(self, hass: HomeAssistant, connector: TauronAmiplusConnector, meter_id: str, meter_name: str,
                 show_generation: bool, show_balanced: bool) -> None:
        self.hass = hass
        self.connector = connector
        self.meter_id = meter_id
        self.meter_name = meter_name
        self.show_generation = show_generation
        self.show_balanced = show_balanced

    @staticmethod
    async def manually_update(hass, start_date: datetime.date, entry) -> None:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]
        meter_id = entry.data[CONF_METER_ID]
        meter_name = entry.data[CONF_METER_NAME]

        show_generation = entry.options.get(CONF_SHOW_GENERATION, False)
        show_balanced = entry.options.get(CONF_SHOW_BALANCED, False)

        connector = TauronAmiplusConnector(username, password, meter_id, hass=hass, config_entry_id=entry.entry_id, show_generation=show_generation,
                                           show_balanced=show_balanced)
        statistics_updater = TauronAmiplusStatisticsUpdater(hass, connector, meter_id, meter_name, show_generation, show_balanced)

        start_date = datetime.datetime.combine(start_date,
                                               datetime.time(tzinfo=datetime.datetime.now().astimezone().tzinfo))
        await statistics_updater.update_all(start_date)

    async def update_all(self, start_date: datetime.datetime = None) -> dict:
        """Download missing hours from the API into the Recorder; returns the zones of the current tariff."""
        now = datetime.datetime.now(datetime.timezone.utc)
        base_ids = await self.prepare_stats_ids({})

        healing = False
        if start_date is None:
            damaged_day = await self.find_damaged_day()
            if damaged_day is not None:
                healing = True
                warsaw = get_time_zone("Europe/Warsaw")
                start_date = datetime.datetime.combine(damaged_day, datetime.time(), tzinfo=warsaw)
                for offset in range((datetime.date.today() - damaged_day).days + 1):
                    self.connector._cache.delete_day(damaged_day + datetime.timedelta(days=offset))

        if (start_date is not None
                or not all(self.are_stats_up_to_date(v["last_stats_end"]) for v in base_ids.values())):
            if start_date is None:
                stored_ends = [v["last_stats_end"] for v in base_ids.values() if v["last_stats_end"] is not None]
                if stored_ends:
                    start_range = max(min(stored_ends), now - datetime.timedelta(days=MAX_AUTOMATIC_STATISTICS_DAYS))
                    start_range = start_range.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    # First run: download the whole history (see history_start_day)
                    start_range = datetime.datetime.combine(
                        history_start_day(), datetime.time(), tzinfo=datetime.datetime.now().astimezone().tzinfo)
            else:
                start_range = start_date
            data_consumption = await self.connector.get_raw_values_daily_for_range(start_range, now, False)
            raw_data = {CONST_CONSUMPTION: data_consumption["data"]["allData"] if data_consumption else []}
            if self.show_generation or self.show_balanced:
                data_generation = await self.connector.get_raw_values_daily_for_range(start_range, now, True)
                if not data_generation:
                    return {}
                raw_data[CONST_GENERATION] = data_generation["data"]["allData"]
        else:
            return {}

        zones = {}
        if data_consumption:
            zones = {k: v for k, v in data_consumption["data"].get("zonesName", {}).items() if "_" not in str(k)}
        all_stat_ids = await self.prepare_stats_ids(zones)

        if not raw_data[CONST_CONSUMPTION]:
            return zones

        if self.show_balanced:
            balanced_consumption, balanced_generation = self.prepare_balanced_raw_data(raw_data)
            raw_data[f"{CONST_BALANCED}_{CONST_CONSUMPTION}"] = balanced_consumption
            raw_data[f"{CONST_BALANCED}_{CONST_GENERATION}"] = balanced_generation

        for s, v in all_stat_ids.items():
            if healing:
                # Rewrite everything from the damaged day, continuing the sum from the hour before it.
                v["sum"], v["last_stats_time"] = await self.get_sum_before(s, start_date)
            elif v["last_stats_end"] is not None:
                stat = await self.get_stats(raw_data[v["data_source"]], s)
                if not stat.get(s):
                    # No stored statistics within the fetched range: continue from the last stored one.
                    stat = await self.get_last_stats(s)
                if not stat.get(s):
                    continue
                v["sum"] = stat[s][0]["sum"]
                start = stat[s][0].get("start", v["last_stats_end"])
                if isinstance(start, float):
                    start = utc_from_timestamp(start)
                if start_date is not None and start > start_date:
                    start = None
                    v["sum"] = 0
                v["last_stats_time"] = start

        for s, v in all_stat_ids.items():
            await self.update_stats(s, v["name"], v["sum"], v["last_stats_time"], v["zone"], raw_data[v["data_source"]])
        return zones

    async def find_damaged_day(self) -> datetime.date | None:
        """Look at the last SELF_HEALING_DAYS full days in the Recorder for missing hours or a falling sum."""
        stat_id = self.get_stats_id(CONST_CONSUMPTION)
        warsaw = get_time_zone("Europe/Warsaw")
        last_day = datetime.datetime.now(warsaw).date() - datetime.timedelta(days=1)
        first_day = last_day - datetime.timedelta(days=SELF_HEALING_DAYS - 1)
        start = datetime.datetime.combine(first_day, datetime.time(), tzinfo=warsaw) - datetime.timedelta(hours=1)
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, start, None, {stat_id}, "hour", None, {"sum"})
        rows = []
        for row in stats.get(stat_id, []):
            row_start = row.get("start")
            if isinstance(row_start, (int, float)):
                row_start = utc_from_timestamp(row_start)
            if row_start is not None:
                rows.append((row_start, row.get("sum")))
        if not rows:
            return None
        day = find_damaged_day(rows, first_day, last_day)
        if day is not None:
            _LOGGER.info("[%s] Detected missing hours or a decreasing sum in the Recorder on %s, "
                         "self-healing from this day", self.meter_id, day)
        return day

    async def get_sum_before(self, statistic_id, start):
        """(sum, start) of the last stored hour before `start`; (0, None) when there is none."""
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period, self.hass, start - datetime.timedelta(days=3), start, {statistic_id},
            "hour", None, {"sum"})
        rows = stats.get(statistic_id, [])
        if not rows:
            return 0, None
        row_start = rows[-1].get("start")
        if isinstance(row_start, (int, float)):
            row_start = utc_from_timestamp(row_start)
        return rows[-1].get("sum") or 0, row_start

    async def prepare_stats_ids(self, zones):
        suffixes = [{
            "id": CONST_CONSUMPTION,
            "name": CONST_CONSUMPTION,
            "data": CONST_CONSUMPTION,
            "zone": None
        }]
        if self.show_generation:
            suffixes.append({
                "id": CONST_GENERATION,
                "name": CONST_GENERATION,
                "data": CONST_GENERATION,
                "zone": None
            })
        if self.show_balanced:
            suffixes.append({
                "id": f"{CONST_BALANCED}_{CONST_CONSUMPTION}",
                "name": f"{CONST_BALANCED} {CONST_CONSUMPTION}",
                "data": f"{CONST_BALANCED}_{CONST_CONSUMPTION}",
                "zone": None
            })
            suffixes.append({
                "id": f"{CONST_BALANCED}_{CONST_GENERATION}",
                "name": f"{CONST_BALANCED} {CONST_GENERATION}",
                "data": f"{CONST_BALANCED}_{CONST_GENERATION}",
                "zone": None
            })
        if len(zones) > 1:
            for s in [*suffixes]:
                suffixes.extend([
                    {
                        "id": f'{s["id"]}_zone_{zone}',
                        "name": f'{s["name"]} {zone_name}',
                        "data": s["data"],
                        "zone": zone
                    }
                    for zone, zone_name in zones.items()
                ])

        all_stat_ids = {
            self.get_stats_id(s["id"]): {
                "name": self.get_stats_name(s["name"]),
                "zone": s["zone"],
                "data_source": s["data"],
                "sum": 0,
                "last_stats_time": None,
                "last_stats_end": None
            }
            for s in suffixes
        }
        for k, v in all_stat_ids.items():
            v["last_stats_end"] = await self.get_last_stats_date(k)
        return all_stat_ids

    def get_stats_id(self, suffix):
        return f"{STATISTICS_DOMAIN}:{self.meter_id}_{suffix}".lower()

    def get_stats_name(self, suffix):
        return f"{DEFAULT_NAME} {self.meter_name} {suffix}"

    @staticmethod
    def are_stats_up_to_date(last_stats_end):
        if last_stats_end is None:
            return False
        now = datetime.datetime.now()
        return (as_utc(now) - last_stats_end) < datetime.timedelta(hours=1)

    @staticmethod
    def prepare_balanced_raw_data(raw_data) -> (dict, dict):
        consumption_data = raw_data[CONST_CONSUMPTION]
        generation_data = raw_data[CONST_GENERATION]
        if len(consumption_data) != len(generation_data):
            return {}, {}
        balanced_consumption = []
        balanced_generation = []

        for consumption, generation in zip(consumption_data, generation_data):
            value_consumption = float(consumption["EC"])
            value_generation = float(generation["EC"])
            balance = value_consumption - value_generation
            if balance > 0:
                output_consumption = {
                    "EC": f'{balance}',
                    "Date": consumption["Date"],
                    "Hour": consumption["Hour"],
                    "Zone": consumption["Zone"],
                }
                output_generation = {
                    "EC": "0",
                    "Date": generation["Date"],
                    "Hour": generation["Hour"],
                    "Zone": generation["Zone"],
                }
            else:
                output_consumption = {
                    "EC": "0",
                    "Date": consumption["Date"],
                    "Hour": consumption["Hour"],
                    "Zone": consumption["Zone"],
                }
                output_generation = {
                    "EC": f'{-balance}',
                    "Date": generation["Date"],
                    "Hour": generation["Hour"],
                    "Zone": generation["Zone"],
                }
            balanced_consumption.append(output_consumption)
            balanced_generation.append(output_generation)

        return balanced_consumption, balanced_generation

    async def update_recorder_series(self) -> None:
        """Keep the raw hourly series (`tauron_amiplus:<meter>_<type>`) up to date in the Recorder.

        They are read by the energy storage and rolling 12-month sensors. On the first run the last
        HISTORY_MONTHS months are downloaded; later runs only add hours after the last stored one.
        """
        today = datetime.date.today()
        for measurement_type in RECORDER_SERIES:
            stat_id = statistic_id(self.meter_id, measurement_type)
            last = await self.get_last_stats(stat_id)
            total = 0.0
            last_start = None
            first_day = history_start_day(today)
            if last.get(stat_id):
                row = last[stat_id][0]
                total = float(row.get("sum") or 0)
                last_start = row.get("start")
                if isinstance(last_start, (int, float)):
                    last_start = utc_from_timestamp(last_start)
                if last_start is not None:
                    first_day = max(first_day, last_start.astimezone(get_time_zone("Europe/Warsaw")).date())
            readings = await self.connector.get_hourly_readings(measurement_type, first_day, today)
            statistic_data = []
            for reading in sorted(readings, key=lambda item: item.timestamp):
                start = as_utc(reading.timestamp)
                if last_start is not None and start <= last_start:
                    continue
                total += float(reading.value)
                statistic_data.append({"start": start, "state": float(reading.value), "sum": total})
            if statistic_data:
                metadata = build_metadata(f"{DEFAULT_NAME} {self.meter_name} {measurement_type}", stat_id)
                async_add_external_statistics(self.hass, metadata, statistic_data)
            self.log(f"Updated {len(statistic_data)} entries for statistic: {stat_id}")

    async def read_period_values(self, generation: bool, zones_name: dict, tariff: str | None):
        """Build daily/monthly/yearly values of the current tariff from hourly statistics stored in the Recorder.

        Returns (daily, daily_date, monthly, yearly) in the shape used by the sensors, or None without data.
        """
        base = CONST_GENERATION if generation else CONST_CONSUMPTION
        zone_ids = [z for z in zones_name if "_" not in str(z)]
        ids = {None: self.get_stats_id(base)}
        if len(zone_ids) > 1:
            ids.update({z: self.get_stats_id(f"{base}_zone_{z}") for z in zone_ids})
        tz = get_time_zone("Europe/Warsaw")
        today = datetime.datetime.now(tz).date()
        year_start = datetime.datetime(today.year, 1, 1, tzinfo=tz)
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass, year_start, None, set(ids.values()), "hour", None, {"state"})

        by_day = {}
        for key, stat_id in ids.items():
            days = by_day.setdefault(key, {})
            for row in result.get(stat_id, []):
                start, state = row.get("start"), row.get("state")
                if start is None or state is None:
                    continue
                if isinstance(start, (int, float)):
                    start = utc_from_timestamp(start)
                day = start.astimezone(tz).date()
                days[day] = days.get(day, 0.0) + float(state)
        if not by_day[None]:
            return None

        last_day = max(by_day[None])
        names = {z: zones_name[z] for z in zone_ids}

        def period(first: datetime.date, last: datetime.date):
            days = sorted(d for d in by_day[None] if first <= d <= last)
            if not days:
                return None
            total = sum(by_day[None][d] for d in days)
            if len(zone_ids) > 1:
                zones = {z: sum(v for d, v in by_day[z].items() if first <= d <= last) for z in zone_ids}
                rest = total - sum(zones.values())
                if rest > 0.001:
                    zones[PREVIOUS_TARIFF_ZONE] = rest
                    names[PREVIOUS_TARIFF_ZONE] = "Previous tariff"
            else:
                zones = {z: total for z in zone_ids}
            return {"data": {
                "sum": total,
                "zones": zones,
                "zonesName": dict(names),
                "tariff": tariff,
                "allData": [{"Date": days[0].isoformat()}, {"Date": days[-1].isoformat()}],
            }}

        return (
            period(last_day, last_day),
            TauronAmiplusConnector.format_date(last_day),
            period(today.replace(day=1), today),
            period(today.replace(month=1, day=1), today),
        )

    async def read_balanced_values(self):
        """Hourly netting of consumption and generation from the Recorder.

        Returns {"daily"|"monthly"|"yearly": (balance, sum_consumption, sum_generation, zones, data_range)}
        (generation is negative in the balance, as in the former API based calculation) or None without data.
        """
        tz = get_time_zone("Europe/Warsaw")
        today = datetime.datetime.now(tz).date()
        ids = {"c": self.get_stats_id(CONST_CONSUMPTION), "g": self.get_stats_id(CONST_GENERATION)}
        result = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass, datetime.datetime(today.year, 1, 1, tzinfo=tz), None, set(ids.values()), "hour", None,
            {"state"})
        hours = {}
        for key, stat_id in ids.items():
            for row in result.get(stat_id, []):
                start, state = row.get("start"), row.get("state")
                if start is None or state is None:
                    continue
                if isinstance(start, (int, float)):
                    start = utc_from_timestamp(start)
                hours.setdefault(start, {"c": 0.0, "g": 0.0})[key] += float(state)
        if not hours:
            return None
        last_day = max(h.astimezone(tz).date() for h in hours)

        def period(first, last):
            cons = gen = 0.0
            days = set()
            for start, v in hours.items():
                day = start.astimezone(tz).date()
                if not first <= day <= last:
                    continue
                days.add(day)
                balance = v["c"] - v["g"]
                if balance > 0:
                    cons += balance
                else:
                    gen += balance
            if not days:
                return None
            return cons + gen, cons, gen, {}, f"{min(days)} - {max(days)}"

        return {
            "daily": period(last_day, last_day),
            "monthly": period(today.replace(day=1), today),
            "yearly": period(today.replace(month=1, day=1), today),
        }

    async def update_stats(self, statistic_id, statistic_name, initial_sum, last_stats_time, zone_id, raw_data):
        current_sum = initial_sum
        metadata: StatisticMetaData = {
            "has_mean": False,
            "has_sum": True,
            "name": statistic_name,
            "source": STATISTICS_DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            "mean_type": StatisticMeanType.NONE,
            "unit_class": "energy",
        }
        statistic_data = []
        for raw_hour in raw_data:
            start = self.get_time(raw_hour)
            if last_stats_time is not None and start <= last_stats_time:
                continue
            usage = float(raw_hour["EC"])
            if zone_id is not None and raw_hour["Zone"] != zone_id:
                usage = 0
            current_sum += usage
            stats = {
                "start": start,
                "state": usage,
                "sum": current_sum
            }
            statistic_data.append(stats)
        async_add_external_statistics(self.hass, metadata, statistic_data)
        self.log(f"Updated {len(statistic_data)} entries for statistic: {statistic_id} ")

    async def get_last_stats_date(self, statistic_id):
        last_stats = await self.get_last_stats(statistic_id)
        if statistic_id in last_stats and len(last_stats[statistic_id]) > 0:
            end = last_stats[statistic_id][0]["end"]
            if isinstance(end, float):
                end = utc_from_timestamp(end)
            return end
        return None

    async def get_last_stats(self, statistic_id):
        return await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass, 1, statistic_id, True, {"state", "sum"})

    async def get_stats(self, raw_data, statistic_id):
        if not raw_data:
            return {statistic_id: [{"sum": 0, "start": None}]}
        start = self.get_time(raw_data[0])
        if start is None:
            return {statistic_id: [{"sum": 0, "start": None}]}
        return await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass, start, None, [statistic_id], "hour", None, {"state", "sum"})

    def log(self, msg):
        _LOGGER.debug(f"[{self.meter_id}]: {msg}")

    @staticmethod
    def get_time(raw_hour):
        return hour_start(raw_hour)
