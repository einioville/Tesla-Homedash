'''
SpotPriceProvider — Nord Pool FI spot electricity price, fetched on demand (issue #12).

The Charging view prices energy against the actual hourly Nord Pool spot price for the hour
each kWh was drawn, instead of a single flat tariff. Prices come from a free no-key Finnish
API (sähkötin.fi), which serves *historical* hourly FI-zone prices — so a charging session
from days/weeks ago can be priced retroactively without us logging prices ourselves.

This module is the shared pricing core: it fetches, caches, and converts prices. Two consumers
use it — the on-demand ChargingSession / ChargingLoader (per-session + month cost) and the
always-on SpotPriceService (the live current-price tile). It owns no protocol/serialization.

Correctness model:
  - Every price and every energy bucket is keyed by UTC hour-start ms. Nord Pool hours are
    fixed UTC instants; keying by UTC (never local wall-clock) keeps the two DST switch days
    (23h/25h) correct.
  - The API returns raw wholesale €/MWh. The all-in estimate the tiles use is
    (spot_€/kWh + margin_€/kWh) * (1 + VAT). VAT and margin come from config.spot_price_config.
  - Past hours are immutable, so once fetched a raw price is cached for the process lifetime.
    The VAT/margin conversion is applied on read, so a config change never needs a cache flush.
'''
import asyncio
import logging
import math
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger("charging_service.spot_price")

_HOUR_MS = 3_600_000
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)


def _hour_floor_ms(timestamp_ms: int) -> int:
    '''Floors an epoch-ms instant to the start of its UTC hour (epoch-ms).'''
    return (int(timestamp_ms) // _HOUR_MS) * _HOUR_MS


def _to_iso_z(timestamp_ms: int) -> str:
    '''Epoch-ms -> the RFC3339 'Z' string sähkötin expects for its start/end params.'''
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_iso_z(value: str) -> int:
    '''
    Parses an RFC3339 'Z' timestamp (e.g. "2026-07-07T00:00:00.000Z") to epoch-ms.
    Arguments:
        value (str): The ISO-8601 UTC timestamp from a price entry's "date" field.
    '''
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def price_hourly_energy(
    hourly_kwh: dict[int, float],
    prices: dict[int, float],
    flat_fallback: float | None = None,
) -> float:
    '''
    Costs a per-UTC-hour energy map against a per-hour all-in price map, falling back to a
    flat €/kWh tariff for any hour with no spot price. This is the single place the
    energy×price dot-product lives, shared by the per-session and month cost paths.
    Returns the total € cost, or NaN when nothing could be priced (no spot price for any
    hour and no flat fallback). An hour whose energy has neither a spot price nor a flat
    fallback is dropped (its energy goes uncounted) rather than voiding the whole total.
    Arguments:
        hourly_kwh (dict[int, float]): {utc_hour_start_ms: energy_kwh}. NaN energy skipped.
        prices (dict[int, float]): {utc_hour_start_ms: all_in_eur_per_kwh}.
        flat_fallback (float | None): Flat €/kWh used when an hour has no spot price, or None.
    '''
    total = 0.0
    priced_any = False
    for hour, kwh in hourly_kwh.items():
        if kwh is None or math.isnan(kwh):
            continue
        price = prices.get(hour)
        if price is None:
            price = flat_fallback
        if price is None:
            continue
        total += kwh * price
        priced_any = True
    return total if priced_any else float("nan")


class SpotPriceProvider:
    '''
    Fetches, caches, and converts Nord Pool FI spot prices.

    Constructed unconditionally (independent of the myenergi charger — the live price tile
    should show even with no Zappi). When spot_price_config["enabled"] is false every method
    degrades to "no price", so callers fall back to the flat tariff.
    Arguments:
        config (Config): Shared configuration; spot_price_config supplies enabled, vatPercent,
            marginCentsPerKwh, and baseUrl.
    '''

    def __init__(self, config):
        cfg = config.spot_price_config
        self.__enabled = bool(cfg["enabled"])
        self.__base_url = str(cfg["baseUrl"])
        self.__vat_multiplier = 1.0 + float(cfg["vatPercent"]) / 100.0
        self.__margin_eur_per_kwh = float(cfg["marginCentsPerKwh"]) / 100.0
        # UTC-hour-start ms -> raw spot €/kWh (no VAT/margin). Past hours are immutable, so a
        # cache hit is never re-fetched; the all-in conversion is applied on read.
        self.__raw_cache: dict[int, float] = {}

    @property
    def enabled(self) -> bool:
        '''True when spot pricing is switched on in config.'''
        return self.__enabled

    def _all_in(self, raw_eur_per_kwh: float) -> float:
        '''Applies seller margin then VAT to a raw wholesale €/kWh price.'''
        return (raw_eur_per_kwh + self.__margin_eur_per_kwh) * self.__vat_multiplier

    async def prices_for_range(self, start_ms: int, end_ms: int) -> dict[int, float]:
        '''
        Returns {utc_hour_start_ms: all_in_eur_per_kwh} for every whole UTC hour the window
        [start_ms, end_ms] touches (inclusive of the hour containing end). Empty when spot
        pricing is disabled, the window is inverted, or the fetch yields nothing. Fetches
        the span (once) only if some hour is not already cached.
        Arguments:
            start_ms (int): Window start, epoch-ms UTC.
            end_ms (int): Window end, epoch-ms UTC.
        '''
        if not self.__enabled or end_ms <= start_ms:
            return {}
        first = _hour_floor_ms(start_ms)
        last = _hour_floor_ms(end_ms - 1)
        await self.__ensure_cached(first, last)
        result: dict[int, float] = {}
        hour = first
        while hour <= last:
            raw = self.__raw_cache.get(hour)
            if raw is not None:
                result[hour] = self._all_in(raw)
            hour += _HOUR_MS
        return result

    async def price_at(self, timestamp_ms: int) -> float | None:
        '''
        Returns the all-in €/kWh price for the hour containing timestamp_ms, or None when
        pricing is disabled or the hour has no price. Fetches the hour if not cached.
        Arguments:
            timestamp_ms (int): The instant to price, epoch-ms UTC.
        '''
        if not self.__enabled:
            return None
        hour = _hour_floor_ms(timestamp_ms)
        await self.__ensure_cached(hour, hour)
        raw = self.__raw_cache.get(hour)
        return self._all_in(raw) if raw is not None else None

    def raw_price_at(self, timestamp_ms: int) -> float | None:
        '''
        Returns the cached *raw* (no VAT/margin) €/kWh for the hour containing timestamp_ms
        without fetching, or None if not cached. Used by the live broadcast, which pairs the
        raw wholesale price with the all-in estimate.
        Arguments:
            timestamp_ms (int): The instant to look up, epoch-ms UTC.
        '''
        return self.__raw_cache.get(_hour_floor_ms(timestamp_ms))

    async def __ensure_cached(self, first_hour_ms: int, last_hour_ms: int) -> None:
        '''
        Ensures every whole UTC hour in [first_hour_ms, last_hour_ms] is present in the
        cache, fetching the whole span in one request when any hour is missing. A fully
        cached span (all past hours) skips the network entirely; a span with an unpublished
        or not-yet-fetched hour (today/tomorrow) triggers one fetch.
        Arguments:
            first_hour_ms (int): First UTC hour-start to cover, epoch-ms.
            last_hour_ms (int): Last UTC hour-start to cover (inclusive), epoch-ms.
        '''
        missing = any(
            h not in self.__raw_cache
            for h in range(first_hour_ms, last_hour_ms + _HOUR_MS, _HOUR_MS)
        )
        if not missing:
            return
        await self.__fetch_and_cache(first_hour_ms, last_hour_ms + _HOUR_MS)

    async def __fetch_and_cache(self, start_ms: int, end_ms: int) -> None:
        '''
        Fetches sähkötin's price range for [start_ms, end_ms) and merges it into the cache.
        Network/decoding failures are logged and swallowed — the caller then prices with
        whatever is already cached (possibly nothing), never crashing the request.
        Arguments:
            start_ms (int): Fetch window start, epoch-ms UTC.
            end_ms (int): Fetch window end (exclusive), epoch-ms UTC.
        '''
        params = {"start": _to_iso_z(start_ms), "end": _to_iso_z(end_ms)}
        try:
            async with aiohttp.ClientSession(timeout=_FETCH_TIMEOUT) as session:
                async with session.get(self.__base_url, params=params) as resp:
                    resp.raise_for_status()
                    # sähkötin serves JSON without a JSON content-type on some paths;
                    # content_type=None disables aiohttp's strict mimetype check.
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.warning(
                "Spot price fetch failed for %s..%s: %s: %s",
                params["start"], params["end"], type(e).__name__, e,
            )
            return
        self.__ingest(data)

    def __ingest(self, data) -> None:
        '''
        Merges a sähkötin response ({"prices": [{"date": "…Z", "value": €/MWh}, …]}) into
        the cache. Each entry is floored to its UTC hour and, if several entries share an
        hour (a 15-minute-resolution response), averaged — so the cache always holds one
        raw €/kWh per hour regardless of the API's resolution.
        Arguments:
            data: The decoded JSON body (expected dict with a "prices" list).
        '''
        prices = data.get("prices") if isinstance(data, dict) else None
        if not prices:
            logger.debug("Spot price response carried no 'prices' array")
            return
        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for entry in prices:
            try:
                hour = _hour_floor_ms(_parse_iso_z(entry["date"]))
                eur_per_mwh = float(entry["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isnan(eur_per_mwh):
                continue
            sums[hour] = sums.get(hour, 0.0) + eur_per_mwh
            counts[hour] = counts.get(hour, 0) + 1
        for hour, total in sums.items():
            self.__raw_cache[hour] = (total / counts[hour]) / 1000.0  # €/MWh -> €/kWh
        if sums:
            logger.info("Cached %d hourly spot prices", len(sums))
