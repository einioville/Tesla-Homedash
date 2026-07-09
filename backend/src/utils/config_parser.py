'''
Configuration access for the backend.

Two public surfaces:
- `Config` — instantiated once in the starter script with a path to the JSON
  config file.  The whole document is parsed into memory and exposed via
  property accessors and dict-style indexing.  All services receive the
  instance via constructor injection so no service ever re-reads the file.
- `get_env(key)` — module-level accessor for environment variables.
  Loads `.env` on first call.  Kept separate from `Config` because env vars
  and JSON config have different lifecycles and validation needs.
'''
import json
import logging
import os
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

logger = logging.getLogger("utils.config_parser")

_env_loaded: bool = False


def _ensure_env() -> None:
    global _env_loaded
    if not _env_loaded:
        load_dotenv()
        _env_loaded = True


def get_env(key: str) -> str | None:
    '''
    Returns the value of the named environment variable, or None if missing.
    `.env` is loaded once on first call.  Callers that require the variable
    must check for None — this function does not raise.
    Arguments:
        key (str): Environment variable name.
    '''
    _ensure_env()
    value = os.getenv(key)
    if value is None:
        logger.warning("Environment variable not set: %s", key)
    return value


class Config:
    '''
    In-memory configuration loaded once from a JSON file.

    Validated on construction: missing required keys raise immediately so
    services do not start in an unusable state.  Currently read-only; the
    API is shaped to support future writes (`set` + `save`) without
    breaking callers.
    Arguments:
        config_path (str): Absolute path to the JSON config file.
    '''

    REQUIRED_KEYS = (
        "timeZone",
        "tesla data",
        "calculated tesla data",
        "weatherPlace",
        "radioMediaIds",
        "defaultRadioStation",
        "spotifyDeviceId",
        "spotifyRedirectUri",
        "spotifyCachePath",
        "spotifyMarket",
    )

    # Trip-detection tunables. Not a REQUIRED_KEY: the real config.json is
    # gitignored, so absence must degrade to these defaults rather than block
    # startup. A partial "trip" block is merged over them per-key (see
    # trip_config).
    _TRIP_DEFAULTS = {
        "min_stop_minutes": 10,
        "min_trip_distance_km": 0.5,
    }

    # MyEnergi (Zappi) tunables. Like the trip block, not a REQUIRED_KEY: the
    # gitignored real config.json may omit it, and a deployment without a charger
    # must still start. A partial "myenergi" block is merged over these per-key
    # (see myenergi_config). Credentials (hub serial + API key) live in .env, not
    # here — only non-secret tunables belong in config.json.
    _MYENERGI_DEFAULTS = {
        "zappiSerial": "",
        "pollIntervalIdleSeconds": 30,
        "pollIntervalActiveSeconds": 10,
        "minSessionEnergyKwh": 0.5,
        "sessionMergeMinutes": 5,
    }

    def __init__(self, config_path: str):
        if not config_path:
            raise RuntimeError("Config path is empty or None")
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        try:
            with open(config_path, "r") as f:
                self.__data: dict = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Config file contains invalid JSON: {e}") from e

        missing = [k for k in self.REQUIRED_KEYS if k not in self.__data]
        if missing:
            raise RuntimeError(
                f"Config is missing required keys: {', '.join(missing)}"
            )

        # Build the ZoneInfo once at load time so services can take it
        # directly without each re-parsing the IANA string.  Invalid zone
        # names fail here, not deep inside a service's first scheduler call.
        try:
            self.__zone_info = ZoneInfo(self.__data["timeZone"])
        except ZoneInfoNotFoundError as e:
            raise ValueError(
                f"Invalid timeZone in config: {self.__data['timeZone']!r}"
            ) from e

        self.__path = config_path
        logger.info(
            "Configuration loaded from %s (timeZone=%s)",
            config_path, self.__data["timeZone"],
        )

    # ── Generic access ─────────────────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        return self.__data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.__data.get(key, default)

    # ── Typed accessors ────────────────────────────────────────────

    @property
    def timezone(self) -> str:
        '''IANA name as configured (e.g. "Europe/Helsinki").'''
        return self.__data["timeZone"]

    @property
    def zone_info(self) -> ZoneInfo:
        '''Pre-built ZoneInfo for the configured timezone — services that
        need a ZoneInfo for schedulers, datetime arithmetic, or formatting
        should use this rather than constructing their own.'''
        return self.__zone_info

    @property
    def tesla_data(self) -> dict:
        return self.__data["tesla data"]

    @property
    def calculated_tesla_data(self) -> dict:
        return self.__data["calculated tesla data"]

    @property
    def weather_place(self) -> str:
        return self.__data["weatherPlace"]

    @property
    def radio_media_ids(self) -> dict:
        return self.__data["radioMediaIds"]

    @property
    def default_radio_station(self) -> str:
        return self.__data["defaultRadioStation"]

    @property
    def spotify_device_id(self) -> str:
        return self.__data["spotifyDeviceId"]

    @property
    def spotify_redirect_uri(self) -> str:
        return self.__data["spotifyRedirectUri"]

    @property
    def spotify_cache_path(self) -> str:
        return self.__data["spotifyCachePath"]

    @property
    def spotify_market(self) -> str:
        '''ISO 3166-1 alpha-2 country code passed to Spotify playback queries
        (e.g. "FI"). Determines track/episode availability filtering.'''
        return self.__data["spotifyMarket"]

    @property
    def electricity_price_eur_per_kwh(self) -> float | None:
        '''Flat electricity tariff (EUR/kWh) for the Charging view's cost estimate, or
        None when not configured (the cost tile then shows "—"). Optional and non-secret;
        spot/hourly pricing is a separate future feature.'''
        value = self.get("electricityPriceEurPerKwh")
        return float(value) if value is not None else None

    @property
    def trip_config(self) -> dict:
        '''Trip-detection tunables (issue #5), with defaults filled in for any
        missing key so a fully or partially absent "trip" block is safe:
        - min_stop_minutes: a stop in Park shorter than this is merged into the
          surrounding trip rather than ending it.
        - min_trip_distance_km: drive segments shorter than this are discarded
          (e.g. shuffling the car in the driveway).'''
        return {**self._TRIP_DEFAULTS, **self.__data.get("trip", {})}

    @property
    def myenergi_config(self) -> dict:
        '''MyEnergi (Zappi) tunables, with defaults filled in for any missing key so
        a fully or partially absent "myenergi" block is safe:
        - zappiSerial: which Zappi to read when the account has more than one; ""
          lets MyEnergiService auto-select the first discovered Zappi.
        - pollIntervalIdleSeconds / pollIntervalActiveSeconds: cloud poll cadence
          when no car is connected vs. while a session is active.
        - minSessionEnergyKwh: charging sessions that delivered less than this are
          dropped from the list (noise / a car charged away from this Zappi).
        - sessionMergeMinutes: a non-charging gap shorter than this is absorbed into
          the surrounding session rather than splitting it (the charging analogue of
          the trip block's min_stop_minutes).'''
        return {**self._MYENERGI_DEFAULTS, **self.__data.get("myenergi", {})}
