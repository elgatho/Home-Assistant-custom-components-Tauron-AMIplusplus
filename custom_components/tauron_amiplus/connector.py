"""Update coordinator for TAURON sensors."""
import copy
import datetime
import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Any

from aiohttp import ClientSession
# from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .hourly_data import MEASUREMENT_TYPES, expected_hours_for_day, normalize_daily_data, parse_daily_endpoint
from .const import (
    CONST_DATE_FORMAT,
    CONST_MAX_LOOKUP_RANGE,
    CONST_REQUEST_HEADERS,
    CONST_URL_ENERGY,
    CONST_URL_ENERGY_BUSINESS,
    CONST_URL_LOGIN,
    CONST_URL_LOGIN_MOJ_TAURON,
    CONST_URL_READINGS,
    CONST_URL_SELECT_METER,
    CONST_URL_SERVICE,
    CONST_URL_SERVICE_MOJ_TAURON,
    STORAGE_VERSION,
    STORAGE_KEY_PREFIX,
)

_LOGGER = logging.getLogger(__name__)


class TauronAmiplusRawData:
    def __init__(self):
        self.tariff = None
        self.consumption: Optional[TauronAmiplusDataSet] = None
        self.generation: Optional[TauronAmiplusDataSet] = None
        self.payments: Optional[list[MojTauronPaymentData]] = None
        self.hourly_series = {}
        self.hourly_diagnostics = {}
        self.balanced = None

    def data_unavailable(self):
        return self.consumption is None or self.generation is None

    def _balanced(self, period):
        return self.balanced.get(period) if self.balanced else None

    @property
    def balance_daily(self):
        return self._balanced("daily")

    @property
    def balance_monthly(self):
        return self._balanced("monthly")

    @property
    def balance_yearly(self):
        return self._balanced("yearly")

    @property
    def balance_last_12_months_hourly(self):
        if (self.data_unavailable() or
                self.consumption.json_last_12_months_hourly is None or
                self.generation.json_last_12_months_hourly is None):
            return None
        return self.consumption.json_last_12_months_hourly, self.generation.json_last_12_months_hourly

    @property
    def balance_configurable_hourly(self):
        if (self.data_unavailable() or
                self.consumption.json_configurable_hourly is None or
                self.generation.json_configurable_hourly is None):
            return None
        return self.consumption.json_configurable_hourly, self.generation.json_configurable_hourly


class TauronAmiplusDataSet:
    def __init__(self):
        self.hourly_series = {measurement_type: [] for measurement_type in MEASUREMENT_TYPES}
        self.hourly_diagnostics = {}
        self.json_reading = None
        self.json_daily = None
        self.daily_date = None
        self.json_monthly = None
        self.json_yearly = None
        self.json_month_hourly = None
        self.json_year_hourly = None
        self.json_last_30_days_hourly = None
        self.json_last_12_months_hourly = None
        self.json_configurable_hourly = None


@dataclass
class MojTauronPaymentData:
    value: float
    date: str


class TauronAmiplusConnector:

    def __init__(
        self,
        username: str,
        password: str,
        meter_id: str,
        hass: HomeAssistant | None = None,
        config_entry_id: str = None,
        show_generation: bool = False,
        show_12_months: bool = False,
        show_balanced: bool = False,
        show_balanced_yearly: bool = False,
        show_configurable: bool = False,
        show_configurable_date: datetime.date = None,
    ):
        self._username = username
        self._password = password
        self._meter_id = meter_id
        self._is_business = False
        self.meters = []
        self._show_generation = show_generation
        self._show_12_months = show_12_months
        self._show_balanced = show_balanced
        self._show_balanced_yearly = show_balanced_yearly
        self._show_configurable = show_configurable
        self._show_configurable_date = show_configurable_date
        self._session: ClientSession | None = None
        self._cache = DailyDataCache(meter_id)
        self._cycle_cache: dict[tuple, Any] = {}
        self.hourly_series = {measurement_type: [] for measurement_type in MEASUREMENT_TYPES}
        self.hourly_diagnostics = {}
        self._hass = hass
        self._storage_key = f"{STORAGE_KEY_PREFIX}_{config_entry_id}" if config_entry_id is not None else None

    async def get_raw_data(self, include_statistics: bool = True) -> TauronAmiplusRawData:
        data = TauronAmiplusRawData()
        # data.payments = await self.get_moj_tauron()
        data.tariff = await self.login()
        generation_max_cache = datetime.datetime.now()
        data.consumption, consumption_max_cache = await self.get_data_set(
            generation=False, include_statistics=include_statistics
        )
        if self._show_generation or self._show_balanced:
            data.generation, generation_max_cache = await self.get_data_set(
                generation=True, include_statistics=include_statistics
            )
        else:
            data.generation = TauronAmiplusDataSet()
        self._cache.delete_older_than(min(consumption_max_cache, generation_max_cache))
        return data

    async def get_light_data(self) -> TauronAmiplusRawData:
        """Only what the Recorder cannot provide: tariff and meter readings (daily/monthly/yearly values and
        hourly series are built from the Recorder, see TauronAmiplusStatisticsUpdater)."""
        self._cycle_cache.clear()
        data = TauronAmiplusRawData()
        data.tariff = await self.login()
        data.consumption = TauronAmiplusDataSet()
        data.consumption.json_reading = await self.get_reading(False)
        data.generation = TauronAmiplusDataSet()
        if self._show_generation or self._show_balanced:
            data.generation.json_reading = await self.get_reading(True)
        self._cache.delete_older_than(datetime.datetime.now() - datetime.timedelta(days=8))
        return data

    async def get_zones_name(self) -> dict:
        """Zones of the current tariff, taken from the latest available day (usually one request)."""
        values, _ = await self.get_values_daily(False)
        return dict(values["data"].get("zonesName", {})) if values else {}

    async def get_data_set(self, generation, include_statistics: bool = True) -> Tuple[TauronAmiplusDataSet, datetime.datetime]:
        dataset = TauronAmiplusDataSet()
        dataset.json_reading = await self.get_reading(generation)
        dataset.json_daily, dataset.daily_date = await self.get_values_daily(generation)
        dataset.json_monthly = await self.get_values_monthly(generation)
        dataset.json_yearly = await self.get_values_yearly(generation)
        if include_statistics:
            dataset.json_month_hourly = await self.get_values_month_hourly(generation)
            dataset.json_last_30_days_hourly = await self.get_values_last_30_days_hourly(generation)
        now = datetime.datetime.now()
        cache_max = datetime.datetime.now() - datetime.timedelta(days=32)
        if self._show_12_months and include_statistics:
            dataset.json_last_12_months_hourly = await self.get_values_12_months_hourly(generation)
            cache_max = now.replace(year=now.year - 1) - datetime.timedelta(days=2)
        if self._show_balanced_yearly and include_statistics:
            dataset.json_year_hourly = await self.get_values_year_hourly(generation)
            potential_max = now.replace(day=1, month=1)
            if potential_max < cache_max:
                cache_max = potential_max
        if include_statistics and self._show_configurable and self._show_configurable_date is not None:
            end = datetime.datetime.now()
            start = datetime.datetime.combine(self._show_configurable_date, end.time())
            dataset.json_configurable_hourly = await self.get_raw_values_daily_for_range(start, end, generation)
            potential_max = end - datetime.timedelta(days=2)
            if potential_max < cache_max:
                cache_max = potential_max
        return dataset, cache_max

    async def login_service(self, login_url: str, service: str) -> tuple[ClientSession, str]:
        success, response, session = await self.try_restore_session(service)
        if success:
            return session, response

        self.log(f"Logging in... ({service})")

        # Step 1: GET login page to retrieve the Keycloak form action URL.
        # TAURON migrated from CAS to Keycloak (OpenID Connect) — old POST /login returns 404.
        login_page_response = await session.request(
            "GET",
            f"{login_url}?service={service}",
            headers=CONST_REQUEST_HEADERS,
            allow_redirects=True,
        )
        login_page_text = await login_page_response.text()
        self.log(f"LOGIN PAGE STATUS: {login_page_response.status}")

        form_action_match = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', login_page_text)
        if form_action_match is None:
            self.log("Keycloak login form not found in response")
            raise Exception("Failed to find login form")
        form_action = form_action_match.group(1).replace("&amp;", "&")
        self.log(f"FORM ACTION: {form_action[:120]}")

        # Step 2: POST credentials to Keycloak, follow redirects back to the service.
        payload_login = {
            "username": self._username,
            "password": self._password,
            "credentialId": "",
        }
        login_response = await session.request(
            "POST",
            form_action,
            data=payload_login,
            headers=CONST_REQUEST_HEADERS,
            allow_redirects=True,
        )
        login_response_text = await login_response.text()
        self.log(f"LOGIN RESPONSE STATUS: {login_response.status}")

        if "Przekroczono maksymalną liczbę logowań." in login_response_text:
            self.log("Too many login attempts")
            raise Exception("Too many login attempts")
        # If we're still on the Keycloak login page, credentials were rejected.
        if 'id="kc-form-login"' in login_response_text:
            self.log("Invalid credentials")
            raise ConfigEntryAuthFailed("Invalid credentials")
        if (self._username not in login_response_text and
                self._username.upper() not in login_response_text.upper()):
            self.log("Failed to login - username not found in response")
            raise Exception("Failed to login")

        await self.store_session(session, service)
        return session, login_response_text

    async def try_restore_session(self, service: str) -> (bool, str | None, ClientSession):
        session = async_create_clientsession(self._hass)
        if self._storage_key is None or self._hass is None:
            self.log("NO SESSION TO RESTORE ({service})")
            return False, None, session
        self.log(f"RESTORING SESSION {self._storage_key}_{slugify(service)}")
        store = Store(self._hass, STORAGE_VERSION, f"{self._storage_key}_{slugify(service)}")
        stored_data = await store.async_load()
        if stored_data is None:
            return False, None, session
        cookies = {k: v for k, v in stored_data.get("cookies", {}).items() if k in ["PHPSESSID", "ASP.NET_SessionId"]}
        self.log(f"COOKIES ({service}): {cookies}")
        session.cookie_jar.clear(lambda x: True)
        session.cookie_jar.update_cookies(cookies)

        success, response = await self.validate_session(session, service)
        self.log(f"SESSION VALID ({service}): {success}")

        if success:
            session_to_return = session
        else:
            self.log(f"FAILED TO RESTORE SESSION ({service})")
            self.log(f"INVALID SESSION RESPONSE ({service})")
            self.log(response)
            await store.async_save({})
            session_to_return = async_create_clientsession(self._hass)
        return success, response, session_to_return

    async def store_session(self, session: ClientSession, service: str) -> None:
        if self._storage_key is None or self._hass is None:
            self.log(f"SKIPPING STORING SESSION")
            return
        self.log(f"SAVING SESSION {self._storage_key}_{slugify(service)}")
        store = Store(self._hass, STORAGE_VERSION, f"{self._storage_key}_{slugify(service)}")
        cookies = {cookie.key: cookie.value for cookie in session.cookie_jar if cookie.key in ["PHPSESSID", "ASP.NET_SessionId"]}
        self.log(f"SAVED COOKIES ({service}) {cookies}")
        await store.async_save({"cookies": cookies})

    async def validate_session(self, session: ClientSession, service: str) -> (bool, str):
        response = await session.get(service)
        response_text = await response.text()
        return self._username in response_text or self._username.upper() in response_text.upper(), response_text

    async def login(self):
        session, login_response_text = await self.login_service(CONST_URL_LOGIN, CONST_URL_SERVICE)
        self._session = session
        self.log("Logged in to eLicznik.")
        self.meters = self._get_meters(login_response_text)
        payload_select_meter = {"site[client]": self._meter_id}
        selected_meter_info = list(filter(lambda m: m["meter_id"] == self._meter_id, self.meters))
        if len(selected_meter_info) > 0:
            self._is_business = selected_meter_info[0]["meter_type"] == "WO"
        else:
            self._is_business = False
        self.log(f"Selecting meter: {self._meter_id}")
        select_response = await self._session.request("POST", CONST_URL_SELECT_METER, data=payload_select_meter, headers=CONST_REQUEST_HEADERS)
        select_response_text = await select_response.text()
        tariff_search = re.findall(r"[^_]Tariff: '(.*)',", select_response_text)
        if len(tariff_search) > 0:
            tariff = tariff_search[0]
            return tariff
        return "unknown"

    def clear_cache(self) -> None:
        self._cache.clear()

    @staticmethod
    def _get_meters(text: str) -> list:
        regex = r".*data-data='{\"type\": \".*\"}'>.*"
        matches = list(re.finditer(regex, text))
        meters = []
        for match in matches:
            m1 = re.match(r".*value=\"([\d\_]+)\".*", match.group())
            m2 = re.match(r".*\"}'>(.*)</option>", match.group())
            m3 = re.match(r".*data-data='{\"type\": \"(.*)\"}'>.*", match.group())
            if m1 is None or m2 is None or m3 is None:
                continue
            meter_id = m1.groups()[0]
            display_name = m2.groups()[0]
            meter_type = m3.groups()[0]
            meters.append({"meter_id": meter_id, "meter_name": display_name, "meter_type": meter_type})
        return meters

    @staticmethod
    def normalize_period_zones(values):
        """Rebuild zone totals of monthly/yearly data so that periods with a tariff change stay separated.

        The API reports zones by number only, so a month containing both G11 (zone 1 = whole day) and
        G12W (zone 1 = peak) would otherwise be summed into a single, misleading zone 1.
        """
        if not values or not isinstance(values.get("data"), dict):
            return values
        data = values["data"]
        rows = data.get("allData")
        current = data.get("tariff")
        if not rows or not current or not all("Tariff" in r and "Zone" in r and "Sum" in r for r in rows):
            return values
        zones, zones_name = {}, {}
        for row in rows:
            zone, tariff = str(row["Zone"]), row["Tariff"]
            try:
                value = float(row["Sum"])
            except (TypeError, ValueError):
                continue
            label = f'{row.get("ZoneName", zone)} ({row.get("WorkName", "T" + zone)})'
            if tariff == current:
                key, name = zone, label
            else:
                key, name = f"{tariff}_{zone}", f"{label} [{tariff}]"
            zones[key] = zones.get(key, 0) + value
            zones_name.setdefault(key, name)
        data["zones"] = zones
        data["zonesName"] = zones_name
        return values

    async def get_values_yearly(self, generation):
        now = datetime.datetime.now()
        first_day_of_year = now.replace(day=1, month=1)
        last_day_of_year = now.replace(day=31, month=12)
        payload = {
            "from": TauronAmiplusConnector.format_date(first_day_of_year),
            "to": TauronAmiplusConnector.format_date(last_day_of_year),
            "profile": "year",
            "type": "oze" if generation else "consum",
            "energy": 2 if generation else 1,
        }
        self.log(f"Downloading yearly data for year: {now.year}, generation: {generation}")
        values = await self.get_chart_values(payload)
        if values is not None:
            values = TauronAmiplusConnector.normalize_period_zones(values)
            self.log(f"Downloaded yearly data for year: {now.year}, generation: {generation}")
        else:
            self.log(f"Failed to download yearly data for year: {now.year}, generation: {generation}")
        return values

    async def get_values_monthly(self, generation):
        now = datetime.datetime.now()
        month = now.month
        first_day_of_month = now.replace(day=1)
        last_day_of_month = (first_day_of_month + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)

        payload = {
            "from": TauronAmiplusConnector.format_date(first_day_of_month),
            "to": TauronAmiplusConnector.format_date(last_day_of_month),
            "profile": "month",
            "type": "oze" if generation else "consum",
            "energy": 2 if generation else 1,
        }
        values = await self.get_chart_values(payload)
        if values is not None:
            values = TauronAmiplusConnector.normalize_period_zones(values)
            self.log(f"Downloaded monthly data for month: {now.year}.{now.month}, generation: {generation}")
        else:
            self.log(f"Failed to download monthly data for month: {now.year}.{now.month}, generation: {generation}")
        return values

    async def get_values_daily(self, generation):
        offset = 1
        data = None
        day = None
        while offset <= CONST_MAX_LOOKUP_RANGE and data is None:
            data, day = await self.get_raw_values_daily(offset, generation)
            offset += 1
        return data, day

    async def get_raw_values_daily(self, days_before, generation):
        day = datetime.datetime.now() - datetime.timedelta(days_before)
        return await self.get_raw_values_daily_for_day(day, generation), TauronAmiplusConnector.format_date(day)

    async def get_values_month_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now.replace(day=1)
        return await self.get_raw_values_daily_for_range(start_day, now, generation)

    async def get_values_year_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now.replace(day=1, month=1)
        return await self.get_raw_values_daily_for_range(start_day, now, generation)

    async def get_values_last_30_days_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now - datetime.timedelta(days=30)
        return await self.get_raw_values_daily_for_range(start_day, now, generation)

    async def get_values_12_months_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now.replace(year=now.year - 1)
        return await self.get_raw_values_daily_for_range(start_day, now, generation)

    async def get_raw_values_daily_for_range(self, day_from: datetime.date, day_to: datetime.date, generation):
        data = {"data": {
            "allData": [],
            "sum": 0,
            "zones": {},
            "zonesName": {}
        }}
        days_data = []
        for day in [day_from + datetime.timedelta(days=x) for x in range((day_to - day_from).days + 1)]:
            day_data = await self.get_raw_values_daily_for_day(day, generation)
            if day_data is not None:
                days_data.append(day_data)

        # The most recent day defines the current tariff; days from other tariffs keep their zones separate.
        current_tariff = next((d["data"]["tariff"] for d in reversed(days_data) if d["data"].get("tariff")), None)
        for day_data in days_data:
            day_info = day_data["data"]
            items = day_info["allData"]
            zones_name = day_info["zonesName"]
            zones = day_info["zones"]
            day_tariff = day_info.get("tariff")
            if current_tariff and day_tariff and day_tariff != current_tariff:
                prefix = f"{day_tariff}_"
                suffix = f" [{day_tariff}]"
                items = [{**item, "Zone": prefix + str(item["Zone"])} for item in items]
                zones_name = {prefix + str(k): v + suffix for k, v in zones_name.items()}
                zones = {prefix + str(k): v for k, v in zones.items()}
            data["data"]["allData"].extend(items)
            data["data"]["sum"] += day_info["sum"]
            data["data"]["zonesName"] = {**data["data"]["zonesName"], **zones_name}
            if day_tariff:
                data["data"]["tariff"] = day_tariff
            for z, v in zones.items():
                data["data"]["zones"][z] = data["data"]["zones"].get(z, 0) + v

        if len(data["data"]["allData"]) == 0:
            return None
        return data

    async def get_raw_values_daily_for_day(self, day, generation: bool):
        day_str = TauronAmiplusConnector.format_date(day)
        cached_data = self._cache.get_value(day, generation)
        if cached_data is not None:
            self.log(f"Cache hit for day {day_str}, generation: {generation}")
            return cached_data

        payload = {
            "from": day_str,
            "to": day_str,
            "profile": "full time",
            "type": "oze" if generation else "consum",
            "energy": 2 if generation else 1,
        }
        self.log(f"Downloading daily data for day: {day_str}, generation: {generation}")
        values = await self.get_chart_values(payload)
        if values is not None:
            if values["data"].get("allData") is None or any(
                a is None or not self.contains_data(a) for a in values["data"]["allData"]
            ):
                self.add_all_data(values, day)
                self.log(f"Replaced allData: {values}")
            else:
                for reading in values["data"]["allData"]:
                    reading.setdefault("Date", day.strftime("%Y-%m-%d"))
            self.normalize_daily_data(values, day)
            if all(self.contains_data(a) for a in values["data"]["allData"]):
                self._cache.add_value(day, generation, values)
            measurement_type = "oze" if generation else "consum"
            parsed = parse_daily_endpoint(measurement_type, day.date() if hasattr(day, "date") else day, {"data": values.get("data", {})}, logger=_LOGGER)
            if parsed is not None:
                self.hourly_diagnostics[str(day.date() if hasattr(day, "date") else day)] = parsed.diagnostics
            values["data"]["allData"] = [
                d for d in values["data"]["allData"] if self.contains_data(d)
            ]
            self.log(f"Downloaded daily data for day: {day_str}, generation: {generation}")
            return values
        self.log(f"Failed to download daily data for day: {day_str}, generation: {generation}")
        return None

    async def get_hourly_readings(self, measurement_type: str, first_day: datetime.date, last_day: datetime.date):
        """Download hourly readings of one series (consum, oze, netto, netto_oze), one request per day."""
        readings = []
        day = first_day
        while day <= last_day:
            payload = {
                "from": TauronAmiplusConnector.format_date(day),
                "to": TauronAmiplusConnector.format_date(day),
                "profile": "full time",
                "type": measurement_type,
            }
            values = await self.get_chart_values(payload)
            if values is not None:
                parsed = parse_daily_endpoint(measurement_type, day, {"data": values.get("data", {})}, logger=_LOGGER)
                if parsed is not None:
                    readings.extend(parsed.readings)
            day += datetime.timedelta(days=1)
        return readings

    async def get_reading(self, generation):
        date_to = datetime.datetime.now()
        date_from = (date_to - datetime.timedelta(CONST_MAX_LOOKUP_RANGE))

        date_to_str = TauronAmiplusConnector.format_date(date_to)
        payload = {
            "from": TauronAmiplusConnector.format_date(date_from),
            "to": date_to_str,
            "type": "energia-oddana" if generation else "energia-pobrana"
        }
        self.log(f"Downloading readings for date: {date_to_str}, generation: {generation}")
        post = await self.execute_post(CONST_URL_READINGS, payload)
        if post is not None:
            self.log(f"Downloaded readings for date: {date_to_str}, generation: {generation}")
        else:
            self.log(f"Failed to download readings for date: {date_to_str}, generation: {generation}")
        return post

    async def get_chart_values(self, payload):
        return await self.execute_post(CONST_URL_ENERGY_BUSINESS if self._is_business else CONST_URL_ENERGY, payload)

    async def execute_post(self, url: str, payload: dict):
        # Identical requests within one refresh cycle (e.g. the same day needed by several sensors) hit the API once
        cache_key = (url, tuple(sorted((k, str(v)) for k, v in payload.items())))
        if cache_key in self._cycle_cache:
            self.log(f"Cycle cache hit: {url} with payload: {payload}")
            return copy.deepcopy(self._cycle_cache[cache_key])
        result = await self._execute_post(url, payload)
        if result is not None:
            self._cycle_cache[cache_key] = copy.deepcopy(result)
        return result

    async def _execute_post(self, url: str, payload: dict):
        self.log(f"EXECUTING: {url} with payload: {payload}")
        if self._session is None or self._session.closed:
            self.log("HTTP session is closed; re-authenticating")
            await self.login()
        response = await self._session.request(
            "POST",
            url,
            data=payload,
            headers=CONST_REQUEST_HEADERS,
        )
        response_text = await response.text()
        self.log(f"RESPONSE: {response_text}")
        if "Przekroczono maksymalną liczbę logowań." in response_text:
            self.log("Too many login attempts")
            raise Exception("Too many login attempts")
        if response.status == 200 and response_text.startswith('{"success":true'):
            json_data = await response.json()
            self.log(f"RESPONSE JSON: {json_data}")
            return json_data
        return None

    def log(self, msg):
        _LOGGER.debug(f"[{self._meter_id}]: {msg}")

    async def get_moj_tauron(self) -> list[MojTauronPaymentData]:
        session, response_text = await self.login_service(CONST_URL_LOGIN_MOJ_TAURON, CONST_URL_SERVICE_MOJ_TAURON)
        self.log("MÓJ TAURON")
        self.log(response_text)
        if response_text is None:
            return []
        try:
            # parser = BeautifulSoup(response_text, "html.parser")
            # amounts = parser.select(".amount:not(.okay):not(.warning)")
            # dates = parser.select(".date:not(.okay):not(.warning)")
            payments = []
            # for i in range(min(len(amounts), len(dates))):
            #     try:
            #         amount = float(amounts[i].text.strip().split("\n")[0].strip().replace(",", ".").replace(" zł", ""))
            #         date = dates[i].text.replace("Termin:", "").strip()
            #         payments.append(MojTauronPaymentData(amount, date))
            #     except Exception as err:
            #         _LOGGER.error("Error during parsing. %s", err)
            return payments
        except Exception as err:
            _LOGGER.error("Error during downloading. %s", err)
            return []

    @staticmethod
    def format_date(date):
        return date.strftime(CONST_DATE_FORMAT)

    @staticmethod
    async def get_available_meters(username, password, hass: HomeAssistant):
        connector = TauronAmiplusConnector(username, password, "placeholder", hass)
        await connector.login()
        if connector.meters is not None and len(connector.meters) > 0:
            return connector.meters
        raise Exception("Failed to retrieve energy meters")

    @staticmethod
    async def calculate_tariff(username, password, meter_id, hass: HomeAssistant):
        connector = TauronAmiplusConnector(username, password, meter_id, hass)
        tariff = await connector.login()
        if tariff is not None:
            return tariff
        raise Exception("Failed to calculate configuration")

    @staticmethod
    def add_all_data(data: dict, date):
        all_datas = []
        zones_name = data['data'].get('zonesName') or {}
        zone = next(iter(zones_name), "1")
        for i, v in enumerate(data["data"]["values"]):
            if zones_name and data['data'].get('chartZones'):
                selected_zones = [item for item in data["data"]["chartZones"].items() if i < len(item[1]) and item[1][i]]
                if len(selected_zones) > 0:
                    zone = selected_zones[0][0]
            all_datas.append({
                "EC": v,
                "Date": date.strftime("%Y-%m-%d"),
                "Hour": i + 1,
                "Zone": zone,
                "Status": "0"
            })

        data["data"]["allData"] = all_datas

    @staticmethod
    def get_expected_hours_for_day(day) -> int:
        return expected_hours_for_day(day)

    @staticmethod
    def normalize_daily_data(data: dict, day) -> None:
        normalize_daily_data(data, day)

    @staticmethod
    def contains_data(hourly_entry: dict[str, Any]) -> bool:
        return hourly_entry.get("Status") is not None and hourly_entry.get("EC") is not None


class DailyDataCache:

    def __init__(self, meter_id):
        self._consumption_data = dict()
        self._generation_data = dict()
        self._max_date = datetime.datetime.now() + datetime.timedelta(days=1)
        self._meter_id = meter_id

    def __contains__(self, item: Tuple[str, bool]):
        date_str, generation = item
        if generation:
            return date_str in self._generation_data
        return date_str in self._consumption_data

    def add_value(self, date: datetime.datetime, generation: bool, value):
        date = date.replace(tzinfo=None)
        date_str = self._format_date(date)
        if value is None:
            return
        if generation:
            self._generation_data[date_str] = value
        else:
            self._consumption_data[date_str] = value
        if self._max_date is None or self._max_date > date:
            self._max_date = date

    def get_value(self, date: datetime.datetime, generation: bool):
        date_str = self._format_date(date)
        if (date_str, generation) in self:
            if generation:
                return self._generation_data[date_str]
            return self._consumption_data[date_str]
        return None

    def delete_older_than(self, date: datetime.datetime):
        date = date.replace(tzinfo=None)
        if date > self._max_date:
            for d in [self._max_date + datetime.timedelta(days=x) for x in range((date - self._max_date).days)]:
                self.delete_day(d)
            self._max_date = date

    def delete_day(self, date: datetime.datetime):
        date_str = self._format_date(date)
        self.log(f"Deleting data from cache for day: {date_str}")
        if date_str in self._generation_data:
            self._generation_data.pop(date_str)
        if date_str in self._consumption_data:
            self._consumption_data.pop(date_str)

    def clear(self) -> None:
        self.log(
            f"Clearing cache: consumption - {len(self._consumption_data)}, generation - {len(self._generation_data)}"
        )
        self._generation_data.clear()
        self._consumption_data.clear()

    @staticmethod
    def _format_date(date):
        return date.strftime("%Y-%m-%d")

    def log(self, msg):
        _LOGGER.debug(f"[{self._meter_id}]: {msg}")
