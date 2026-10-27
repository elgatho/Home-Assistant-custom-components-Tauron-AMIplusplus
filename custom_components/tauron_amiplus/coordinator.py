"""Update coordinator for TAURON sensors."""
import datetime
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .connector import TauronAmiplusConnector, TauronAmiplusRawData
from .const import DOMAIN
from .schedule import next_update
from .statistics import TauronAmiplusStatisticsUpdater

_LOGGER = logging.getLogger(__name__)


class TauronAmiplusUpdateCoordinator(DataUpdateCoordinator[TauronAmiplusRawData]):

    def __init__(
            self,
            hass: HomeAssistant,
            config_entry_id: str,
            username: str,
            password: str,
            meter_id: str,
            meter_name: str,
            show_generation: bool = False,
            show_12_months: bool = False,
            show_balanced: bool = False,
            show_balanced_year: bool = False,
            show_configurable: bool = False,
            show_configurable_date: datetime.date | None = None,
            store_statistics: bool = False,
            settlement_factor: float = 0.8,
            energy_storage_reset_date: datetime.date | None = None,
    ):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None,
                         update_method=self.update_method)
        self.connector = TauronAmiplusConnector(username, password, meter_id, hass, config_entry_id, show_generation, show_12_months,
                                                show_balanced, show_balanced_year, show_configurable,
                                                show_configurable_date)
        self.meter_id = meter_id
        self.meter_name = meter_name
        self.show_generation = show_generation
        self.show_12_months = show_12_months
        self.show_balanced = show_balanced
        self.show_configurable = show_configurable
        self.show_configurable_date = show_configurable_date
        self.store_statistics = store_statistics
        self.settlement_factor = max(0.0, min(1.0, float(settlement_factor)))
        self.energy_storage_reset_date = energy_storage_reset_date
        self._last_tariff = None
        self._statistics_task = None
        self._history_ready = False
        self._zones_name = {}
        self._statistics = TauronAmiplusStatisticsUpdater(hass, self.connector, meter_id, meter_name,
                                                          show_generation, show_balanced)
        self._config_entry_id = config_entry_id

    async def update_method(self) -> TauronAmiplusRawData:
        """Only tariff and meter readings come from the API on every refresh; everything else is read from the Recorder."""
        self.log("Starting data update")
        try:
            return await self._update()
        finally:
            await self._schedule_next_update()

    async def _update(self) -> TauronAmiplusRawData:
        data = await self.connector.get_light_data()
        self._sync_device_tariff(data)
        if not self._zones_name:
            self._zones_name = await self.connector.get_zones_name()
        if not self._history_ready:
            # The first synchronisation can take long (12 months of history): run it in the background
            self._schedule_first_sync()
            return data
        await self.generate_statistics()
        await self._fill_from_recorder(data)
        return data

    async def _schedule_next_update(self) -> None:
        """Poll at 06:30 and 14:30; 22:30 only when yesterday is still incomplete in the Recorder."""
        try:
            complete = await self._statistics.is_yesterday_complete()
        except Exception:
            _LOGGER.exception("[%s]: Failed to check completeness of yesterday", self.meter_id)
            complete = False
        now = datetime.datetime.now(datetime.timezone.utc)
        target = next_update(now, complete)
        self.update_interval = target - now
        _LOGGER.info("[%s]: Next scheduled update at %s (yesterday %s)", self.meter_id,
                     target.strftime("%Y-%m-%d %H:%M"), "complete" if complete else "incomplete")

    def _sync_device_tariff(self, data) -> None:
        """Keep the device's displayed tariff in line with the tariff detected in the latest data."""
        tariff = getattr(data, "tariff", None)
        if not tariff or tariff == "unknown" or tariff == self._last_tariff:
            return
        if self._last_tariff is not None:
            _LOGGER.info("[%s]: Tariff changed from %s to %s", self.meter_id, self._last_tariff, tariff)
            self._zones_name = {}
        self._last_tariff = tariff
        registry = dr.async_get(self.hass)
        device = next((d for d in dr.async_entries_for_config_entry(registry, self._config_entry_id) if (DOMAIN, self.meter_id) in d.identifiers), None)
        if device is not None:
            registry.async_update_device(device.id, sw_version=f"Tariff {tariff}")

    def _schedule_first_sync(self) -> None:
        if self._statistics_task is not None and not self._statistics_task.done():
            self.log("Initial statistics synchronisation still running")
            return
        self._statistics_task = self.hass.async_create_task(self._first_sync())

    async def _first_sync(self) -> None:
        try:
            await self.generate_statistics()
        finally:
            self._history_ready = True
        await self.async_request_refresh()

    async def generate_statistics(self) -> None:
        """Download only hours missing in the Recorder (everything the API returns is stored there)."""
        try:
            zones = await self._statistics.update_all()
            if zones:
                self._zones_name = zones
        except Exception:
            _LOGGER.exception("[%s]: Failed to update statistics", self.meter_id)
        try:
            await self._statistics.update_recorder_series()
        except Exception:
            _LOGGER.exception("[%s]: Failed to update hourly recorder series", self.meter_id)
        self.log("Updated missing statistics")

    async def _fill_from_recorder(self, data: TauronAmiplusRawData) -> None:
        await get_instance(self.hass).async_block_till_done()
        for generation, dataset in ((False, data.consumption), (True, data.generation)):
            if generation and not (self.show_generation or self.show_balanced):
                continue
            try:
                values = await self._statistics.read_period_values(generation, self._zones_name, data.tariff)
            except Exception:
                _LOGGER.exception("[%s]: Failed to read values from the Recorder", self.meter_id)
                continue
            if values is not None:
                dataset.json_daily, dataset.daily_date, dataset.json_monthly, dataset.json_yearly = values
        if self.show_balanced:
            try:
                data.balanced = await self._statistics.read_balanced_values()
            except Exception:
                _LOGGER.exception("[%s]: Failed to calculate the balance from the Recorder", self.meter_id)

    def log(self, msg):
        _LOGGER.debug(f"[{self.meter_id}]: {msg}")
