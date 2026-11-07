"""Constants for tauron."""
from datetime import timedelta

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import Platform

PLATFORMS = [Platform.SENSOR]
DOMAIN = "tauron_amiplus"
STATISTICS_DOMAIN = "tauron_importer"
DEFAULT_NAME = "Tauron Amiplus+"
DATA_TAURON_CLIENT = "data_client"
CONF_METER_ID = "energy_meter_id"
CONF_METER_NAME = "energy_meter_name"
CONF_TARIFF = "tariff"
CONF_SHOW_GENERATION = "show_generation_sensors"
CONF_SHOW_BALANCED = "show_balanced_sensors"
CONF_SHOW_BALANCED_YEAR = "show_balanced_year_sensors"
CONF_SHOW_12_MONTHS = "show_12_months_sensors"
CONF_SHOW_CONFIGURABLE = "show_configurable_sensors"
CONF_SHOW_CONFIGURABLE_DATE = "show_configurable_sensors_date"
CONF_STORE_STATISTICS = "store_statistics"
CONF_SETTLEMENT_FACTOR = "settlement_factor"
CONF_ENERGY_STORAGE_RESET_DATE = "energy_storage_reset_date"
DEFAULT_SETTLEMENT_FACTOR = 0.8
CONST_DATE_FORMAT = "%d.%m.%Y"
CONST_MAX_LOOKUP_RANGE = 7
CONST_URL_LOGIN = "https://logowanie.tauron-dystrybucja.pl/login"
CONST_URL_SERVICE = "https://elicznik.tauron-dystrybucja.pl"
CONST_URL_LOGIN_MOJ_TAURON = "https://logowanie.tauron.pl/login"
CONST_URL_SERVICE_MOJ_TAURON = "https://moj.tauron.pl"
CONST_URL_SELECT_METER = f"{CONST_URL_SERVICE}/ustaw_punkt"
CONST_URL_ENERGY = f"{CONST_URL_SERVICE}/energia/api"
CONST_URL_READINGS = f"{CONST_URL_SERVICE}/odczyty/api"
CONST_URL_ENERGY_BUSINESS = f"{CONST_URL_SERVICE}/energia/wo/api"
CONST_REQUEST_HEADERS = {"cache-control": "no-cache"}
CONST_CONSUMPTION = "consumption"
CONST_GENERATION = "generation"
CONST_BALANCED = "balanced"
CONST_READING = "reading"
CONST_DAILY = "daily"
CONST_MONTHLY = "monthly"
CONST_YEARLY = "yearly"
CONST_LAST_12_MONTHS = "last_12_months"
CONST_CONFIGURABLE = "configurable"
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_session_data"
TYPE_BALANCED_DAILY = f"{CONST_BALANCED}_{CONST_DAILY}"
TYPE_BALANCED_MONTHLY = f"{CONST_BALANCED}_{CONST_MONTHLY}"
TYPE_BALANCED_YEARLY = f"{CONST_BALANCED}_{CONST_YEARLY}"
TYPE_BALANCED_LAST_12_MONTHS = f"{CONST_BALANCED}_{CONST_LAST_12_MONTHS}"
TYPE_CONSUMPTION_READING = f"{CONST_CONSUMPTION}_{CONST_READING}"
TYPE_CONSUMPTION_DAILY = f"{CONST_CONSUMPTION}_{CONST_DAILY}"
TYPE_CONSUMPTION_MONTHLY = f"{CONST_CONSUMPTION}_{CONST_MONTHLY}"
TYPE_CONSUMPTION_YEARLY = f"{CONST_CONSUMPTION}_{CONST_YEARLY}"
TYPE_CONSUMPTION_LAST_12_MONTHS = f"{CONST_CONSUMPTION}_{CONST_LAST_12_MONTHS}"
TYPE_GENERATION_READING = f"{CONST_GENERATION}_{CONST_READING}"
TYPE_GENERATION_DAILY = f"{CONST_GENERATION}_{CONST_DAILY}"
TYPE_GENERATION_MONTHLY = f"{CONST_GENERATION}_{CONST_MONTHLY}"
TYPE_GENERATION_YEARLY = f"{CONST_GENERATION}_{CONST_YEARLY}"
TYPE_GENERATION_LAST_12_MONTHS = f"{CONST_GENERATION}_{CONST_LAST_12_MONTHS}"
TYPE_BALANCED_DAILY = f"{CONST_BALANCED}_{CONST_DAILY}"
TYPE_BALANCED_MONTHLY = f"{CONST_BALANCED}_{CONST_MONTHLY}"
TYPE_BALANCED_YEARLY = f"{CONST_BALANCED}_{CONST_YEARLY}"
TYPE_BALANCED_LAST_12_MONTHS = f"{CONST_BALANCED}_{CONST_LAST_12_MONTHS}"
TYPE_CONSUMPTION_CONFIGURABLE = f"{CONST_CONSUMPTION}_{CONST_CONFIGURABLE}"
TYPE_GENERATION_CONFIGURABLE = f"{CONST_GENERATION}_{CONST_CONFIGURABLE}"
TYPE_BALANCED_CONFIGURABLE = f"{CONST_BALANCED}_{CONST_CONFIGURABLE}"
TYPE_ENERGY_STORAGE = "energy_storage"
TYPE_AMOUNT = "amount"
TYPE_AMOUNT_PAYMENT = "amount_payment"

DEFAULT_UPDATE_INTERVAL = timedelta(hours=8, minutes=30)

# Adres wyłączeń prądu (osobny wpis konfiguracji, bez logowania do eLicznika)
CONF_KIND = "kind"
KIND_OUTAGE = "outage"
CONF_CITY_NAME = "city_name"
CONF_CITY_GAID = "city_gaid"
CONF_STREET_NAME = "street_name"
CONF_STREET_GAID = "street_gaid"
CONF_HOUSE_NO = "house_no"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_NOTIFY_DEVICE = "notify_device"
OUTAGE_LOOKAHEAD = timedelta(days=30)
OUTAGE_DEFAULT_SCAN_INTERVAL = 60
OUTAGE_MIN_SCAN_INTERVAL = 15
OUTAGE_MAX_SCAN_INTERVAL = 1440
OUTAGE_MIN_SEARCH_LENGTH = 3
OUTAGE_PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.EVENT, Platform.SENSOR]
OUTAGE_API_BASE_URL = "https://www.tauron-dystrybucja.pl"
OUTAGE_ENDPOINT_CITIES = "/waapi/enum/geo/cities"
OUTAGE_ENDPOINT_STREETS = "/waapi/enum/geo/streets"
OUTAGE_ENDPOINT_OUTAGES = "/waapi/outages/address"

SENSOR_TYPES_YAML = {
    TYPE_CONSUMPTION_READING: {
        "name": "Current consumption reading",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    TYPE_CONSUMPTION_DAILY: {
        "name": "Daily energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_CONSUMPTION_MONTHLY: {
        "name": "Monthly energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_CONSUMPTION_YEARLY: {
        "name": "Yearly energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_CONSUMPTION_LAST_12_MONTHS: {
        "name": "Last 12 months energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_READING: {
        "name": "Current generation reading",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_DAILY: {
        "name": "Daily energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_MONTHLY: {
        "name": "Monthly energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_YEARLY: {
        "name": "Yearly energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_LAST_12_MONTHS: {
        "name": "Last 12 months energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_DAILY: {
        "name": "Daily balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_MONTHLY: {
        "name": "Monthly balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_YEARLY: {
        "name": "Yearly balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_LAST_12_MONTHS: {
        "name": "Last 12 months balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_CONSUMPTION_CONFIGURABLE: {
        "name": "Configurable energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_CONFIGURABLE: {
        "name": "Configurable energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_CONFIGURABLE: {
        "name": "Configurable balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_ENERGY_STORAGE: {
        "name": "Domowy magazyn energii",
        "state_class": SensorStateClass.TOTAL,
        "device_class": "energy",
        "unit_of_measurement": "kWh",
        "icon": "mdi:home-battery-outline",
    },
}

SENSOR_TYPES = {
    **SENSOR_TYPES_YAML,
    TYPE_CONSUMPTION_CONFIGURABLE: {
        "name": "Configurable energy consumption",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_GENERATION_CONFIGURABLE: {
        "name": "Configurable energy generation",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_BALANCED_CONFIGURABLE: {
        "name": "Configurable balance",
        "state_class": SensorStateClass.TOTAL,
    },
    TYPE_ENERGY_STORAGE: {
        "name": "Domowy magazyn energii",
        "state_class": SensorStateClass.TOTAL,
    },
    # TYPE_AMOUNT_PAYMENT: {
    #     "name": "Account balance",
    #     "state_class": SensorStateClass.MEASUREMENT,
    # },
}