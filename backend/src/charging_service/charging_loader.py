'''
ChargingLoader — detects charging sessions from the database.

Sessions are not tracked live. They are derived on demand by reading the
DetailedChargeState history over a window and segmenting it: a session is a maximal
run where the car reports charging, with short non-charging gaps (< sessionMergeMinutes)
merged in so one plug-in is not split by a momentary pause. Detection uses
DetailedChargeState alone; the charger/vehicle energies are read from stored telemetry
by the ChargingSession objects returned. All InfluxDB access is delegated to the
injected InfluxDBHandler. This is the charging analogue of TripLoader (which segments
on Gear).
'''
import logging
import math

import numpy as np

from .charging_session import CHARGER_ENERGY_ID, ChargingSession, to_flux_time
from .spot_price import price_hourly_energy

logger = logging.getLogger("charging_service.charging_loader")

# Tesla lifetime counters read for the month-to-date consumption figures — the same ids
# and first-of-month baseline DrivenThisMonth uses. Odometer is stored in km (its formula
# is applied on write); LifetimeEnergyUsed is stored raw in kWh.
ODOMETER_ID = "Odometer"
DRIVING_ENERGY_ID = "LifetimeEnergyUsed"


def _is_charging(state: str) -> bool:
    '''
    True when a DetailedChargeState reading means the car is actively charging.

    The teslemetry stream reports this enum with a "DetailedChargeState" prefix (e.g.
    "DetailedChargeStateCharging", "...Complete", "...Disconnected", "...Stopped",
    "...NoPower", "...Starting"), mirroring how Gear is reported as "ShiftState<X>". A
    case-insensitive "charging" substring test is used rather than an exact literal so
    detection survives the prefixed and un-prefixed spellings both; only the actively-
    delivering state contains "charging" (Complete/Stopped/NoPower/Starting do not).
    Arguments:
        state (str): A raw DetailedChargeState reading.
    '''
    return "charging" in state.lower()


def collapse_transitions(history: list) -> list:
    '''
    Collapses consecutive identical DetailedChargeState readings into transitions.
    Logged fields are written on every telemetry event (not only on change), so the
    raw history repeats the held value; only the points where it changes are real
    transitions. Pure logic (no I/O) — the testable core of detection.
    Arguments:
        history (list): [(timestamp_ms, state_str), ...] ascending by time.
    Returns:
        list: The same shape, with runs of identical state reduced to their first point.
    '''
    collapsed = []
    previous = None
    for timestamp_ms, state in history:
        if state != previous:
            collapsed.append((timestamp_ms, state))
            previous = state
    return collapsed


def segment_sessions(
    transitions: list, held_before, start_ms: int, end_ms: int, threshold_ms: int
) -> list:
    '''
    Turns a collapsed DetailedChargeState timeline into charging-session windows. Walks
    the timeline as contiguous [from, to) intervals per held state, treating any
    charging state as active. A non-charging interval shorter than threshold_ms is
    absorbed into the surrounding session (a momentary pause mid-charge); a longer one
    (or the window end) closes the session. Pure logic (no I/O) — the testable core,
    structurally identical to trip_service.segment_trips with the charging predicate in
    place of the Park predicate.
    Arguments:
        transitions (list): Collapsed [(timestamp_ms, state_str), ...].
        held_before (str | None): The state held just before start_ms, or None if
            nothing was logged before the window. A charging held state captures a
            session already under way at the window boundary.
        start_ms (int): Window start, epoch-ms UTC.
        end_ms (int): Window end, epoch-ms UTC.
        threshold_ms (int): Non-charging gap duration at/above which a pause ends a
            session.
    Returns:
        list: [(session_start_ms, session_end_ms, in_progress), ...].
    '''
    if not transitions:
        return []

    # State governing the timeline from the window start. If a value was held before
    # the window, use it; otherwise assume a non-charging sentinel (don't fabricate a
    # session we can't bound).
    start_state = held_before if held_before is not None else ""
    sequence = [(start_ms, start_state)]
    for timestamp_ms, state in transitions:
        if timestamp_ms > start_ms:
            sequence.append((timestamp_ms, state))
    # Re-collapse in case the synthetic start state equals the first transition.
    sequence = collapse_transitions(sequence)

    windows = []
    session_start = None
    last_charge_end = None

    for index, (segment_start, state) in enumerate(sequence):
        segment_end = sequence[index + 1][0] if index + 1 < len(sequence) else end_ms
        is_charging = _is_charging(state)

        if is_charging:
            if session_start is None:
                session_start = segment_start
            last_charge_end = segment_end
        elif session_start is not None:
            # A non-charging interval while a session is open.
            gap_duration = segment_end - segment_start
            if gap_duration >= threshold_ms:
                windows.append((session_start, last_charge_end, False))
                session_start = None
                last_charge_end = None
            # Shorter pause: leave the session open; the next charging segment extends
            # last_charge_end across this absorbed pause.

    if session_start is not None:
        # No long-enough closing pause was seen inside the window. If the last segment
        # was charging reaching the window end, the car is still charging (in progress);
        # otherwise close at the last observed charging.
        in_progress = last_charge_end == end_ms
        windows.append((session_start, last_charge_end, in_progress))

    return windows


def _window_energy(charger, window_start_ms: int, window_end_ms: int) -> float:
    '''
    Computes a session window's charger energy (kWh) from an already-read ChargeAdded
    series, without another query: the SUM OF POSITIVE INCREMENTS of the accumulator
    inside [window_start, window_end]. ChargeAdded ramps up as energy is delivered and
    only drops when the myenergi charger begins a new session, so summing its positive
    steps is the energy actually delivered in the window — robust to the accumulator
    CARRYING a non-zero value into the window (a physical charge whose start Tesla did not
    yet report as "charging", so it falls outside the detected session) or RESETTING
    inside it. The earlier in-window MAX over-counted both cases by the carried/earlier
    peak (e.g. a 16.6 kWh session that had only delivered 5.6 kWh in its window). NaN when
    the series is missing or holds fewer than two samples in the window (nothing to
    difference — e.g. a session at another charger), matching the old NaN so the
    min-energy filter still drops those. The charging analogue of _window_distance.
    Arguments:
        charger (tuple | None): (count, timestamps_ms, values) from
            read_charger_data_property(ChargeAdded, ...), ascending by time, or None.
        window_start_ms (int): Session window start, epoch-ms UTC.
        window_end_ms (int): Session window end, epoch-ms UTC.
    '''
    if charger is None:
        return float("nan")
    count, timestamps, values = charger
    if count == 0 or len(values) == 0:
        return float("nan")
    low = int(np.searchsorted(timestamps, window_start_ms, side="left"))
    high = int(np.searchsorted(timestamps, window_end_ms, side="right"))
    segment = values[low:high]
    if len(segment) < 2:
        return float("nan")
    return float(np.clip(np.diff(segment), 0.0, None).sum())


class ChargingLoader:
    '''
    Detects charging sessions from stored DetailedChargeState history.
    Arguments:
        influx_handler (InfluxDBHandler): Shared data-access layer. Never queries the
            client directly — only its typed read methods.
        config (Config): Provides myenergi_config (minSessionEnergyKwh, sessionMergeMinutes)
            and the flat electricityPriceEurPerKwh fallback tariff.
        spot_provider (SpotPriceProvider | None): Hourly Nord Pool spot pricing for session
            and month cost. Passed into every ChargingSession; None -> flat-tariff pricing.
    '''

    CHARGE_STATE_ID = "DetailedChargeState"

    def __init__(self, influx_handler, config, spot_provider=None):
        self.__influx = influx_handler
        self.__spot_provider = spot_provider
        self.__flat_tariff = config.electricity_price_eur_per_kwh
        myenergi_config = config.myenergi_config
        self.__merge_ms = int(myenergi_config["sessionMergeMinutes"]) * 60 * 1000
        self.__min_energy_kwh = float(myenergi_config["minSessionEnergyKwh"])
        logger.info(
            "ChargingLoader initialized: merge_gap=%s min, min_energy=%.2f kWh, "
            "spot_pricing=%s, flat_tariff=%s",
            myenergi_config["sessionMergeMinutes"], self.__min_energy_kwh,
            self.__spot_provider is not None and self.__spot_provider.enabled,
            "unset" if self.__flat_tariff is None else f"{self.__flat_tariff:.4f}",
        )

    async def list_sessions(self, start_ms: int, end_ms: int) -> list:
        '''
        Returns the charging sessions whose charging falls within [start_ms, end_ms], in
        chronological order. Reads the DetailedChargeState history for the window,
        collapses it to transitions, segments into sessions (merging non-charging gaps
        shorter than the threshold), then drops sessions that delivered less than
        minSessionEnergyKwh at this charger — which also excludes sessions the car ran
        away from this Zappi (no charger energy -> NaN -> dropped) and DC fast charges.
        Arguments:
            start_ms (int): Window start, epoch-ms UTC.
            end_ms (int): Window end, epoch-ms UTC.
        Returns:
            list[ChargingSession]: The detected sessions (each computes its own summary
                on demand), seeded with their charger energy.
        '''
        if end_ms <= start_ms:
            return []

        start_iso = to_flux_time(start_ms)
        end_iso = to_flux_time(end_ms)

        history = await self.__influx.read_value_string_history(
            self.CHARGE_STATE_ID, start_iso, end_iso
        )
        if not history:
            return []

        transitions = collapse_transitions(history)
        # The state held just before the window: lets a session already under way at the
        # window boundary be recognised (same idea as the trip/History boundary-fill).
        held_before = await self.__influx.read_last_string_before(
            self.CHARGE_STATE_ID, start_iso
        )

        windows = segment_sessions(transitions, held_before, start_ms, end_ms, self.__merge_ms)
        if not windows:
            return []

        # Read the whole window's ChargeAdded ONCE and compute each session's delivered
        # energy from the in-memory series — a single query regardless of session count,
        # mirroring how TripLoader reads Odometer once. Each ChargingSession is seeded
        # with its energy so a later charger_kwh()/summary() reuses it without a re-read.
        charger = await self.__influx.read_charger_data_property(
            CHARGER_ENERGY_ID, start_iso, end_iso
        )

        sessions = []
        for window_start, window_end, in_progress in windows:
            charger_kwh = _window_energy(charger, window_start, window_end)
            # Drop sub-threshold and no-charger-data sessions: the losses view is about
            # THIS charger, so a session with no comparable Zappi energy (charged
            # elsewhere / DC) or a trivial top-up is not listed. NaN < threshold is
            # False, so the explicit isnan check is what excludes no-charger sessions.
            if math.isnan(charger_kwh) or charger_kwh < self.__min_energy_kwh:
                logger.debug(
                    "Discarding session (charger=%s kWh < %.2f): start=%s",
                    "n/a" if math.isnan(charger_kwh) else f"{charger_kwh:.3f}",
                    self.__min_energy_kwh, window_start,
                )
                continue
            session = ChargingSession(
                self.__influx, window_start, window_end, in_progress,
                spot_provider=self.__spot_provider, flat_tariff=self.__flat_tariff,
            )
            session.seed_charger_kwh(charger_kwh)
            # Seed the window's ChargeAdded slice from the bulk read too, so the session's
            # cost path buckets energy by hour without a second query (mirrors the scalar
            # seed above; both come from the one read this method already did).
            self.__seed_series(session, charger, window_start, window_end)
            sessions.append(session)

        logger.info(
            "Detected %d charging session(s) in [%s, %s]", len(sessions), start_ms, end_ms
        )
        return sessions

    def __seed_series(self, session, charger, window_start_ms: int, window_end_ms: int) -> None:
        '''
        Slices the window's ChargeAdded samples out of the bulk-read series and seeds them
        onto the session, so its cost path buckets delivered energy by hour without a
        second query. A no-op when no charger series was read (a priced session then reads
        its own window). Uses the same left/right searchsorted bounds as _window_energy so
        the seeded slice matches the seeded scalar energy exactly.
        Arguments:
            session (ChargingSession): The session to seed.
            charger (tuple | None): (count, timestamps_ms, values) bulk read, or None.
            window_start_ms (int): Session window start, epoch-ms UTC.
            window_end_ms (int): Session window end, epoch-ms UTC.
        '''
        if charger is None:
            return
        _count, timestamps, values = charger
        low = int(np.searchsorted(timestamps, window_start_ms, side="left"))
        high = int(np.searchsorted(timestamps, window_end_ms, side="right"))
        session.seed_charger_series(timestamps[low:high], values[low:high])

    async def load_summary(self, start_ms: int, end_ms: int) -> dict | None:
        '''
        Computes one session's loss breakdown for the detail panel. The frontend already
        knows the session's [start_ms, end_ms] from a prior list_sessions reply, so a
        ChargingSession is constructed directly over that window and asked for its
        summary — no re-detection. Every metric degrades to NaN when its source series
        is missing, so a partial-data session still yields a record.
        Arguments:
            start_ms (int): The session's start (its natural key), epoch-ms UTC.
            end_ms (int): The session's end, epoch-ms UTC.
        Returns:
            dict | None: ChargingSession.summary() for the window, or None for an
                inverted window.
        '''
        if end_ms <= start_ms:
            return None
        session = ChargingSession(
            self.__influx, start_ms, end_ms,
            spot_provider=self.__spot_provider, flat_tariff=self.__flat_tariff,
        )
        return await session.summary()

    async def get_power_history(self, data_property_id: str, time_start: str, time_end: str):
        '''
        Reads a logged charger power series (e.g. GridPower / ChargePower) raw over a
        window, for the Charging view's past-hour graphs — a thin pass-through to the
        InfluxDBHandler's myenergi_data read, kept here so the charger-history request
        handler has one charging-data entry point (the loader owns all myenergi_data
        access). Raises ValueError on a malformed id (the read's _SAFE_ID guard) — the
        handler replies status=0.
        Arguments:
            data_property_id (str): The charger property id (InfluxDB "id" tag).
            time_start (str): Flux range start (relative like "-1h" or RFC3339).
            time_end (str): Flux range stop ("now()" or RFC3339).
        Returns:
            tuple | None: (count, timestamps_ms, values) ascending, or None.
        '''
        return await self.__influx.read_charger_data_property(
            data_property_id, time_start, time_end
        )

    async def month_summary(self, start_ms: int, end_ms: int) -> dict:
        '''
        Aggregates the month-to-date charging stats for the Charging view. Sums the
        myenergi-detected sessions in [start_ms, end_ms] (via list_sessions + each
        session's summary()), so charger vs car energy stay apples-to-apples over the same
        session set. Distance and driving energy are the tesla lifetime counters' month
        deltas (Odometer / LifetimeEnergyUsed, the same first-of-month baseline
        DrivenThisMonth uses); the home grid import is the per-hour integral of positive
        GridPower, summed. Both cost fields are computed here (the loader owns the spot
        provider + flat tariff): charging_cost_eur = Σ per-session spot-priced cost;
        home_cost_eur = Σ hour_kwh × that hour's spot price. Every field degrades to NaN
        when its source is missing, so a partial-data month still yields a well-formed record.
        Arguments:
            start_ms (int): Month start (1st, 00:00 local), epoch-ms UTC.
            end_ms (int): Now, epoch-ms UTC.
        Returns:
            dict: The month aggregate (energy, waste, efficiency, consumption/km,
                sessions, charge time, cost, home import + cost), each value a float
                (may be NaN).
        '''
        sessions = await self.list_sessions(start_ms, end_ms)

        charger_sum = 0.0
        battery_sum = 0.0
        battery_count = 0
        charge_time_s = 0.0
        cost_sum = 0.0
        cost_count = 0
        for session in sessions:
            summary = await session.summary()
            # list_sessions already dropped NaN-charger sessions, so charger_kwh is real.
            charger_sum += summary["charger_kwh"]
            battery_kwh = summary["battery_kwh"]
            if not math.isnan(battery_kwh):
                battery_sum += battery_kwh
                battery_count += 1
            charge_time_s += summary["duration_s"]
            # Month charging cost = Σ per-session spot-priced cost (each session already
            # priced its energy per hour). A NaN session cost (unpriceable) is skipped so
            # one gap doesn't void the month, matching how car_kwh handles missing battery.
            session_cost = summary["cost_eur"]
            if not math.isnan(session_cost):
                cost_sum += session_cost
                cost_count += 1

        session_count = len(sessions)
        charger_kwh = charger_sum if session_count > 0 else float("nan")
        # Car energy sums only sessions that had a battery reading, so a rare missing
        # EnergyRemaining slightly under-counts rather than voiding the whole month.
        car_kwh = battery_sum if battery_count > 0 else float("nan")
        wasted_kwh = (
            charger_kwh - car_kwh
            if (not math.isnan(charger_kwh) and not math.isnan(car_kwh))
            else float("nan")
        )
        efficiency_pct = (
            car_kwh / charger_kwh * 100.0
            if (not math.isnan(car_kwh) and not math.isnan(charger_kwh) and charger_kwh > 0)
            else float("nan")
        )

        now_iso = to_flux_time(end_ms)
        km_month = await self.__month_delta(ODOMETER_ID, now_iso)
        driving_kwh = await self.__month_delta(DRIVING_ENERGY_ID, now_iso)
        car_wh_per_km = (
            driving_kwh * 1000.0 / km_month
            if (not math.isnan(driving_kwh) and not math.isnan(km_month) and km_month > 0)
            else float("nan")
        )
        charger_wh_per_km = (
            charger_kwh * 1000.0 / km_month
            if (not math.isnan(charger_kwh) and not math.isnan(km_month) and km_month > 0)
            else float("nan")
        )

        charging_cost_eur = cost_sum if cost_count > 0 else float("nan")

        # Whole-home grid import + its cost, priced per UTC hour. One hourly read yields
        # both the total (Σ hours) and the cost (Σ hour_kwh × that hour's spot price, per-
        # hour flat-tariff fallback) — no separate month integral.
        hourly_home = await self.__influx.read_grid_import_kwh_hourly(start_ms, end_ms)
        if hourly_home:
            home_grid_kwh = float(sum(hourly_home.values()))
            home_prices: dict = {}
            if self.__spot_provider is not None and self.__spot_provider.enabled:
                home_prices = await self.__spot_provider.prices_for_range(start_ms, end_ms)
            home_cost_eur = price_hourly_energy(hourly_home, home_prices, self.__flat_tariff)
        else:
            home_grid_kwh = float("nan")
            home_cost_eur = float("nan")

        logger.info(
            "Month charging summary: sessions=%d charger=%s kWh car=%s kWh eff=%s%% "
            "charging_cost=%s home=%s kWh home_cost=%s",
            session_count,
            "n/a" if math.isnan(charger_kwh) else f"{charger_kwh:.2f}",
            "n/a" if math.isnan(car_kwh) else f"{car_kwh:.2f}",
            "n/a" if math.isnan(efficiency_pct) else f"{efficiency_pct:.1f}",
            "n/a" if math.isnan(charging_cost_eur) else f"{charging_cost_eur:.2f}€",
            "n/a" if math.isnan(home_grid_kwh) else f"{home_grid_kwh:.1f}",
            "n/a" if math.isnan(home_cost_eur) else f"{home_cost_eur:.2f}€",
        )
        return {
            "charger_kwh": charger_kwh,
            "car_kwh": car_kwh,
            "wasted_kwh": wasted_kwh,
            "efficiency_pct": efficiency_pct,
            "car_wh_per_km": car_wh_per_km,
            "charger_wh_per_km": charger_wh_per_km,
            "driving_kwh": driving_kwh,
            "km_month": km_month,
            "session_count": float(session_count),
            "total_charge_s": charge_time_s,
            "charging_cost_eur": charging_cost_eur,
            "home_grid_kwh": home_grid_kwh,
            "home_cost_eur": home_cost_eur,
        }

    async def __month_delta(self, data_property_id: str, now_iso: str) -> float:
        '''
        Month-to-date delta of a tesla lifetime counter: its last value up to now minus
        its first value since the 1st of the month (the baseline DrivenThisMonth uses).
        NaN if either endpoint is missing (InfluxDB down / not logged this month).
        Arguments:
            data_property_id (str): The counter's id (Odometer / LifetimeEnergyUsed).
            now_iso (str): The window end as an RFC3339 string (Flux stop).
        '''
        baseline = await self.__influx.read_first_value_month(data_property_id)
        latest = await self.__influx.read_last_value_before(data_property_id, now_iso)
        if baseline is None or latest is None:
            return float("nan")
        return float(latest) - float(baseline)
