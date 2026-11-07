"""Spook - Not your homie."""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from homeassistant.exceptions import HomeAssistantError

from .const import CONF_KIND, DOMAIN, KIND_OUTAGE
from .statistics import TauronAmiplusStatisticsUpdater
from .typing_helpers import TauronAmiplusConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)


def _get_meter_config_entry(hass: HomeAssistant, device_id: str) -> TauronAmiplusConfigEntry:
    """Zwraca wpis licznika; usługi nie działają na wpisach adresu wyłączeń."""
    device = dr.async_get(hass).async_get(device_id)
    [config_entry_id, *_] = device.config_entries
    config_entry = hass.config_entries.async_get_entry(config_entry_id)
    if config_entry.data.get(CONF_KIND) == KIND_OUTAGE:
        raise HomeAssistantError("Ta usługa działa tylko dla liczników eLicznik")
    return config_entry


class DownloadStatisticsService:

    domain = DOMAIN
    service = "download_statistics"
    schema = vol.Schema({
        vol.Required("device_id"): cv.string,
        vol.Required("start_date"): cv.date
    })

    def __init__(self, hass: HomeAssistant):
        self._hass = hass

    async def async_handle_service(self, call: ServiceCall) -> None:
        now = datetime.date.today()
        start_date = call.data["start_date"]
        if start_date > now:
            _LOGGER.error(f"Failed to download statistics, date from the future: {start_date}")
            return
        config_entry = _get_meter_config_entry(self._hass, call.data["device_id"])
        await TauronAmiplusStatisticsUpdater.manually_update(self._hass, start_date, config_entry)


class ClearCacheService:

    domain = DOMAIN
    service = "clear_cache"
    schema = vol.Schema({
        vol.Required("device_id"): cv.string,
    })

    def __init__(self, hass: HomeAssistant):
        self._hass = hass

    async def async_handle_service(self, call: ServiceCall) -> None:
        config_entry = _get_meter_config_entry(self._hass, call.data["device_id"])
        config_entry.runtime_data.coordinator.connector.clear_cache()


def register_all_services(hass: HomeAssistant) -> None:
    services = [DownloadStatisticsService(hass), ClearCacheService(hass)]
    for service in services:
        hass.services.async_register(service.domain, service.service, service.async_handle_service, service.schema)
