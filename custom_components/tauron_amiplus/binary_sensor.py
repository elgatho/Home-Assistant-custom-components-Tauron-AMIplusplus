"""Binary sensor wyłączeń: włączony, gdy wyłączenie trwa."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .outage_coordinator import TauronOutageCoordinator
from .outage_entity import TauronOutageEntity
from .typing_helpers import TauronOutageConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TauronOutageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dodaje binary sensor dla wpisu wyłączeń."""
    async_add_entities([TauronOutageActiveSensor(entry.runtime_data)])


class TauronOutageActiveSensor(TauronOutageEntity, BinarySensorEntity):
    """Prawda, gdy wyłączenie obejmujące ten adres trwa."""

    _attr_translation_key = "outage_active"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:flash-off"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "outage_active")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["current"] is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self.coordinator.data["current"]
        if not current:
            return {}
        return {"description": current["message"], "start": current["start"], "end": current["end"]}
