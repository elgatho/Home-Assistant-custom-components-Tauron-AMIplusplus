from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)
try:
    WARSAW = ZoneInfo("Europe/Warsaw")
except Exception:
    from datetime import tzinfo

    class _WarsawTimezone(tzinfo):
        def utcoffset(self, value: datetime | None) -> timedelta:
            return timedelta(hours=2 if self.dst(value) else 1)

        def dst(self, value: datetime | None) -> timedelta:
            if value is None:
                return timedelta(0)
            year = value.year
            march = date(year, 3, 31)
            start = march - timedelta(days=(march.weekday() + 1) % 7)
            october = date(year, 10, 31)
            end = october - timedelta(days=(october.weekday() + 1) % 7)
            current = value.replace(tzinfo=None)
            start_time = datetime.combine(start, time(2))
            end_time = datetime.combine(end, time(3))
            return timedelta(hours=1) if start_time <= current < end_time else timedelta(0)

        def tzname(self, value: datetime | None) -> str:
            return "CEST" if self.dst(value) else "CET"

    WARSAW = _WarsawTimezone()
MEASUREMENT_TYPES = ("consum", "oze", "netto", "netto_oze")


@dataclass(frozen=True)
class TauronHourlyReading:
    measurement_type: str
    timestamp: datetime
    value: Decimal
    hour: int
    status: int | None
    metadata: dict[str, Any]


@dataclass
class TauronParseDiagnostics:
    expected_readings: int = 24
    invalid_readings: int = 0
    missing_hours: int = 0
    duplicate_hours: int = 0
    status_counts: dict[str, int] | None = None
    values_mismatches: int = 0
    sum_mismatch: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.status_counts is None:
            self.status_counts = {}


@dataclass
class TauronParsedSeries:
    measurement_type: str
    readings: list[TauronHourlyReading]
    diagnostics: TauronParseDiagnostics
    api_sum: Decimal | None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _local_timestamp(day: date, hour: int, occurrence: int) -> datetime:
    if not 1 <= hour <= 24:
        raise ValueError(f"Invalid Tauron hour: {hour}")
    naive = datetime.combine(day, time()) + timedelta(hours=hour - 1)
    fold = 1 if hour == 3 and occurrence else 0
    return naive.replace(tzinfo=WARSAW, fold=fold)


def hour_start(raw_hour: dict[str, Any]) -> datetime | None:
    """UTC start of the hour of a raw reading: day from "Date", offset from "Hour" (1-24) in real hours.

    The API repeats the day's timestamp (e.g. 2026-10-21T02:00:00.000+02:00) in every hour of the day, so the time
    part of "Date" must be ignored. Counting real hours keeps DST days (23/25 hours) correct.
    """
    value = raw_hour.get("Date")
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value[:10])
        hour = int(raw_hour.get("Hour", "")) - 1
    except (TypeError, ValueError):
        return None
    if not 0 <= hour <= 24:
        return None
    midnight = datetime.combine(day, time(), tzinfo=WARSAW).astimezone(timezone.utc)
    return midnight + timedelta(hours=hour)


def expected_hours_for_day(day: date | datetime) -> int:
    """Real number of hours in a Warsaw day: 23 (spring DST), 24 or 25 (autumn DST)."""
    if isinstance(day, datetime):
        day = day.date()
    start = datetime.combine(day, time(), tzinfo=WARSAW).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(), tzinfo=WARSAW).astimezone(timezone.utc)
    return int((end - start).total_seconds() // 3600)


def normalize_daily_data(data: dict[str, Any], day: date | datetime) -> None:
    """Make "Hour" a continuous 1..N sequence on DST days.

    Tauron either repeats "Hour": 3 on the 25-hour day or returns 24 items (the merged 02:00-03:00 hours at
    index 2) on 23/25-hour days. Colliding hours overwrite each other in the Recorder and make the cumulative
    sum (and the energy storage) go negative.
    """
    all_data = data["data"].get("allData")
    if not all_data:
        return
    expected = expected_hours_for_day(day)
    if expected == 25 and len(all_data) == 24:
        merged = all_data[2]
        try:
            half = f"{float(merged['EC']) / 2:.6f}"
        except (KeyError, TypeError, ValueError):
            half = merged.get("EC")
        all_data = list(all_data[:2]) + [{**merged, "EC": half}, {**merged, "EC": half}] + list(all_data[3:])
    elif expected == 23 and len(all_data) == 24:
        all_data = list(all_data[:2]) + list(all_data[3:])
    if len(all_data) == expected:
        for index, item in enumerate(all_data, start=1):
            item["Hour"] = index
        data["data"]["allData"] = all_data


def find_damaged_day(rows: Iterable[tuple[datetime, float | None]], first_day: date, last_day: date) -> date | None:
    """First day in [first_day, last_day] whose stored hourly statistics are damaged.

    `rows` are (UTC hour start, cumulative sum). A day is damaged when it has fewer hours than the day really has
    (23/24/25) or when the cumulative sum drops (e.g. after two hours collided on a DST change).
    """
    counts: Counter[date] = Counter()
    decreasing: set[date] = set()
    previous = None
    for start, total in sorted(rows, key=lambda row: row[0]):
        day = start.astimezone(WARSAW).date()
        if not first_day <= day <= last_day:
            continue
        counts[day] += 1
        if total is not None:
            if previous is not None and total < previous - 1e-4:
                decreasing.add(day)
            previous = total
    day = first_day
    while day <= last_day:
        if day in decreasing or 0 < counts.get(day, 0) < expected_hours_for_day(day):
            return day
        day += timedelta(days=1)
    return None


def _response_data(endpoint: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(endpoint.get("data"), dict):
        return endpoint["data"]
    raw = endpoint.get("raw_response")
    if isinstance(raw, dict):
        response = raw
    elif isinstance(raw, str):
        try:
            response = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        return None
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else None


def parse_daily_endpoint(
    measurement_type: str,
    day: date,
    endpoint: dict[str, Any],
    *,
    logger: logging.Logger = _LOGGER,
) -> TauronParsedSeries | None:
    if measurement_type not in MEASUREMENT_TYPES:
        raise ValueError(f"Unsupported Tauron measurement type: {measurement_type}")
    data = _response_data(endpoint)
    if data is None or not isinstance(data.get("allData"), list):
        logger.warning("Invalid Tauron response for %s on %s", measurement_type, day)
        return None

    all_data = data["allData"]
    values = data.get("values")
    diagnostics = TauronParseDiagnostics()
    hour_occurrences: Counter[int] = Counter()
    readings: list[TauronHourlyReading] = []

    if not isinstance(values, list):
        values = []
    for index, item in enumerate(all_data):
        if not isinstance(item, dict):
            diagnostics.invalid_readings += 1
            continue
        raw_hour = item.get("Hour")
        try:
            hour = int(raw_hour)
        except (TypeError, ValueError):
            diagnostics.invalid_readings += 1
            continue
        try:
            timestamp = _local_timestamp(day, hour, hour_occurrences[hour])
        except ValueError:
            diagnostics.invalid_readings += 1
            continue
        hour_occurrences[hour] += 1
        value = _decimal(item.get("EC"))
        if value is None and index < len(values):
            value = _decimal(values[index])
        if value is None:
            diagnostics.invalid_readings += 1
            logger.warning("Invalid Tauron reading %s %s hour %s", measurement_type, day, raw_hour)
            continue
        status = item.get("Status")
        try:
            status_value = int(status) if status not in (None, "") else None
        except (TypeError, ValueError):
            status_value = None
        status_key = str(status_value) if status_value is not None else "missing"
        diagnostics.status_counts[status_key] = diagnostics.status_counts.get(status_key, 0) + 1
        if status_value == 100:
            logger.warning("Tauron reading has status 100: %s %s hour %s", measurement_type, day, hour)
        if index >= len(values) or _decimal(values[index]) != _decimal(item.get("EC")):
            diagnostics.values_mismatches += 1
        readings.append(TauronHourlyReading(measurement_type, timestamp, value, hour, status_value, dict(item)))

    diagnostics.missing_hours = max(0, len(set(range(1, 25)) - set(hour_occurrences)))
    diagnostics.duplicate_hours = sum(max(0, count - 1) for count in hour_occurrences.values())
    api_sum = _decimal(data.get("sum"))
    if api_sum is not None:
        diagnostics.sum_mismatch = abs(sum((reading.value for reading in readings), Decimal("0")) - api_sum)
        if diagnostics.sum_mismatch > Decimal("0.001"):
            logger.warning("Tauron hourly sum mismatch for %s %s: %s", measurement_type, day, diagnostics.sum_mismatch)
    return TauronParsedSeries(measurement_type, readings, diagnostics, api_sum)


def parse_raw_payload(payload: dict[str, Any], *, logger: logging.Logger = _LOGGER) -> dict[str, list[TauronHourlyReading]]:
    result = {measurement_type: [] for measurement_type in MEASUREMENT_TYPES}
    for day_text, daily in payload.get("data", {}).items():
        try:
            day = date.fromisoformat(day_text)
        except (TypeError, ValueError):
            logger.warning("Invalid Tauron day key: %s", day_text)
            continue
        if not isinstance(daily, dict):
            continue
        for measurement_type in MEASUREMENT_TYPES:
            endpoint = daily.get(measurement_type)
            if not isinstance(endpoint, dict):
                continue
            parsed = parse_daily_endpoint(measurement_type, day, endpoint, logger=logger)
            if parsed:
                result[measurement_type].extend(parsed.readings)
    for readings in result.values():
        readings.sort(key=lambda reading: reading.timestamp)
    return result


def load_raw_payload(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("Tauron RAW payload must be an object")
    return payload
