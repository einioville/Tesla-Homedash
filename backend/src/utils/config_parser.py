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
import shutil
import tempfile
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

logger = logging.getLogger("utils.config_parser")

_env_loaded: bool = False


def default_config_path() -> str:
    '''
    Where the backend's config.json lives when CONFIG_PATH is not set:
    $XDG_CONFIG_HOME (or ~/.config) / Tesla-Homedash / backend_config.json.

    Deliberately the SAME directory the frontend writes its own
    frontend_config.json into, so both halves of the configuration sit together
    rather than in the repo root and an app-name directory nobody can guess.
    CONFIG_PATH still wins when set, so existing deployments are untouched.
    '''
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, "Tesla-Homedash", "backend_config.json")


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

    # Suffix of the rollback copy written by save() before every runtime write.
    # Paired with the __init__ fallback below: a structurally bad write costs one
    # bad boot instead of a systemd restart LOOP.
    BACKUP_SUFFIX = ".bak"

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

    # Spot-price tunables (issue #12). Like the myenergi block, not a REQUIRED_KEY: a
    # gitignored config.json may omit it and the stack must still start. A partial
    # "spotPrice" block is merged over these per-key (see spot_price_config). No secret
    # here — the sähkötin.fi source needs no API key. When "enabled" is false (or the
    # block is absent) the Charging view falls back to the flat electricityPriceEurPerKwh
    # tariff. All-in €/kWh for an hour = (spot + marginCentsPerKwh/100) * (1 + vatPercent/100).
    # Host audio tunables.  Like the trip block this is NOT a required key: an
    # existing config.json will not have it and the stack must still start.
    # outputDevice "" means "leave the host's own default alone", which is not
    # the same as a device literally named "".
    _AUDIO_DEFAULTS = {
        "volumePercent": 60,
        "outputDevice": "",
    }

    _SPOT_PRICE_DEFAULTS = {
        "enabled": True,
        "vatPercent": 25.5,
        "marginCentsPerKwh": 0.0,
        "baseUrl": "https://sahkotin.fi/prices",
    }

    def __init__(self, config_path: str):
        if not config_path:
            raise RuntimeError("Config path is empty or None")
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        # Load the live config, rolling back to the backup copy if it is
        # unusable.  This file is now written at RUNTIME by the Options view
        # (see config_service), and applying a restart-tier setting exits the
        # process for systemd to restart -- so a structurally bad write would
        # otherwise be a restart LOOP.  save() snapshots the previous good file
        # to <path>.bak before every write, so one bad boot rolls back.
        backup_path = config_path + self.BACKUP_SUFFIX
        try:
            self.__data, self.__zone_info = self._load_and_validate(config_path)
        except (ValueError, RuntimeError) as e:
            if not os.path.isfile(backup_path):
                raise
            logger.error(
                "Config at %s is unusable (%s); rolling back to %s",
                config_path, e, backup_path,
            )
            self.__data, self.__zone_info = self._load_and_validate(backup_path)
            # Promote the backup to the live file so the next start is clean and
            # the Options view shows the values actually in effect.
            shutil.copyfile(backup_path, config_path)
            logger.warning("Restored %s from the rollback copy", config_path)

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

    @property
    def path(self) -> str:
        '''
        Absolute path of the live config.json, as resolved from CONFIG_PATH at
        construction.  Reported to the frontend in the CONFIG_SCHEMA document so
        the Options view can show WHICH file its remote half is editing — the
        path is deployment-specific (a worktree copy, the Pi's own), and without
        it the user has no way to tell from the screen.
        '''
        return self.__path

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

    @property
    def spot_price_config(self) -> dict:
        '''Nord Pool spot-price tunables (issue #12), with defaults filled in for any
        missing key so a fully or partially absent "spotPrice" block is safe:
        - enabled: master switch. False -> the Charging view keeps using the flat
          electricityPriceEurPerKwh tariff and no live-price service runs.
        - vatPercent: Finnish electricity VAT applied on top of the wholesale price
          (25.5% since 2024-09-01).
        - marginCentsPerKwh: the seller's fixed margin (c/kWh) added to the raw spot
          price before VAT, approximating a real spot contract's energy price.
        - baseUrl: the sähkötin.fi range endpoint; config-driven so an alternate
          no-key source (e.g. sahkonhintatanaan.fi) can be swapped in without code.'''
        return {**self._SPOT_PRICE_DEFAULTS, **self.__data.get("spotPrice", {})}

    @property
    def audio_config(self) -> dict:
        '''
        Audio block merged over _AUDIO_DEFAULTS, so an omitted or partial "audio"
        block still reports the values actually in effect.
        '''
        return {**self._AUDIO_DEFAULTS, **self.__data.get("audio", {})}

    # ── Loading / validation ───────────────────────────────────────

    @classmethod
    def _load_and_validate(cls, path: str) -> tuple[dict, ZoneInfo]:
        '''
        Parses one config file and validates it well enough to start services:
        valid JSON, every REQUIRED_KEYS entry present, and a resolvable IANA
        timezone.  Returns the parsed document and its pre-built ZoneInfo so
        callers assign both together.  Raises rather than returning a partial
        result -- `__init__` turns a raise on the live file into a rollback.
        Arguments:
            path (str): Absolute path to a JSON config file.
        '''
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Config file contains invalid JSON: {e}") from e

        missing = [k for k in cls.REQUIRED_KEYS if k not in data]
        if missing:
            raise RuntimeError(
                f"Config is missing required keys: {', '.join(missing)}"
            )

        # Build the ZoneInfo once at load time so services can take it directly
        # without each re-parsing the IANA string.  Invalid zone names fail
        # here, not deep inside a service's first scheduler call.
        try:
            zone_info = ZoneInfo(data["timeZone"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(
                f"Invalid timeZone in config: {data['timeZone']!r}"
            ) from e

        return data, zone_info

    # ── Runtime writes (the Options view) ──────────────────────────

    def set(self, key_path: str, value: Any) -> None:
        '''
        Writes one value into the in-memory document by dotted key path
        ("myenergi.pollIntervalIdleSeconds").  Missing intermediate blocks are
        created: the optional "trip" / "myenergi" / "spotPrice" blocks are
        merged over defaults at read time, so a real config.json may legitimately
        not contain them yet.

        The change is visible to every service immediately -- they hold this
        instance by constructor injection and never re-read the file -- but is
        NOT persisted until `save()`.  Does not validate; `config_service`
        validates against the settings schema before calling this.
        Arguments:
            key_path (str): Dotted path into the config document.
            value (Any): JSON-serializable value to store.
        '''
        parts = key_path.split(".")
        target = self.__data
        for part in parts[:-1]:
            existing = target.get(part)
            if not isinstance(existing, dict):
                existing = {}
                target[part] = existing
            target = existing
        target[parts[-1]] = value

        # timeZone is the one key with a derived cached value.  Rebuild it so a
        # live change is consistent even though the APScheduler cron jobs built
        # from it only pick the new zone up on the next process start (which is
        # why the schema marks timeZone as a restart-tier setting).
        if key_path == "timeZone":
            self.__zone_info = ZoneInfo(value)

    def save(self) -> None:
        '''
        Persists the in-memory document to the config path, atomically.

        Two safety steps matter on the embedded target, where the Options view
        can write this file and power can be cut at any moment:
        - the previous on-disk file is copied to `<path>.bak` first, which is
          what `__init__` rolls back to if a write ever produces an unusable
          config (otherwise a restart-tier setting could restart-loop systemd);
        - the new document is written to a temp file in the SAME directory,
          flushed + fsynced, then `os.replace`d onto the real path.  Same
          directory because os.replace is only atomic within a filesystem, and
          fsync because a rename can otherwise land before the data does.
        '''
        directory = os.path.dirname(self.__path) or "."

        if os.path.isfile(self.__path):
            try:
                shutil.copyfile(self.__path, self.__path + self.BACKUP_SUFFIX)
            except OSError as e:
                # A missing rollback copy is worth a loud log but must not block
                # the write -- the user asked for this change.
                logger.warning("Could not write config backup: %s", e)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".config-", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.__data, f, indent=4, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.__path)
        except BaseException:
            # Leave the live config untouched on any failure, including
            # cancellation, and never leak the temp file.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info("Configuration saved to %s", self.__path)
