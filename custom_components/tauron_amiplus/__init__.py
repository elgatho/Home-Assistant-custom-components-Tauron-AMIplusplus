"""Support for Tauron sensors."""
import datetime
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import DATE_STR_FORMAT, parse_date

from .const import (
    CONF_KIND, KIND_OUTAGE, OUTAGE_PLATFORMS,
    CONF_METER_ID, CONF_METER_NAME, CONF_SHOW_12_MONTHS, CONF_SHOW_BALANCED, CONF_SHOW_BALANCED_YEAR,
    CONF_SHOW_CONFIGURABLE, CONF_SHOW_CONFIGURABLE_DATE, CONF_SHOW_GENERATION, CONF_STORE_STATISTICS, CONF_SETTLEMENT_FACTOR, CONF_ENERGY_STORAGE_RESET_DATE, CONF_TARIFF,
    DOMAIN, PLATFORMS,
)
from .coordinator import TauronAmiplusUpdateCoordinator
from .outage_coordinator import TauronOutageCoordinator
from .services import register_all_services
from .typing_helpers import TauronAmiplusRuntimeData, TauronAmiplusConfigEntry

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = datetime.timedelta(seconds=600)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_METER_ID): cv.string,
        vol.Required(CONF_TARIFF): cv.string,
    }
)


async def async_setup(hass, config):
    """Set up the TAURON component."""
    hass.data[DOMAIN] = {}

    if not hass.config_entries.async_entries(DOMAIN) and DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: TauronAmiplusConfigEntry) -> bool:
    """Set up TAURON as config entry."""
    if config_entry.data.get(CONF_KIND) == KIND_OUTAGE:
        return await _async_setup_outage_entry(hass, config_entry)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    user = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    meter_id = config_entry.data[CONF_METER_ID]
    meter_name = config_entry.data[CONF_METER_NAME]
    tariff = config_entry.data[CONF_TARIFF]

    show_generation_sensors = config_entry.options.get(CONF_SHOW_GENERATION, False)
    show_12_months = config_entry.options.get(CONF_SHOW_12_MONTHS, False)
    show_balanced = config_entry.options.get(CONF_SHOW_BALANCED, False)
    show_balanced_year = config_entry.options.get(CONF_SHOW_BALANCED_YEAR, False)
    show_configurable = config_entry.options.get(CONF_SHOW_CONFIGURABLE, False)
    show_configurable_date = config_entry.options.get(CONF_SHOW_CONFIGURABLE_DATE, None)
    store_statistics = config_entry.options.get(CONF_STORE_STATISTICS, False)
    settlement_factor = config_entry.options.get(CONF_SETTLEMENT_FACTOR, 0.8)
    energy_storage_reset_date = config_entry.options.get(CONF_ENERGY_STORAGE_RESET_DATE)
    if energy_storage_reset_date:
        energy_storage_reset_date = parse_date(energy_storage_reset_date)
    if show_configurable_date is not None:
        show_configurable_date = parse_date(show_configurable_date)
    else:
        show_configurable = False

    tauron_amiplus_update_coordinator = TauronAmiplusUpdateCoordinator(
        hass,
        config_entry.entry_id,
        user,
        password,
        meter_id,
        meter_name,
        show_generation=show_generation_sensors,
        show_12_months=show_12_months,
        show_balanced=show_balanced,
        show_balanced_year=show_balanced_year,
        show_configurable=show_configurable,
        show_configurable_date=show_configurable_date,
        store_statistics=store_statistics,
        settlement_factor=settlement_factor,
        energy_storage_reset_date=energy_storage_reset_date,
    )
    config_entry.runtime_data = TauronAmiplusRuntimeData(tauron_amiplus_update_coordinator)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    config_entry.async_on_unload(config_entry.add_update_listener(async_reload_entry))
    register_all_services(hass)
    hass.async_create_task(tauron_amiplus_update_coordinator.async_request_refresh())
    return True


async def _async_setup_outage_entry(hass: HomeAssistant, config_entry) -> bool:
    """Set up an outage address entry (public API, no login)."""
    coordinator = TauronOutageCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
    config_entry.runtime_data = coordinator
    config_entry.async_on_unload(config_entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(config_entry, OUTAGE_PLATFORMS)
    return True


async def async_unload_entry(hass, config_entry) -> bool:
    """Unload a config entry."""
    platforms = OUTAGE_PLATFORMS if config_entry.data.get(CONF_KIND) == KIND_OUTAGE else PLATFORMS
    await hass.config_entries.async_unload_platforms(config_entry, platforms)
    return True


async def async_reload_entry(hass, entry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass, config_entry: TauronAmiplusConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        data = {
            CONF_USERNAME: config_entry.data[CONF_USERNAME],
            CONF_PASSWORD: config_entry.data[CONF_PASSWORD],
            CONF_METER_ID: config_entry.data[CONF_METER_ID],
            CONF_TARIFF: config_entry.data[CONF_TARIFF],
        }
        options = {
            CONF_SHOW_GENERATION: config_entry.data[CONF_SHOW_GENERATION],
            CONF_SHOW_BALANCED: False,
            CONF_SHOW_12_MONTHS: False,
            CONF_SHOW_CONFIGURABLE: False,
            CONF_SHOW_CONFIGURABLE_DATE: datetime.date.today().strftime(DATE_STR_FORMAT),
        }
        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=data, options=options)

    if config_entry.version == 2:
        data = {
            CONF_USERNAME: config_entry.data[CONF_USERNAME],
            CONF_PASSWORD: config_entry.data[CONF_PASSWORD],
            CONF_METER_ID: config_entry.data[CONF_METER_ID],
            CONF_TARIFF: config_entry.data[CONF_TARIFF],
            CONF_METER_NAME: config_entry.data[CONF_METER_ID],
        }
        options = {
            CONF_SHOW_GENERATION: config_entry.options[CONF_SHOW_GENERATION],
            CONF_SHOW_BALANCED: config_entry.options[CONF_SHOW_BALANCED],
            CONF_SHOW_BALANCED_YEAR: False,
            CONF_SHOW_12_MONTHS: config_entry.options[CONF_SHOW_12_MONTHS],
            CONF_SHOW_CONFIGURABLE: config_entry.options[CONF_SHOW_CONFIGURABLE],
            CONF_SHOW_CONFIGURABLE_DATE: config_entry.options[CONF_SHOW_CONFIGURABLE_DATE],
            CONF_STORE_STATISTICS: True,
        }
        config_entry.version = 3
        hass.config_entries.async_update_entry(config_entry, data=data, options=options)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True
