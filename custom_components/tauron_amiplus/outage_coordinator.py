"""Koordynator wyłączeń dla jednego adresu."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CITY_GAID,
    CONF_HOUSE_NO,
    CONF_NOTIFY_DEVICE,
    CONF_SCAN_INTERVAL,
    CONF_STREET_GAID,
    CONF_STREET_NAME,
    DOMAIN,
    OUTAGE_DEFAULT_SCAN_INTERVAL,
    OUTAGE_LOOKAHEAD,
)
from .outage_api import TauronOutageApi, TauronOutageApiError

_LOGGER = logging.getLogger(__name__)


def _parse_date(value: str | None) -> Any:
    """Zamienia znacznik czasu z API na świadomy datetime."""
    if not value:
        return None
    return dt_util.parse_datetime(value)


def parse_outages(raw: dict[str, Any], street_name: str | None = None) -> list[dict[str, Any]]:
    """Normalizuje odpowiedź API do posortowanej listy wyłączeń.

    Zostają tylko wyłączenia, których pole 'Message' zawiera nazwę ulicy (bez wielkości liter).
    """
    outages = []
    for item in raw.get("OutageItems") or []:
        message = item.get("Message", "")
        if street_name:
            if not isinstance(message, str) or street_name.strip().lower() not in message.strip().lower():
                continue
        start = _parse_date(item.get("StartDate"))
        end = _parse_date(item.get("EndDate"))
        outage_id = item.get("OutageId")
        outages.append(
            {
                "id": outage_id,
                "key": f"{outage_id}-{start.isoformat() if start else 'unknown'}",
                "message": message,
                "start": start,
                "end": end,
                "type_id": item.get("TypeId"),
                "is_active": bool(item.get("IsActive")),
            }
        )
    outages.sort(key=lambda o: o["start"] or dt_util.utc_from_timestamp(0))
    return outages


class TauronOutageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Pobiera listę wyłączeń dla jednego adresu i wysyła powiadomienia o nowych."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, OUTAGE_DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.entry = entry
        self._api = TauronOutageApi(async_get_clientsession(hass))
        self._seen_keys: set[str] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now()
        try:
            raw = await self._api.async_get_outages(
                city_gaid=self.entry.data[CONF_CITY_GAID],
                street_gaid=self.entry.data[CONF_STREET_GAID],
                house_no=self.entry.data[CONF_HOUSE_NO],
                from_date=now.strftime("%Y-%m-%dT%H:%M:%S"),
                to_date=(now + OUTAGE_LOOKAHEAD).strftime("%Y-%m-%dT%H:%M:%S"),
            )
        except TauronOutageApiError as err:
            raise UpdateFailed(str(err)) from err

        outages = parse_outages(raw, self.entry.data[CONF_STREET_NAME])

        current = next(
            (o for o in outages if o["start"] and o["end"] and o["start"] <= now <= o["end"]),
            None,
        )
        upcoming = next((o for o in outages if o["start"] and o["start"] > now), None)

        # Przy pierwszym odświeżeniu nie ma czego porównywać, więc nic nie jest "nowe".
        if self._seen_keys is None:
            new_outages: list[dict[str, Any]] = []
        else:
            new_outages = [o for o in outages if o["key"] not in self._seen_keys]
        self._seen_keys = {o["key"] for o in outages}

        if new_outages:
            await self._async_notify(new_outages)

        return {
            "outages": outages,
            "current": current,
            "next": upcoming,
            "new": new_outages,
        }

    async def _async_notify(self, new_outages: list[dict[str, Any]]) -> None:
        """Wysyła powiadomienie na wybrane urządzenie, jeśli zostało wybrane."""
        notify_entity = self.entry.options.get(CONF_NOTIFY_DEVICE)
        if not notify_entity:
            return
        for outage in new_outages:
            start = dt_util.as_local(outage["start"]).strftime("%d.%m %H:%M") if outage["start"] else "?"
            end = dt_util.as_local(outage["end"]).strftime("%d.%m %H:%M") if outage["end"] else "?"
            try:
                await self.hass.services.async_call(
                    "notify",
                    "send_message",
                    {
                        "title": "Nowe wyłączenie prądu",
                        "message": f"{start} – {end}: {outage['message']}",
                    },
                    target={"entity_id": notify_entity},
                )
            except HomeAssistantError as err:
                _LOGGER.warning("Nie udało się wysłać powiadomienia o wyłączeniu: %s", err)

    async def async_fetch_range(self, start: Any, end: Any) -> list[dict[str, Any]]:
        """Pobiera wyłączenia z dowolnego okna czasowego (dla kalendarza)."""
        try:
            raw = await self._api.async_get_outages(
                city_gaid=self.entry.data[CONF_CITY_GAID],
                street_gaid=self.entry.data[CONF_STREET_GAID],
                house_no=self.entry.data[CONF_HOUSE_NO],
                from_date=start.strftime("%Y-%m-%dT%H:%M:%S"),
                to_date=end.strftime("%Y-%m-%dT%H:%M:%S"),
            )
        except TauronOutageApiError as err:
            raise UpdateFailed(str(err)) from err
        return parse_outages(raw, self.entry.data[CONF_STREET_NAME])
