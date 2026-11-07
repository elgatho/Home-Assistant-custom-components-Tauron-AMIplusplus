"""Kalendarz wyłączeń: pozwala budować automatyzacje oparte na czasie."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_CITY_NAME, CONF_HOUSE_NO, CONF_STREET_NAME
from .outage_coordinator import TauronOutageCoordinator
from .outage_entity import TauronOutageEntity
from .typing_helpers import TauronOutageConfigEntry

SUMMARY = "Wyłączenie prądu"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TauronOutageConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Dodaje kalendarz dla wpisu wyłączeń."""
    async_add_entities([TauronOutageCalendar(entry.runtime_data)])


def _to_event(outage: dict[str, Any], location: str) -> CalendarEvent | None:
    """Zamienia wyłączenie na wydarzenie kalendarza; pomija niekompletne."""
    if not outage["start"] or not outage["end"]:
        return None
    return CalendarEvent(
        start=dt_util.as_local(outage["start"]),
        end=dt_util.as_local(outage["end"]),
        summary=SUMMARY,
        description=outage["message"] or "",
        location=location,
        uid=outage["key"],
    )


class TauronOutageCalendar(TauronOutageEntity, CalendarEntity):
    """Wyłączenia jako wydarzenia kalendarza."""

    _attr_translation_key = "outages"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "calendar")
        data = coordinator.entry.data
        self._location = f"{data[CONF_CITY_NAME]}, {data[CONF_STREET_NAME]} {data[CONF_HOUSE_NO]}"

    @property
    def event(self) -> CalendarEvent | None:
        """Zwraca trwające wyłączenie albo najbliższe."""
        data = self.coordinator.data
        outage = data["current"] or data["next"]
        return _to_event(outage, self._location) if outage else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Zwraca wydarzenia z żądanego okna, o które prosi interfejs."""
        outages = await self.coordinator.async_fetch_range(start_date, end_date)
        events = [_to_event(outage, self._location) for outage in outages]
        return [event for event in events if event is not None]
