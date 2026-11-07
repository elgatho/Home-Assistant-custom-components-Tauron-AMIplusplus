"""Sensory wyłączeń dla jednego adresu."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from .outage_coordinator import TauronOutageCoordinator
from .outage_entity import TauronOutageEntity

STATUS_NONE = "none"
STATUS_UPCOMING = "upcoming"
STATUS_ONGOING = "ongoing"
MAX_STATE_LENGTH = 255


def create_outage_sensors(coordinator: TauronOutageCoordinator) -> list[SensorEntity]:
    """Tworzy komplet sensorów dla wpisu wyłączeń (wywoływane z sensor.py)."""
    return [
        TauronStatusSensor(coordinator),
        TauronNextOutageSensor(coordinator),
        TauronNextOutageEndSensor(coordinator),
        TauronNextOutageDurationSensor(coordinator),
        TauronNextOutageDescriptionSensor(coordinator),
        TauronOutageCountSensor(coordinator),
    ]


class TauronRelevantOutageEntity(TauronOutageEntity, SensorEntity):
    """Baza sensorów opisujących trwające albo najbliższe wyłączenie."""

    @property
    def _outage(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        return data["current"] or data["next"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        outage = self._outage
        if not outage:
            return {}
        return {"start": outage["start"], "end": outage["end"], "description": outage["message"]}


class TauronStatusSensor(TauronOutageEntity, SensorEntity):
    """Jeden czytelny stan: brak, zapowiedziane albo trwa."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_NONE, STATUS_UPCOMING, STATUS_ONGOING]
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data["current"]:
            return STATUS_ONGOING
        if data["next"]:
            return STATUS_UPCOMING
        return STATUS_NONE


class TauronNextOutageSensor(TauronRelevantOutageEntity):
    """Początek trwającego albo najbliższego wyłączenia."""

    _attr_translation_key = "next_outage"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "next_outage")

    @property
    def native_value(self) -> datetime | None:
        outage = self._outage
        return outage["start"] if outage else None


class TauronNextOutageEndSensor(TauronRelevantOutageEntity):
    """Koniec trwającego albo najbliższego wyłączenia."""

    _attr_translation_key = "next_outage_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "next_outage_end")

    @property
    def native_value(self) -> datetime | None:
        outage = self._outage
        return outage["end"] if outage else None


class TauronNextOutageDurationSensor(TauronRelevantOutageEntity):
    """Czas trwania trwającego albo najbliższego wyłączenia."""

    _attr_translation_key = "next_outage_duration"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "next_outage_duration")

    @property
    def native_value(self) -> float | None:
        outage = self._outage
        if not outage or not outage["start"] or not outage["end"]:
            return None
        return (outage["end"] - outage["start"]).total_seconds() / 3600


class TauronNextOutageDescriptionSensor(TauronRelevantOutageEntity):
    """Opis trwającego albo najbliższego wyłączenia (przycięty do 255 znaków)."""

    _attr_translation_key = "next_outage_description"
    _attr_icon = "mdi:text-long"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "next_outage_description")

    @property
    def native_value(self) -> str | None:
        outage = self._outage
        if not outage:
            return None
        message = outage["message"] or ""
        if len(message) <= MAX_STATE_LENGTH:
            return message
        return f"{message[: MAX_STATE_LENGTH - 1]}…"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        outage = self._outage
        if outage:
            attributes["full_description"] = outage["message"]
        return attributes


class TauronOutageCountSensor(TauronOutageEntity, SensorEntity):
    """Liczba wyłączeń zapowiedzianych w oknie prognozy."""

    _attr_translation_key = "outage_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: TauronOutageCoordinator) -> None:
        super().__init__(coordinator, "outage_count")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data["outages"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "outages": [
                {"description": o["message"], "start": o["start"], "end": o["end"]}
                for o in self.coordinator.data["outages"]
            ]
        }
