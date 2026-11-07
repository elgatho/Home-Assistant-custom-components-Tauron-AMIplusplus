"""Klient publicznego API Tauron dla wyłączeń prądu (bez logowania)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    OUTAGE_API_BASE_URL,
    OUTAGE_ENDPOINT_CITIES,
    OUTAGE_ENDPOINT_OUTAGES,
    OUTAGE_ENDPOINT_STREETS,
)

_LOGGER = logging.getLogger(__name__)


class TauronOutageApiError(Exception):
    """Błąd połączenia z API wyłączeń albo nieprawidłowa odpowiedź."""


class TauronOutageApi:
    """Obsługuje trzy endpointy potrzebne do wyszukania adresu i wyłączeń."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{OUTAGE_API_BASE_URL}{endpoint}"
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise TauronOutageApiError(f"Error calling {endpoint}: {err}") from err

    async def async_get_cities(self, part_name: str) -> list[dict[str, Any]]:
        """Szuka miejscowości po fragmencie nazwy."""
        data = await self._get(OUTAGE_ENDPOINT_CITIES, {"partName": part_name})
        return data if isinstance(data, list) else []

    async def async_get_streets(self, city_gaid: int, part_name: str) -> list[dict[str, Any]]:
        """Szuka ulic w miejscowości. API oczekuje GAID miejscowości w ownerGAID."""
        data = await self._get(
            OUTAGE_ENDPOINT_STREETS, {"partName": part_name, "ownerGAID": city_gaid}
        )
        return data if isinstance(data, list) else []

    async def async_get_outages(
        self,
        city_gaid: int,
        street_gaid: int,
        house_no: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        """Pobiera planowane i awaryjne wyłączenia dla adresu."""
        data = await self._get(
            OUTAGE_ENDPOINT_OUTAGES,
            {
                "cityGAID": city_gaid,
                "streetGAID": street_gaid,
                "houseNo": house_no,
                "fromDate": from_date,
                "toDate": to_date,
                "getLightingSupport": "true",
                "getServicedSwitchingoff": "true",
            },
        )
        return data if isinstance(data, dict) else {}
