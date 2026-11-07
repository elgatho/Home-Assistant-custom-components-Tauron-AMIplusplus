from typing import Any

from homeassistant.core import HomeAssistant

from .const import (CONF_KIND, CONF_NOTIFY_DEVICE, CONF_SCAN_INTERVAL, CONF_SHOW_12_MONTHS, CONF_SHOW_BALANCED,
                    CONF_SHOW_BALANCED_YEAR, CONF_SHOW_CONFIGURABLE, CONF_SHOW_CONFIGURABLE_DATE, CONF_SHOW_GENERATION,
                    CONF_STORE_STATISTICS, CONF_TARIFF, KIND_OUTAGE)
from .typing_helpers import TauronAmiplusConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TauronAmiplusConfigEntry) -> dict[str, Any]:
    return await get_config_entry_diagnostics(hass, entry)


async def get_config_entry_diagnostics(hass: HomeAssistant, entry: TauronAmiplusConfigEntry) -> dict[str, Any]:
    if entry.data.get(CONF_KIND) == KIND_OUTAGE:
        return {
            "kind": KIND_OUTAGE,
            "scan_interval": entry.options.get(CONF_SCAN_INTERVAL),
            "notify_device_configured": bool(entry.options.get(CONF_NOTIFY_DEVICE)),
            "outages_announced": len(entry.runtime_data.data["outages"]),
        }

    tariff = entry.data[CONF_TARIFF]
    show_generation_sensors = entry.options.get(CONF_SHOW_GENERATION, False)
    show_12_months = entry.options.get(CONF_SHOW_12_MONTHS, False)
    show_balanced = entry.options.get(CONF_SHOW_BALANCED, False)
    show_balanced_year = entry.options.get(CONF_SHOW_BALANCED_YEAR, False)
    show_configurable = entry.options.get(CONF_SHOW_CONFIGURABLE, False)
    show_configurable_date = entry.options.get(CONF_SHOW_CONFIGURABLE_DATE, False)
    store_statistics = entry.options.get(CONF_STORE_STATISTICS, False)

    connector = entry.runtime_data.coordinator.connector
    raw_data = await connector.get_raw_data()

    return {
        "tariff": tariff,
        "show_generation_sensors": show_generation_sensors,
        "show_12_months": show_12_months,
        "show_balanced": show_balanced,
        "show_balanced_year": show_balanced_year,
        "show_configurable": show_configurable,
        "show_configurable_date": show_configurable_date,
        "store_statistics": store_statistics,
        "raw_data_tariff": raw_data.tariff,
        "raw_data_consumption": {
            "json_reading": raw_data.consumption.json_reading,
            "json_daily": raw_data.consumption.json_daily,
            "daily_date": raw_data.consumption.daily_date,
            "json_monthly": raw_data.consumption.json_monthly,
            "json_yearly": raw_data.consumption.json_yearly,
            "json_month_hourly": raw_data.consumption.json_month_hourly,
            "json_last_30_days_hourly": raw_data.consumption.json_last_30_days_hourly,
        },
        "hourly_series_counts": {
            measurement_type: len(raw_data.consumption.hourly_series.get(measurement_type, []))
            for measurement_type in raw_data.consumption.hourly_series
        } if raw_data.consumption else {},
        "hourly_diagnostics": {
            day: {
                "invalid_readings": diagnostics.invalid_readings,
                "missing_hours": diagnostics.missing_hours,
                "duplicate_hours": diagnostics.duplicate_hours,
                "values_mismatches": diagnostics.values_mismatches,
                "status_counts": diagnostics.status_counts,
                "sum_mismatch": str(diagnostics.sum_mismatch),
            }
            for day, diagnostics in raw_data.consumption.hourly_diagnostics.items()
        } if raw_data.consumption else {},
        "raw_data_generation": {
            "json_reading": raw_data.generation.json_reading,
            "json_daily": raw_data.generation.json_daily,
            "daily_date": raw_data.generation.daily_date,
            "json_monthly": raw_data.generation.json_monthly,
            "json_yearly": raw_data.generation.json_yearly,
            "json_month_hourly": raw_data.generation.json_month_hourly,
            "json_last_30_days_hourly": raw_data.generation.json_last_30_days_hourly,
        }
    }
