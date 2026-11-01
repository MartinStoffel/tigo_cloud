"""Business Logic for Tigo."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from http.cookies import Morsel
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import TIGO_URL

_LOGGER = logging.getLogger(__name__)

# Time between updating data, for the premium plan and while the plan is unknown
SCAN_INTERVAL = timedelta(minutes=1)
# The data of the free plan changes only about every 15 minutes
FREE_SCAN_INTERVAL = timedelta(minutes=5)
# Month, year and lifetime totals change slowly, so they are fetched less often
SLOW_SCAN_INTERVAL = timedelta(minutes=15)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
# Fetch the secondary values in parallel, but no more at once than a browser would
MAX_PARALLEL_REQUESTS = 4
# Tigo's servers often answer with a server error (5xx) and succeed a few seconds
# later. Its web portal retries after 5 seconds as well
RETRIES = 2
RETRY_DELAY = 5  # seconds

# Panel readings. The free plan covers power and reclaimed power (and the energy,
# read separately), all others need the premium plan
PANEL_VALUES = ("pin", "rssi", "pwm", "temp", "vin", "vout", "iin", "reclaimedPower")
FREE_PANEL_VALUES = ("pin", "reclaimedPower")

type TigoConfigEntry = ConfigEntry[TigoCoordinator]


class TigoError(Exception):
    """Base class for errors talking to the Tigo cloud."""


class TigoConnectionError(TigoError):
    """The Tigo cloud could not be reached."""


class TigoResponseError(TigoError):
    """The Tigo cloud answered with an error or unexpected data."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.status = status


class TigoAuthError(TigoError):
    """The Tigo cloud rejected the username or password."""


class TigoSystemError(TigoError):
    """The system id is unknown or not accessible with this account."""


def create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Create a session with its own cookie jar, as the Tigo login is cookie based."""
    return async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())


def _has_data(reading: Any) -> bool:
    """Return whether a reading has a value; for panel readings, of any panel."""
    if isinstance(reading, dict):
        return any(v is not None for v in reading.values())
    return reading is not None


def _dataset(response: Any) -> dict[str, Any]:
    """Return the readings per panel id of a response."""
    dataset = response["dataset"]
    if not dataset:  # PHP encodes an empty map as []
        return {}
    if not isinstance(dataset, dict):
        raise TypeError(f"dataset is a {type(dataset).__name__}")
    return dataset


class CookieCache:
    """Manages the cookie / auth bearer from the web login."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize the cache."""
        self._session = session
        self._username = username
        self._password = password
        self._cookie: Morsel[str] | None = None
        self._valid_till = datetime.min.replace(tzinfo=UTC)

    async def get_auth_header(self) -> dict[str, str]:
        """Return the Auth header, logging in first if needed."""
        if self._cookie is None or self._valid_till <= dt_util.utcnow():
            self._cookie = await self.__login()
        return {
            "accept": "application/json",
            "Authorization": f"Bearer {self._cookie.value}",
        }

    def reset_cookie(self) -> None:
        """Forget the cookie, so the next request logs in again."""
        self._cookie = None

    async def __login(self) -> Morsel[str]:
        """Log in to the web UI and return the JWT cookie it sets."""
        # Drop the cookies of an earlier login, so a stale JWT can't pass for a new one
        self._session.cookie_jar.clear()
        try:
            async with self._session.get(TIGO_URL, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                text = await response.text()
            csrf = next(
                (
                    line.split('"')[1]
                    for line in text.splitlines()
                    if "TIGO_CSRF_TOKEN" in line and '"' in line
                ),
                None,
            )
            if csrf is None:
                raise TigoResponseError("No CSRF token on the Tigo login page")

            form_data = {
                "_csrf": csrf,
                "LoginFormModel[login]": self._username,
                "LoginFormModel[password]": self._password,
                "LoginFormModel[remember_me]": "0",
            }
            async with self._session.post(
                TIGO_URL, data=form_data, timeout=REQUEST_TIMEOUT
            ) as response:
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TigoConnectionError(f"Tigo login failed: {err}") from err

        cookie = next((c for c in self._session.cookie_jar if c.key == "wssJwt"), None)
        if cookie is None:
            # A rejected login shows the login form again; other answers (rate limit,
            # server error) are no reason to ask for the password
            if status in (200, 401, 403):
                raise TigoAuthError("Tigo rejected the login, check username and password")
            raise TigoResponseError(f"Tigo login failed with status {status}", status)

        # Renew an hour before the cookie expires; without a max-age, renew on a 401
        max_age = str(cookie["max-age"])
        self._valid_till = (
            dt_util.utcnow() + timedelta(seconds=int(max_age), hours=-1)
            if max_age.isdigit()
            else datetime.max.replace(tzinfo=UTC)
        )
        return cookie


class TigoData:
    """Fetches the system layout and the readings from the Tigo cloud."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str, systemid: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._cookie_cache = CookieCache(session, username, password)
        self._system_id = systemid
        self._last_time: str | None = None
        self._last_slow_update: datetime | None = None
        # Readings that had a value at least once, and readings failing right now
        self._delivered: set[str] = set()
        self._failing: set[str] = set()
        self._request_limit = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
        # The day the plan was last read; the plan itself is in the data
        self._plan_date: date | None = None
        self._data: dict[str, Any] = {}

    async def _update_plan(self, today: date, headers: dict[str, str]) -> None:
        """Read once a day whether the system has the premium plan."""
        if self._plan_date == today:
            return
        query = f"/system/summary/systeminfo?system_id={self._system_id}&date={today}&resourceId=dateinfo-{today}&v=0.1.0&_=0"
        try:
            premium = (await self._get_json(query, headers)).get("has_premium")
        except (TigoError, AttributeError) as err:
            # Keep the plan known so far, and try again on the next update
            _LOGGER.debug("Reading the plan failed: %s", err)
            return
        if isinstance(premium, bool):
            plan = "Premium" if premium else "Free"
            if plan != self._data.get("plan"):
                _LOGGER.debug("The system has the %s plan", plan)
                self._data["plan"] = plan
        self._plan_date = today

    def get_value(self, graph) -> Any:
        """Return the reading, None if the graph has no solar total."""
        for serie in graph["series"]:
            if serie["id"] == "solar_total":
                result = 0
                for data in serie["data"]:
                    if data[1] is not None:
                        result = data[1]
                return result
        return None

    async def async_get_panels(self) -> list[dict[str, Any]]:
        """Log in and return the panels of the system."""
        # This endpoint authenticates with the login cookies instead of the bearer
        await self._cookie_cache.get_auth_header()
        query = f"/system/summary/config?system_id={self._system_id}&resourceId=config&v=0.1.0&_=0"
        try:
            system = await self._get_json(query)
            return [x for x in system["system"]["objects"] if x.get("B") == 2]
        except (TigoResponseError, KeyError, TypeError, AttributeError) as err:
            raise TigoSystemError(
                f"System {self._system_id} is not accessible: {err}"
            ) from err

    async def fetch_data(self) -> dict[str, Any]:
        """Get the data from the web api."""
        today = dt_util.now().date()
        val = await self._get_api(
            f"/api/v4/system/summary/aggenergy?system_id={self._system_id}&date={today}"
        )
        try:
            self._data["energy"] = _dataset(val)
            last_data = val["datasetLastData"]
            # HH:MM of the latest reading, empty before the first reading of the day
            time = next(iter(last_data.values()), "")[11:16] if last_data else ""
        except (KeyError, TypeError, AttributeError) as err:
            raise TigoResponseError(f"Unexpected energy data: {err}") from err

        headers = await self._cookie_cache.get_auth_header()
        await self._update_plan(today, headers)

        requests = []
        if time and time != self._last_time:
            self._last_time = time
            free = self._data.get("plan") == "Free"
            for value in PANEL_VALUES:
                if free and value not in FREE_PANEL_VALUES:
                    # Not covered by the free plan
                    self._data.pop(value, None)
                    continue
                requests.append(
                    self._fetch_optional(
                        value,
                        f"/api/v4/system/summary/lastvalue?system_id={self._system_id}&resourceId=lastValue-{today}-{value}-{time}&v=0.1.0&_=0",
                        headers,
                        _dataset,
                    )
                )

        # Get summary data; a slow total that stopped arriving is retried on the next
        # update instead of showing unknown until the next slow update
        aggs = ["now", "hour", "day"]
        now = dt_util.utcnow()
        retry = any(
            key in self._failing and key in self._delivered
            for key in ("month", "year", "allTime")
        )
        if (
            retry
            or self._last_slow_update is None
            or now - self._last_slow_update >= SLOW_SCAN_INTERVAL
        ):
            self._last_slow_update = now
            aggs += ["month", "year"]
            requests.append(
                self._fetch_optional(
                    "allTime",
                    f"/fleet/system/overview/data-lifetime?sysid={self._system_id}&range=lifetime",
                    headers,
                    lambda value: value["energy"],
                )
            )
        requests += [
            self._fetch_optional(
                agg,
                f"/api/v4/data/aggregate?systemId={self._system_id}&view=gen&output=echart&type=bar&agg={agg}&start={today}&end={today}&reclaimed=true",
                headers,
                self.get_value,
            )
            for agg in aggs
        ]
        await asyncio.gather(*requests)
        return dict(self._data)

    async def _fetch_optional(
        self, key: str, query: str, headers: dict[str, str], parse: Callable[[Any], Any]
    ) -> None:
        """Fetch a secondary value; a failure makes it unknown instead of failing the update."""
        try:
            async with self._request_limit:
                response = await self._get_json(query, headers)
            value = parse(response)
        except (TigoError, LookupError, TypeError, AttributeError) as err:
            # Show unknown rather than the reading of an earlier time
            self._data.pop(key, None)
            if key not in self._failing:
                self._failing.add(key)
                # Data the plan doesn't cover may never have a value, no reason to warn
                level = logging.WARNING if key in self._delivered else logging.DEBUG
                _LOGGER.log(level, "Tigo did not send %s: %s", key, err)
            return
        if key in self._failing and key in self._delivered:
            _LOGGER.info("Tigo sends %s again", key)
        self._failing.discard(key)
        if _has_data(value):
            self._delivered.add(key)
        self._data[key] = value

    async def _get_api(self, query: str) -> Any:
        """GET an API endpoint, logging in again once if the token is rejected."""
        try:
            return await self._get_json(query, await self._cookie_cache.get_auth_header())
        except TigoResponseError as err:
            if err.status not in (401, 403):
                raise
        self._cookie_cache.reset_cookie()
        return await self._get_json(query, await self._cookie_cache.get_auth_header())

    async def _get_json(self, query: str, headers: dict[str, str] | None = None) -> Any:
        """GET a Tigo endpoint and decode its JSON answer, retrying server errors."""
        for attempt in range(1 + RETRIES):
            if attempt:
                await asyncio.sleep(RETRY_DELAY)
            try:
                async with self._session.get(
                    TIGO_URL + query, headers=headers, timeout=REQUEST_TIMEOUT
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    status = response.status
            except (aiohttp.ContentTypeError, ValueError) as err:
                raise TigoResponseError(f"{query} did not return JSON: {err}") from err
            except (aiohttp.ClientError, TimeoutError) as err:
                raise TigoConnectionError(f"{query} failed: {err}") from err
            if status < 500:
                break
        raise TigoResponseError(f"{query} failed with status {status}", status)

    def get_system_id(self) -> str:
        """Return the system id"""
        return self._system_id


# see https://developers.home-assistant.io/docs/integration_fetching_data/
class TigoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Represents Coordinator for this sensor."""

    config_entry: TigoConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: TigoConfigEntry, tigo_data: TigoData
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            # Name of the data. For logging purposes.
            name="TigoCoordinator",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=SCAN_INTERVAL,
        )
        self.tigo_data = tigo_data
        self.panels: list[dict[str, Any]] = []

    async def _async_setup(self) -> None:
        """Load the panels once, before the first update."""
        self.panels = await self._call(self.tigo_data.async_get_panels)

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._call(self.tigo_data.fetch_data)
        # Applies from the next update on
        self.update_interval = (
            FREE_SCAN_INTERVAL if data.get("plan") == "Free" else SCAN_INTERVAL
        )
        return data

    async def _call(self, request: Callable[[], Awaitable[Any]]) -> Any:
        """Run a Tigo request, translating its errors for the coordinator."""
        try:
            return await request()
        except TigoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TigoError as err:
            raise UpdateFailed(str(err)) from err

    def has_reading(self, property: str) -> bool:
        """Return whether any panel has a reading of property."""
        return any(v is not None for v in self.data.get(property, {}).values())

    def get_system_id(self) -> str:
        """Return the system id"""
        return self.tigo_data.get_system_id()
