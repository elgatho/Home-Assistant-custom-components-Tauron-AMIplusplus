"""Zdarzenie wyłączeń: wyzwala się przy każdym nowo ogłoszonym wyłączeniu."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .outage_coordinator import TauronOutageCoordinator
from .outage_entity import TauronOutageEntity
from .typing_helpers import TauronOutageConfigEntry

EVENT_NEW_OUTAGE = "new_outage"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TauronOutageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dodaje encję zdarzeń dla wpisu wyłączeń."""
    async_add_entities([TauronNewOutageEvent(entry.runtime_data)])


class TauronNewOutageEvent(TauronOutageEntity, EventEntity):
    """Wyzwala zdarzenie dla każdego wyłączenia, którego wcześniej nie było."""

    _attr_translation_key = "new_outage"
    _attr_event_types = [EVENT_NEW_OUTAGE]
    _attr_icon = "mdi:bell-alert"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "new_outage")

    @callback
    def _handle_coordinator_update(self) -> None:
        for outage in self.coordinator.data["new"]:
            start = outage["start"]
            end = outage["end"]
            self._trigger_event(
                EVENT_NEW_OUTAGE,
                {
                    "outage_id": outage["id"],
                    "description": outage["message"],
                    "start": dt_util.as_local(start).isoformat() if start else None,
                    "end": dt_util.as_local(end).isoformat() if end else None,
                },
            )
        super()._handle_coordinator_update()
