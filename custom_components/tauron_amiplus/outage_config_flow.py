"""Kroki konfiguracji adresu wyłączeń prądu (publiczne API, bez logowania do eLicznika)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_CITY_GAID,
    CONF_CITY_NAME,
    CONF_HOUSE_NO,
    CONF_KIND,
    CONF_NOTIFY_DEVICE,
    CONF_SCAN_INTERVAL,
    CONF_STREET_GAID,
    CONF_STREET_NAME,
    KIND_OUTAGE,
    OUTAGE_DEFAULT_SCAN_INTERVAL,
    OUTAGE_MAX_SCAN_INTERVAL,
    OUTAGE_MIN_SCAN_INTERVAL,
    OUTAGE_MIN_SEARCH_LENGTH,
)
from .outage_api import TauronOutageApi, TauronOutageApiError

_LOGGER = logging.getLogger(__name__)


def _city_label(city: dict[str, Any]) -> str:
    """Rozróżnia miejscowości o tej samej nazwie, dopisując dzielnicę."""
    district = city.get("DistrictName")
    return f"{city['Name']} ({district})" if district else city["Name"]


def _notify_selector() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="notify"))


class TauronOutageConfigFlowMixin:
    """Kroki dodawania adresu wyłączeń; miksowane do TauronAmiplusFlowHandler."""

    async def async_step_outage(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wpisanie fragmentu nazwy miejscowości."""
        self._outage_cities: dict[str, dict[str, Any]] = {}
        self._outage_streets: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        if user_input is not None:
            part = user_input["city_partial"].strip()
            if len(part) < OUTAGE_MIN_SEARCH_LENGTH:
                errors["city_partial"] = "too_few_characters"
            else:
                try:
                    cities = await TauronOutageApi(async_get_clientsession(self.hass)).async_get_cities(part)
                except TauronOutageApiError as err:
                    _LOGGER.error("Error searching outage cities: %s", err)
                    errors["base"] = "outage_cannot_connect"
                else:
                    if cities:
                        self._outage_cities = {_city_label(c): c for c in cities}
                        return await self.async_step_outage_city()
                    errors["city_partial"] = "no_cities_found"

        return self.async_show_form(
            step_id="outage",
            data_schema=vol.Schema({vol.Required("city_partial"): str}),
            errors=errors,
        )

    async def async_step_outage_city(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wybór miejscowości z listy wyników."""
        if user_input is not None:
            self._outage_city = self._outage_cities[user_input["city"]]
            return await self.async_step_outage_street()

        return self.async_show_form(
            step_id="outage_city",
            data_schema=vol.Schema({vol.Required("city"): vol.In(sorted(self._outage_cities))}),
            last_step=False,
        )

    async def async_step_outage_street(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Wpisanie fragmentu nazwy ulicy."""
        errors: dict[str, str] = {}
        if user_input is not None:
            part = user_input["street_partial"].strip()
            if len(part) < OUTAGE_MIN_SEARCH_LENGTH:
                errors["street_partial"] = "too_few_characters"
            else:
                try:
                    streets = await TauronOutageApi(async_get_clientsession(self.hass)).async_get_streets(
                        self._outage_city["GAID"], part
                    )
                except TauronOutageApiError as err:
                    _LOGGER.error("Error searching outage streets: %s", err)
                    errors["base"] = "outage_cannot_connect"
                else:
                    if streets:
                        self._outage_streets = {(s.get("FullName") or s["Name"]): s for s in streets}
                        return await self.async_step_outage_street_selection()
                    errors["street_partial"] = "no_streets_found"

        return self.async_show_form(
            step_id="outage_street",
            data_schema=vol.Schema({vol.Required("street_partial"): str}),
            description_placeholders={"city": self._outage_city["Name"]},
            errors=errors,
            last_step=False,
        )

    async def async_step_outage_street_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wybór ulicy z listy wyników."""
        if user_input is not None:
            self._outage_street = self._outage_streets[user_input["street"]]
            return await self.async_step_outage_house_number()

        return self.async_show_form(
            step_id="outage_street_selection",
            data_schema=vol.Schema({vol.Required("street"): vol.In(sorted(self._outage_streets))}),
            last_step=False,
        )

    async def async_step_outage_house_number(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Numer domu, opcjonalne urządzenie do powiadomień i utworzenie wpisu."""
        errors: dict[str, str] = {}
        if user_input is not None:
            house_no = user_input["house_no"].strip()
            if not house_no:
                errors["house_no"] = "invalid_house_number"
            else:
                await self.async_set_unique_id(
                    f"{self._outage_city['GAID']}-{self._outage_street['GAID']}-{house_no}"
                )
                self._abort_if_unique_id_configured()
                try:
                    await TauronOutageApi(async_get_clientsession(self.hass)).async_get_outages(
                        city_gaid=self._outage_city["GAID"],
                        street_gaid=self._outage_street["GAID"],
                        house_no=house_no,
                        from_date="2000-01-01T00:00:00",
                        to_date="2000-01-02T00:00:00",
                    )
                except TauronOutageApiError as err:
                    _LOGGER.error("Error validating outage address: %s", err)
                    errors["base"] = "outage_cannot_connect"
                else:
                    options: dict[str, Any] = {CONF_SCAN_INTERVAL: OUTAGE_DEFAULT_SCAN_INTERVAL}
                    if user_input.get(CONF_NOTIFY_DEVICE):
                        options[CONF_NOTIFY_DEVICE] = user_input[CONF_NOTIFY_DEVICE]
                    return self.async_create_entry(
                        title=f"Wyłączenia: {self._outage_city['Name']}, {self._outage_street['Name']} {house_no}",
                        data={
                            CONF_KIND: KIND_OUTAGE,
                            CONF_CITY_NAME: self._outage_city["Name"],
                            CONF_CITY_GAID: self._outage_city["GAID"],
                            CONF_STREET_NAME: self._outage_street["Name"],
                            CONF_STREET_GAID: self._outage_street["GAID"],
                            CONF_HOUSE_NO: house_no,
                        },
                        options=options,
                    )

        return self.async_show_form(
            step_id="outage_house_number",
            data_schema=vol.Schema(
                {
                    vol.Required("house_no"): str,
                    vol.Optional(CONF_NOTIFY_DEVICE): _notify_selector(),
                }
            ),
            errors=errors,
        )


class TauronOutageOptionsFlowHandler(OptionsFlow):
    """Interwał odpytywania API i urządzenie do powiadomień dla adresu wyłączeń."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options: dict[str, Any] = {CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            if user_input.get(CONF_NOTIFY_DEVICE):
                options[CONF_NOTIFY_DEVICE] = user_input[CONF_NOTIFY_DEVICE]
            return self.async_create_entry(data=options)

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current.get(CONF_SCAN_INTERVAL, OUTAGE_DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=OUTAGE_MIN_SCAN_INTERVAL,
                            max=OUTAGE_MAX_SCAN_INTERVAL,
                            step=5,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_NOTIFY_DEVICE,
                        description={"suggested_value": current.get(CONF_NOTIFY_DEVICE)},
                    ): _notify_selector(),
                }
            ),
        )
