"""Wspólna baza encji wyłączeń: jeden adres to jedno urządzenie."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_NAME, CONF_HOUSE_NO, CONF_STREET_NAME, DOMAIN
from .outage_coordinator import TauronOutageCoordinator


class TauronOutageEntity(CoordinatorEntity[TauronOutageCoordinator]):
    """Baza wszystkich encji jednego adresu wyłączeń."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TauronOutageCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}-{key}"
        data = entry.data
        address = f"{data[CONF_CITY_NAME]}, {data[CONF_STREET_NAME]} {data[CONF_HOUSE_NO]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Wyłączenia {address}",
            manufacturer="Tauron AMIplus+",
            model="Wyłączenia prądu",
            configuration_url="https://www.tauron-dystrybucja.pl/wylaczenia/wylaczenia-planowane",
        )
