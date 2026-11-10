"""Support for TAURON sensors."""
import asyncio
import dataclasses
import datetime
import logging
from pathlib import Path

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import CONF_MONITORED_VARIABLES, CONF_NAME, CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .connector import TauronAmiplusRawData
from .const import (CONF_KIND, KIND_OUTAGE, CONF_METER_ID, CONF_METER_NAME, CONF_SHOW_12_MONTHS, CONF_SHOW_ACCOUNT_BALANCE, CONF_SHOW_BALANCED, CONF_SHOW_BALANCED_YEAR,
                     CONF_ENERGY_STORAGE_RESET_DATE,

                    CONF_SHOW_CONFIGURABLE, CONF_SHOW_CONFIGURABLE_DATE, CONF_SHOW_GENERATION, CONF_TARIFF,
                    CONST_BALANCED, CONST_CONFIGURABLE, CONST_DAILY, CONST_GENERATION,
                    CONST_LAST_12_MONTHS, CONST_MONTHLY, CONST_READING, CONST_URL_SERVICE, CONST_YEARLY, DEFAULT_NAME,
                    DOMAIN, SENSOR_TYPES, SENSOR_TYPES_YAML, TYPE_BALANCED_CONFIGURABLE, TYPE_BALANCED_DAILY,
                    TYPE_BALANCED_LAST_12_MONTHS, TYPE_BALANCED_MONTHLY, TYPE_BALANCED_YEARLY,
                    TYPE_AMOUNT, TYPE_AMOUNT_PAYMENT, TYPE_ENERGY_STORAGE)
from .coordinator import TauronAmiplusUpdateCoordinator
from .energy_storage import calculate_monthly_window
from .outage_sensor import create_outage_sensors
from .history_import import async_get_statistics_readings, statistic_id
from .typing_helpers import TauronAmiplusConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_METER_ID): cv.string,
    vol.Required(CONF_MONITORED_VARIABLES, default=[]):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES_YAML)]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    name = config.get(CONF_NAME)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    meter_id = config.get(CONF_METER_ID)

    show_generation_sensors = any(filter(lambda v: CONST_GENERATION in v, config[CONF_MONITORED_VARIABLES]))
    show_12_months = any(filter(lambda v: CONST_LAST_12_MONTHS in v, config[CONF_MONITORED_VARIABLES]))
    show_balanced = any(filter(lambda v: CONST_BALANCED in v, config[CONF_MONITORED_VARIABLES]))
    show_balanced_year = CONF_SHOW_BALANCED_YEAR in config[CONF_MONITORED_VARIABLES]

    coordinator = TauronAmiplusUpdateCoordinator(hass, "YAML", username, password, meter_id, name,
                                                 show_generation=show_generation_sensors,
                                                 show_12_months=show_12_months,
                                                 show_balanced=show_balanced,
                                                 show_balanced_year=show_balanced_year,
                                                 store_statistics=True)
    dev = []
    for variable in config[CONF_MONITORED_VARIABLES]:
        sensor_type_config = SENSOR_TYPES[variable]
        dev.append(TauronAmiplusSensor(coordinator, name, meter_id, variable, sensor_type_config["state_class"]))
    async_add_entities(dev, False)


async def async_setup_entry(hass, entry: TauronAmiplusConfigEntry, async_add_entities):
    """Set up a TAURON sensor based on a config entry."""
    if entry.data.get(CONF_KIND) == KIND_OUTAGE:
        async_add_entities(create_outage_sensors(entry.runtime_data))
        return

    coordinator = entry.runtime_data.coordinator
    meter_id = entry.data[CONF_METER_ID]
    meter_name = entry.data[CONF_METER_NAME]
    tariff = entry.data[CONF_TARIFF]

    show_generation_sensors = entry.options.get(CONF_SHOW_GENERATION, False)
    show_12_months = entry.options.get(CONF_SHOW_12_MONTHS, False)
    show_balanced = entry.options.get(CONF_SHOW_BALANCED, False)
    show_balanced_year = entry.options.get(CONF_SHOW_BALANCED_YEAR, False)
    show_configurable = entry.options.get(CONF_SHOW_CONFIGURABLE, False)
    show_configurable_date = entry.options.get(CONF_SHOW_CONFIGURABLE_DATE, None)
    if show_configurable_date is None:
        show_configurable = False

    sensors = []
    if entry.options.get(CONF_SHOW_ACCOUNT_BALANCE, False):
        sensors.append(TauronAmiplusAccountBalanceSensor(coordinator, meter_id, meter_name))
    sensor_types = {**SENSOR_TYPES}
    if not show_generation_sensors:
        sensor_types = {k: v for k, v in sensor_types.items() if not k.startswith(CONST_GENERATION)}
    if not show_balanced_year:
        sensor_types = {k: v for k, v in sensor_types.items() if not k == TYPE_BALANCED_YEARLY}
    if not show_balanced:
        sensor_types = {
            k: v for k, v in sensor_types.items() if (not k.startswith(CONST_BALANCED)) or k.endswith(CONST_YEARLY)
        }
    sensor_types[TYPE_BALANCED_LAST_12_MONTHS] = SENSOR_TYPES[TYPE_BALANCED_LAST_12_MONTHS]
    sensor_types = {k: v for k, v in sensor_types.items() if not k.endswith(CONST_CONFIGURABLE)}
    last_12_months_types = {k: v for k, v in sensor_types.items() if k.endswith(CONST_LAST_12_MONTHS)}
    sensor_types = {k: v for k, v in sensor_types.items() if not k.endswith(CONST_LAST_12_MONTHS)}
    if TYPE_ENERGY_STORAGE in sensor_types and show_generation_sensors and show_balanced:
        energy_storage_sensor = TauronAmiplusEnergyStorageSensor(coordinator, meter_name or name, meter_id)
        sensors.append(energy_storage_sensor)
        sensor_types = {k: v for k, v in sensor_types.items() if k != TYPE_ENERGY_STORAGE}
    else:
        sensor_types = {k: v for k, v in sensor_types.items() if k != TYPE_ENERGY_STORAGE}

    for sensor_type, sensor_type_config in last_12_months_types.items():
        sensors.append(
            TauronAmiplusRecorderLast12MonthsSensor(
                coordinator,
                sensor_type_config["name"],
                meter_id,
                sensor_type,
                meter_name,
            )
        )

    for sensor_type, sensor_type_config in sensor_types.items():
        sensors.append(
            TauronAmiplusConfigFlowSensor(
                coordinator,
                sensor_type_config["name"],
                meter_id,
                sensor_type,
                sensor_type_config["state_class"],
                tariff,
                meter_name
            )
        )

    async_add_entities(sensors, False)

    added_zone_sensors: set[str] = set()

    @callback
    def _add_zone_sensors() -> None:
        """Add per-zone sensors as soon as the detected tariff has more than one zone (e.g. G12, G12W)."""
        zones = current_tariff_zones(coordinator.data)
        if len(zones) < 2:
            return
        new_sensors = []
        for zone_id in zones:
            if zone_id not in added_zone_sensors:
                added_zone_sensors.add(zone_id)
                new_sensors.append(TauronAmiplusZoneSensor(coordinator, meter_id, meter_name, zone_id))
        if OFF_PEAK_SHARE_KEY not in added_zone_sensors:
            added_zone_sensors.add(OFF_PEAK_SHARE_KEY)
            new_sensors.append(TauronAmiplusOffPeakShareSensor(coordinator, meter_id, meter_name))
        if new_sensors:
            async_add_entities(new_sensors, False)

    _add_zone_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_zone_sensors))


OFF_PEAK_SHARE_KEY = "off_peak_share"


class TauronAmiplusAccountBalanceSensor(SensorEntity, CoordinatorEntity):
    """Account balance (saldo) from Mój TAURON: positive = amount to pay, summed over all supply points."""

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, meter_id: str, meter_name: str):
        super().__init__(coordinator)
        self._meter_id = meter_id
        self._attr_unique_id = f"tauron-{meter_id}-account_balance"
        self._attr_name = f"{DEFAULT_NAME} {meter_name} account balance"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_suggested_display_precision = 2
        self._attr_icon = "mdi:cash"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._meter_id)}}

    @property
    def _balance(self):
        return getattr(self.coordinator.data, "account_balance", None)

    @property
    def available(self):
        return super().available and self._balance is not None

    @property
    def native_value(self):
        return self._balance.total if self._balance else None

    @property
    def extra_state_attributes(self):
        if not self._balance:
            return {}
        return {"supply_points": [dataclasses.asdict(p) for p in self._balance.points]}


def current_tariff_zones(data) -> dict[str, tuple[str, float]]:
    """Return {zone_id: (zone_name, monthly consumption)} for zones of the currently active tariff."""
    json_monthly = getattr(getattr(data, "consumption", None), "json_monthly", None)
    if not json_monthly or not isinstance(json_monthly.get("data"), dict):
        return {}
    monthly = json_monthly["data"]
    names = monthly.get("zonesName") or {}
    values = monthly.get("zones") or {}
    return {
        zone_id: (name, float(values.get(zone_id, 0)))
        for zone_id, name in sorted(names.items())
        if "_" not in str(zone_id)
    }


class TauronAmiplusZoneSensor(SensorEntity, CoordinatorEntity):
    """Monthly consumption in a single tariff zone (only created for multi-zone tariffs)."""

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, meter_id: str, meter_name: str, zone_id: str):
        super().__init__(coordinator)
        self._meter_id = meter_id
        self._meter_name = meter_name
        self._zone_id = zone_id
        self._attr_unique_id = f"tauron-{meter_id}-monthly_zone_{zone_id}_energy_consumption"
        self._attr_name = f"{DEFAULT_NAME} {meter_name} monthly energy consumption zone {zone_id}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:counter"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._meter_id)}}

    @property
    def available(self):
        return super().available and self._zone_id in current_tariff_zones(self.coordinator.data)

    @property
    def native_value(self):
        zone = current_tariff_zones(self.coordinator.data).get(self._zone_id)
        return round(zone[1], 3) if zone else None

    @property
    def extra_state_attributes(self):
        zone = current_tariff_zones(self.coordinator.data).get(self._zone_id)
        return {
            "tariff": getattr(self.coordinator.data, "tariff", None),
            "zone": zone[0] if zone else None,
        }


class TauronAmiplusOffPeakShareSensor(SensorEntity, CoordinatorEntity):
    """Share of monthly consumption in the cheaper (last) zone of a multi-zone tariff."""

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, meter_id: str, meter_name: str):
        super().__init__(coordinator)
        self._meter_id = meter_id
        self._attr_unique_id = f"tauron-{meter_id}-monthly_off_peak_share"
        self._attr_name = f"{DEFAULT_NAME} {meter_name} monthly off-peak consumption share"
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:percent"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._meter_id)}}

    def _share(self):
        zones = current_tariff_zones(self.coordinator.data)
        if len(zones) < 2:
            return None, None, 0
        total = sum(v for _, v in zones.values())
        cheaper = max(zones, key=int)
        return (zones[cheaper][1] / total * 100 if total > 0 else None), zones[cheaper][0], total

    @property
    def available(self):
        return super().available and self._share()[0] is not None

    @property
    def native_value(self):
        share = self._share()[0]
        return round(share, 1) if share is not None else None

    @property
    def extra_state_attributes(self):
        _, name, total = self._share()
        return {
            "tariff": getattr(self.coordinator.data, "tariff", None),
            "cheaper_zone": name,
            "total_in_tariff": round(total, 3),
        }


class TauronAmiplusEnergyStorageSensor(SensorEntity, CoordinatorEntity):
    """Sensor representing the virtual energy storage for net-metering 1:0.8."""

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, name: str, meter_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._client_name = name
        self._meter_id = meter_id
        self._attr_name = "Domowy magazyn energii"
        self._attr_unique_id = f"tauron_{meter_id}_domowy_magazyn_energii"

        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:home-battery-outline"
        self._state = None
        self._available = False
        self._accuracy = "requires_sync"
        self._storage_state = None
        self._last_period = None
        self._statistics_state = None
        self._statistics_loaded = False
        self._raw_path = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._meter_id)},
            "name": f"{DEFAULT_NAME} {self._client_name}",
            "manufacturer": "TAURON",
            "model": self._meter_id,
            "configuration_url": CONST_URL_SERVICE,
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if the sensor is available."""
        return self._available

    @property
    def device_class(self):
        return SensorDeviceClass.ENERGY

    @property
    def state_class(self):
        return SensorStateClass.TOTAL

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "source_generation": f"sensor.tauron_amiplus_{self._meter_id}_monthly_energy_generation",
            "source_consumption": f"sensor.tauron_amiplus_{self._meter_id}_monthly_energy_consumption",
            "initial_balance_entity": None,
            "accuracy": getattr(self, "_accuracy", "requires_sync"),
            "model": "last_12_months_monthly_fifo_approximation",
            "period": (self._storage_state or {}).get("period"),
            "uncovered_consumption": (self._storage_state or {}).get("uncovered_consumption"),
            "window": f"from_{self.coordinator.energy_storage_reset_date.isoformat()}" if self.coordinator.energy_storage_reset_date else "last_12_months",
            "reset_date": self.coordinator.energy_storage_reset_date.isoformat() if self.coordinator.energy_storage_reset_date else None,
            "tariff": self.coordinator.data.tariff if self.coordinator.data is not None else None,
            "raw_source": "Home Assistant Recorder",
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self._async_update_storage()

    def _handle_coordinator_update(self):
        self.hass.async_create_task(self._async_update_storage())

    async def _async_update_storage(self):
        """Update the virtual storage without blocking the event loop."""
        _LOGGER.debug(f"Updating energy storage sensor for meter: {self._meter_id}")
        try:
            initial_state = 0.0

            data = self.coordinator.data
            if not data or not data.generation or not data.consumption:
                self._state = None
                self._available = False
                self.async_write_ha_state()
                return

            end = datetime.datetime.now(datetime.timezone.utc)
            reset_date = self.coordinator.energy_storage_reset_date
            start = (
                datetime.datetime.combine(reset_date, datetime.time.min, tzinfo=datetime.timezone.utc)
                if reset_date is not None
                else end - datetime.timedelta(days=370)
            )
            generation_data = await async_get_statistics_readings(
                self.hass, statistic_id(self._meter_id, "netto_oze"), start, end
            )
            consumption_data = await async_get_statistics_readings(
                self.hass, statistic_id(self._meter_id, "netto"), start, end
            )
            if not generation_data or not consumption_data:
                self._state = None
                self._available = False
                self.async_write_ha_state()
                return
            accuracy = "recorder_hourly_fifo_netto"
            state, storage_value, _ = calculate_monthly_window(
                generation_data,
                consumption_data,
                datetime.date.today(),
                settlement_factor=self.coordinator.settlement_factor,
                window_start=reset_date,
            )
            state["settlement_factor"] = self.coordinator.settlement_factor
            state["official_tauron_balance"] = False
            self._storage_state = state
            self._state = storage_value
            self._available = True
            self._accuracy = accuracy

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error updating energy storage sensor: {str(e)}")
            self._state = None
            self._available = False
            self.async_write_ha_state()


class TauronAmiplusSensor(SensorEntity, CoordinatorEntity):

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, name: str, meter_id: str, sensor_type: str,
                 state_class: SensorStateClass):
        super().__init__(coordinator)
        self._client_name = name
        self._meter_id = meter_id
        self._generation = sensor_type.startswith(CONST_GENERATION)
        self._sensor_type = sensor_type
        self._state_class = state_class
        self._power_zones = None
        self._tariff = None
        self._params = {}
        self._state = None

    @property
    def name(self):
        return f"{self._client_name} {self._sensor_type}"

    @property
    def native_unit_of_measurement(self):
        if self._sensor_type == TYPE_AMOUNT_PAYMENT:
            return "zł"
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def device_class(self):
        if self._sensor_type.startswith(TYPE_AMOUNT):
            return None
        return SensorDeviceClass.ENERGY

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        _params = {
            "tariff": self._tariff,
            **self._params,
        }
        return _params

    @property
    def icon(self):
        return "mdi:counter"

    @property
    def state_class(self):
        return self._state_class

    def _handle_coordinator_update(self) -> None:
        if self._sensor_type == TYPE_BALANCED_LAST_12_MONTHS:
            self.hass.async_create_task(self._async_update_last_12_months_balance())
            return
        self.log(f"Updating data for entry: {self._sensor_type}")
        data: TauronAmiplusRawData = self.coordinator.data
        self.log(f"DATA: {data}")
        if not self.available or data is None:
            return
        dataset = data.generation if self._generation else data.consumption
        self._tariff = data.tariff

        if self._sensor_type == TYPE_AMOUNT_PAYMENT and data.payments:
            self._state = data.payments[0].value
            payments = list(map(lambda p: dataclasses.asdict(p), data.payments))
            self._params = {"date": data.payments[0].date, "payments": payments}
        elif self._sensor_type == TYPE_BALANCED_DAILY and data.balance_daily is not None:
            self.update_balanced_data(data.balance_daily)
        elif self._sensor_type == TYPE_BALANCED_MONTHLY and data.balance_monthly is not None:
            self.update_balanced_data(data.balance_monthly)
        elif self._sensor_type == TYPE_BALANCED_YEARLY and data.balance_yearly is not None:
            self.update_balanced_data(data.balance_yearly)
        elif self._sensor_type == TYPE_BALANCED_LAST_12_MONTHS and data.balance_last_12_months_hourly is not None:
            self.update_balanced_data(data.balance_last_12_months_hourly)
        elif self._sensor_type == TYPE_BALANCED_CONFIGURABLE and data.balance_configurable_hourly is not None:
            self.update_balanced_data(data.balance_configurable_hourly)
        elif self._sensor_type.endswith(CONST_READING) and dataset.json_reading is not None:
            self.update_reading(dataset.json_reading)
        elif self._sensor_type.endswith(CONST_DAILY) and dataset.json_daily is not None:
            self.update_values(dataset.json_daily)
            self._params = {"date": dataset.daily_date, **self._params}
        elif self._sensor_type.endswith(CONST_MONTHLY) and dataset.json_monthly is not None:
            self.update_values(dataset.json_monthly)
        elif self._sensor_type.endswith(CONST_YEARLY) and dataset.json_yearly is not None:
            self.update_values(dataset.json_yearly)
        elif self._sensor_type.endswith(CONST_LAST_12_MONTHS) and dataset.json_last_12_months_hourly is not None:
            self.update_values(dataset.json_last_12_months_hourly)
        elif self._sensor_type.endswith(CONST_CONFIGURABLE) and dataset.json_configurable_hourly is not None:
            self.update_values(dataset.json_configurable_hourly)
        self.async_write_ha_state()

    def update_reading(self, json_data):
        reading = json_data["data"][-1]
        self._state = reading["C"]
        partials = {s: reading[s] for s in ["S1", "S2", "S3"] if s in reading and reading[s] is not None}
        self._params = {"date": reading["Date"], **partials}

    async def _async_update_last_12_months_balance(self) -> None:
        end = datetime.datetime.now(datetime.timezone.utc)
        start = end - datetime.timedelta(days=365)
        consumption_data = await async_get_statistics_readings(
            self.hass, statistic_id(self._meter_id, "netto"), start, end
        )
        generation_data = await async_get_statistics_readings(
            self.hass, statistic_id(self._meter_id, "netto_oze"), start, end
        )
        if not consumption_data and not generation_data:
            self._state = None
            self._params = {
                "data_range": f"{start.date()} - {end.date()}",
                "raw_source": "Home Assistant Recorder",
            }
            self.async_write_ha_state()
            return
        sum_consumption = sum(float(item["EC"]) for item in consumption_data)
        sum_generation = sum(float(item["EC"]) for item in generation_data)
        self._state = round(sum_consumption - sum_generation, 3)
        self._params = {
            "sum_consumption": round(sum_consumption, 3),
            "sum_generation": round(sum_generation, 3),
            "data_range": f"{start.date()} - {end.date()}",
            "raw_source": "Home Assistant Recorder",
        }
        self.async_write_ha_state()

    def update_values(self, json_data):
        total, zones, data_range = TauronAmiplusSensor.get_data_from_json(json_data)
        self._state = total
        self._params = {**zones, "data_range": data_range}
        self._params = {k: v for k, v in self._params.items() if v is not None}

    def update_balanced_data(self, balanced_data):
        if len(balanced_data) == 5:
            # Already netted hour by hour from Recorder statistics
            balance, sum_consumption, sum_generation, zones, data_range = balanced_data
            self._state = round(balance, 3)
            self._params = {
                "sum_consumption": round(sum_consumption, 3),
                "sum_generation": round(sum_generation, 3),
                "data_range": data_range,
            }
            return
        con = balanced_data[0]
        gen = balanced_data[1]
        balance, sum_consumption, sum_generation, zones, data_range = TauronAmiplusSensor.get_balanced_data(con, gen)
        self._state = round(balance, 3)
        self._params = {
            "sum_consumption": round(sum_consumption, 3),
            "sum_generation": round(sum_generation, 3),
            "data_range": data_range,
            **{k: round(v, 3) for (k, v) in zones.items()},
        }

    @staticmethod
    def get_data_from_json(json_data):
        total = round(json_data["data"]["sum"], 3)
        zones = {}
        data_range = None
        if (
            "zones" in json_data["data"]
            and len(json_data["data"]["zones"]) > 0
            and "zonesName" in json_data["data"]
            and len(json_data["data"]["zonesName"]) > 0
        ):
            zones = {v: round(json_data["data"]["zones"].get(k, 0), 3) for (k, v) in json_data["data"]["zonesName"].items()}
        if (
            "allData" in json_data["data"]
            and len(json_data["data"]["allData"]) > 0
            and "Date" in json_data["data"]["allData"][0]
        ):
            consumption_data = json_data["data"]["allData"]
            data_range = f"{consumption_data[0]['Date']} - {consumption_data[-1]['Date']}"
        return total, zones, data_range

    @staticmethod
    def get_balanced_data(consumption_data_json, generation_data_json):
        zone_names = consumption_data_json["data"]["zonesName"]
        consumption_data = consumption_data_json["data"]["allData"]
        generation_data = generation_data_json["data"]["allData"]
        if len(consumption_data) == 0 or len(generation_data) == 0:
            return 0, 0, 0, {}, ""
        data_range = f"{consumption_data[0]['Date']} - {consumption_data[-1]['Date']}"

        sum_consumption = 0
        sum_generation = 0
        zones = {}

        for consumption, generation in zip(consumption_data, generation_data):
            value_consumption = float(consumption["EC"])
            value_generation = float(generation["EC"])
            zone = zone_names[consumption["Zone"]]
            balance = value_consumption - value_generation
            if balance > 0:
                sum_consumption += balance
                zone_key = f"{zone}_consumption"
                if zone_key not in zones:
                    zones[zone_key] = 0
                zones[zone_key] += balance
            else:
                sum_generation += balance
                zone_key = f"{zone}_generation"
                if zone_key not in zones:
                    zones[zone_key] = 0
                zones[zone_key] += balance

        balance = sum_consumption + sum_generation
        return balance, sum_consumption, sum_generation, zones, data_range

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"tauron-yaml-{self._meter_id}-{self._sensor_type.lower()}"

    def log(self, msg):
        _LOGGER.debug(f"[{self._meter_id}]: {msg}")


class TauronAmiplusConfigFlowSensor(TauronAmiplusSensor):

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, name: str, meter_id: str, sensor_type: str,
                 state_class: SensorStateClass, tariff: str, meter_name: str):
        """Initialize the sensor."""
        super().__init__(coordinator, name, meter_id, sensor_type, state_class)
        self._tariff = tariff
        self._meter_name = meter_name

    def _current_tariff(self):
        data = self.coordinator.data
        detected = getattr(data, "tariff", None)
        return detected if detected and detected != "unknown" else self._tariff

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._meter_id)},
            "name": f"{DEFAULT_NAME} {self._meter_name}",
            "manufacturer": "TAURON",
            "model": self._meter_id,
             "sw_version": f"Tariff {self._current_tariff()}",
             "configuration_url": CONST_URL_SERVICE,
        }

    @property
    def name(self):
        return f"{DEFAULT_NAME} {self._meter_name} {self._client_name}"

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"tauron-{self._meter_id}-{self._sensor_type.lower()}"


class TauronAmiplusRecorderLast12MonthsSensor(SensorEntity, CoordinatorEntity):
    """Last 12 months energy sensor computed from recorder statistics."""

    def __init__(self, coordinator: TauronAmiplusUpdateCoordinator, name: str, meter_id: str, sensor_type: str,
                 meter_name: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._client_name = name
        self._meter_id = meter_id
        self._sensor_type = sensor_type
        # consum/oze = raw grid import/export (same series as daily/monthly/yearly sensors);
        # balance = hourly-balanced netto_oze - netto.
        if sensor_type.startswith(CONST_BALANCED):
            self._measurement_types = ("netto", "netto_oze")
        elif sensor_type.startswith(CONST_GENERATION):
            self._measurement_types = ("oze",)
        else:
            self._measurement_types = ("consum",)
        self._state = None
        self._params = {}
        self._available = True
        self._attr_name = f"{DEFAULT_NAME} {meter_name} {name}"
        # Same unique_id as the former config-flow sensor so existing entity_ids keep working.
        self._attr_unique_id = f"tauron-{meter_id}-{sensor_type.lower()}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:calendar-month"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._meter_id)},
            "name": f"{DEFAULT_NAME} {self._meter_id}",
            "manufacturer": "TAURON",
            "model": self._meter_id,
            "configuration_url": CONST_URL_SERVICE,
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def available(self):
        """Return if the sensor is available."""
        return self._available

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "source": [statistic_id(self._meter_id, m) for m in self._measurement_types],
            "data_source": "Home Assistant Recorder",
            "period": "last_12_months",
            **self._params,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self._async_update_from_recorder()

    def _handle_coordinator_update(self) -> None:
        self.hass.async_create_task(self._async_update_from_recorder())

    async def _async_update_from_recorder(self):
        """Compute the rolling 12-month sum from recorder statistics."""
        _LOGGER.debug(f"Updating 12-month recorder sensor for meter: {self._meter_id}")
        try:
            end = datetime.datetime.now(datetime.timezone.utc)
            start = end - datetime.timedelta(days=365)
            sums = []
            for measurement_type in self._measurement_types:
                readings = await async_get_statistics_readings(
                    self.hass, statistic_id(self._meter_id, measurement_type), start, end
                )
                sums.append(sum(float(r.get("EC") or 0.0) for r in readings) if readings else None)
            if any(s is None for s in sums):
                self._state = None
                self._available = False
            else:
                self._params = {"data_range": f"{start.date()} - {end.date()}"}
                if len(sums) == 2:
                    # Balance = generation - consumption: negative when more energy was drawn than produced.
                    self._state = round(sums[1] - sums[0], 3)
                    self._params |= {"sum_consumption": round(sums[0], 3), "sum_generation": round(sums[1], 3)}
                else:
                    self._state = round(sums[0], 3)
                self._available = True
        except (HomeAssistantError, ValueError, TypeError, KeyError) as err:
            _LOGGER.warning(f"Failed to read recorder statistics for meter {self._meter_id}: {err}")
            self._state = None
            self._available = False
        self.async_write_ha_state()
