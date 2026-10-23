from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
import logging
import re
import numpy as np
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ..utils.config_parser import get_env

_SAFE_ID = re.compile(r'^[A-Za-z0-9_\-]+$')

_HOUR_MS = 3_600_000

logger = logging.getLogger("influxdb_service.influxdb_handler")


def to_flux_time(timestamp_ms: int) -> str:
    '''
    Converts an epoch-ms instant to the RFC3339 "Z" string a Flux range() takes:
    whole seconds print no fraction, anything else six digits.
    Arguments:
        timestamp_ms (int): Milliseconds since the Unix epoch (UTC).
    '''
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def integrate_power_series_hourly(timestamps_ms, values) -> dict:
    '''
    Trapezoidally integrates a power (W) time series into energy (kWh) bucketed by UTC hour.
    Each sample interval is split at hour boundaries and the (linearly interpolated) power
    at each slice's endpoints is trapezoided, so energy lands in the hour it was actually
    drawn — the per-hour analogue of Flux integral(unit: 1h). Negative power (grid export)
    is clamped to zero first, so only imported energy ("energy bought") is counted. Pure/
    testable: no I/O. Fewer than two samples -> {}.
    Arguments:
        timestamps_ms: Ascending epoch-ms sample times (int64 array/sequence).
        values: Power in W at each sample (float array/sequence), same length.
    Returns:
        dict: {utc_hour_start_ms: energy_kwh} for every hour the series spans.
    '''
    ts = np.asarray(timestamps_ms, dtype=np.int64)
    clamped = np.clip(np.asarray(values, dtype=np.float64), 0.0, None)
    n = len(ts)
    result: dict[int, float] = {}
    for i in range(n - 1):
        t0 = int(ts[i])
        t1 = int(ts[i + 1])
        if t1 <= t0:
            continue
        p0 = float(clamped[i])
        p1 = float(clamped[i + 1])
        span = t1 - t0
        a = t0
        while a < t1:
            hour = (a // _HOUR_MS) * _HOUR_MS
            b = min(t1, hour + _HOUR_MS)
            # Power linearly interpolated at the slice endpoints, then trapezoided
            # (exact for a linear segment). W * (ms / 3.6e6) -> Wh; /1000 -> kWh.
            pa = p0 + (p1 - p0) * (a - t0) / span
            pb = p0 + (p1 - p0) * (b - t0) / span
            wh = (pa + pb) / 2.0 * (b - a) / _HOUR_MS
            result[hour] = result.get(hour, 0.0) + wh / 1000.0
            a = b
    return result


class InfluxDBHandler:
    def __init__(self, url: str, org: str, zone_info: ZoneInfo):
        self.__url = url
        self.__token = get_env("INFLUX_TOKEN")
        self.__org = org
        self.__client = InfluxDBClientAsync(url=url, token=self.__token, org=org)
        self.__bucket = "data"
        # Day/month boundary queries must align with the configured timezone
        # used by the midnight snapshot job, not the host OS local time.
        self.__timezone = zone_info
        # Epoch ms of the last request InfluxDB answered, for the status card.
        self.__last_ok_ms: int | None = None
        logger.info(
            "InfluxDB handler initialized: url=%s, org=%s, tz=%s",
            url, org, zone_info.key,
        )

    async def connected(self) -> bool:
        return await self.__client.ping()

    async def health(self) -> dict:
        '''
        The database's standing for the Järjestelmän tila card: a real ping, so
        the status probe registry awaits it under its timeout.
        '''
        ok = await self.connected()
        if ok:
            self.__answered()
        return {"state": "ok" if ok else "error",
                "detail": "Yhteys auki" if ok else "Ei yhteyttä tietokantaan",
                "config": [["Osoite", self.__url], ["Organisaatio", self.__org],
                           ["Bucket", self.__bucket]],
                "last_ok_ms": self.__last_ok_ms}

    def __answered(self) -> None:
        '''Notes that InfluxDB answered a request just now.'''
        self.__last_ok_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    async def __single_table(self, query: str, failure: str):
        '''
        Runs one read and returns its result table, or None when InfluxDB is
        unreachable, the query fails or nothing matched: a read degrades to "no
        data" rather than propagating.  A second table raises — every read here is
        shaped to produce one.
        Arguments:
            query (str): The Flux query.
            failure (str): The warning line's text, e.g. "history read failed for Odometer".
        '''
        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            logger.warning("InfluxDB %s: %s: %s", failure, type(e).__name__, e)
            return None
        self.__answered()

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        return result[0]

    @staticmethod
    def __as_series(table) -> tuple | None:
        '''
        Converts a table's non-null records into (count, timestamps_ms (int64),
        values (float64)), or None when no record has a value.
        Arguments:
            table (FluxTable): A numeric read's result table.
        '''
        records = [r for r in table if r.get_value() is not None]
        if not records:
            return None

        timestamps = np.array(
            [record.get_time().timestamp() * 1000 for record in records], dtype=np.int64
        )
        values = np.array([record.get_value() for record in records], dtype=np.float64)

        return len(values), timestamps, values

    async def read_tesla_data_property(
        self,
        data_property_id: str,
        time_start: str,
        time_end: str,
    ) -> tuple:
        '''
        Reads a logged numeric property's raw history from InfluxDB over a time
        range.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            time_start (str): Flux range start (relative like "-1h" or RFC3339).
            time_end (str): Flux range stop ("now()" or RFC3339).
        Returns:
            tuple | None: (count, timestamps_ms (int64), values (float64)), or None
                if InfluxDB is unreachable / the query fails / there is no data.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        # Graphable properties store their value under the "value_float" field;
        # restricting to it keeps a single result table and excludes any
        # non-numeric fields that might share the id tag.
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
        query += '\n  |> keep(columns: ["_time", "_value"])'

        table = await self.__single_table(
            query, f"history read failed for {data_property_id}")
        if table is None:
            return None
        logger.debug("Query returned results for property: %s", data_property_id)
        return self.__as_series(table)

    async def read_charger_data_property(
        self, data_property_id: str, time_start: str, time_end: str
    ) -> tuple | None:
        '''
        Reads a logged charger (myenergi) numeric property's raw history over a time
        range — the charger analogue of read_tesla_data_property, over a different
        measurement: myenergi charger points live under "myenergi_data" (written
        by MyEnergiService), kept separate from "tesla_data" but queryable over the same
        time window so a charging session's charger energy can be joined to the vehicle's
        telemetry. Values come back raw and ascending; ChargeAdded's callers sum its
        in-window positive increments.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            time_start (str): Flux range start (relative like "-1d" or RFC3339).
            time_end (str): Flux range stop ("now()" or RFC3339).
        Returns:
            tuple | None: (count, timestamps_ms (int64), values (float64)), or None if
                InfluxDB is unreachable / the query fails / there is no data in range.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "myenergi_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> sort(columns: ["_time"])'

        table = await self.__single_table(
            query, f"charger history read failed for {data_property_id}")
        return None if table is None else self.__as_series(table)

    async def read_grid_import_kwh_hourly(self, start_ms: int, end_ms: int) -> dict | None:
        '''
        Reads the logged grid power (myenergi "GridPower", W) over [start_ms, end_ms] and
        integrates it into imported energy (kWh) bucketed by UTC hour — the per-hour input
        the spot-price cost path needs (each hour's kWh × that hour's price). Reuses the
        raw read_charger_data_property("GridPower", …) read and integrates in Python
        (integrate_power_series_hourly), rather than a Flux windowed integral(): it reuses
        the existing safe read and keeps the bucketing unit-testable. Only import (positive
        power) is counted, so grid export doesn't subtract. The month total is just
        sum(result.values()). Degrades to None on an unreachable/failed query or a window
        with fewer than two samples.
        Arguments:
            start_ms (int): Window start, epoch-ms UTC.
            end_ms (int): Window end, epoch-ms UTC.
        Returns:
            dict | None: {utc_hour_start_ms: kwh}, or None.
        '''
        result = await self.read_charger_data_property(
            "GridPower", to_flux_time(start_ms), to_flux_time(end_ms)
        )
        if result is None:
            return None
        count, timestamps, values = result
        if count < 2:
            return None
        return integrate_power_series_hourly(timestamps, values)

    async def read_last_value_before(
        self, data_property_id: str, stop_time: str
    ) -> float | None:
        '''
        Reads the most recent stored value of a property strictly before a given
        time — used by the History path to draw a flat held line for a window in
        which nothing was logged (a value that stayed constant), and by the charging
        month summary for a lifetime counter's latest value. Scans from the
        start of history up to stop_time and takes the last record, so a value held
        constant for days is still found.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            stop_time (str): Flux range stop (RFC3339 or relative). Interpolated
                into the query, so it must be code-generated (never client input),
                exactly like time_start/time_end in read_tesla_data_property.
        Returns:
            float | None: The held value before stop_time, or None if InfluxDB is
                unreachable / the query fails / the property was never logged before.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: 0, stop: {stop_time})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> last()'

        # A failure reads as "no prior value", so an empty-window history read stays
        # empty ("Ei dataa") rather than fabricating a line.
        table = await self.__single_table(
            query, f"last-value-before read failed for {data_property_id}")
        if table is None or not table.records:
            return None

        value = table.records[0].get_value()
        if value is None:
            return None
        logger.debug("Last value before %s for %s: %s", stop_time, data_property_id, value)
        return float(value)

    async def read_value_string_history(
        self, data_property_id: str, time_start: str, time_end: str
    ) -> list | None:
        '''
        Reads a logged string (enum) property's history over a time range, ascending
        by time — the Gear and DetailedChargeState timelines that trip and charging
        detection segment on. Records are returned raw, with no de-duplication: logged
        fields are written on every telemetry event (not only on change), so the caller
        collapses consecutive identical readings (utils.timeline.collapse_transitions).
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            time_start (str): Flux range start (relative like "-1d" or RFC3339).
            time_end (str): Flux range stop ("now()" or RFC3339).
        Returns:
            list | None: [(timestamp_ms (int), value (str)), ...] in ascending time
                order, or None if InfluxDB is unreachable / the query fails / there
                is no data in the range.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        # String enums (Gear, BMSState, DetailedChargeState, ...) store their value
        # under the "value_string" field.
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_string")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> sort(columns: ["_time"])'

        table = await self.__single_table(
            query, f"string-history read failed for {data_property_id}")
        if table is None:
            return None

        records = [r for r in table if r.get_value() is not None]
        if not records:
            return None

        return [
            (int(record.get_time().timestamp() * 1000), str(record.get_value()))
            for record in records
        ]

    async def read_last_string_before(
        self, data_property_id: str, stop_time: str
    ) -> str | None:
        '''
        Reads the most recent stored string value of a property strictly before a
        given time — used by trip and charging detection to learn the held Gear /
        DetailedChargeState at the start of a query window, so a trip or session
        already under way at the window boundary is still recognised. The string
        analogue of read_last_value_before.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            stop_time (str): Flux range stop (RFC3339 or relative). Interpolated into
                the query, so it must be code-generated (never client input).
        Returns:
            str | None: The held string before stop_time, or None if InfluxDB is
                unreachable / the query fails / the property was never logged before.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: 0, stop: {stop_time})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_string")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> last()'

        table = await self.__single_table(
            query, f"last-string-before read failed for {data_property_id}")
        if table is None or not table.records:
            return None

        value = table.records[0].get_value()
        if value is None:
            return None
        return str(value)

    async def read_location_history(
        self, time_start: str, time_end: str
    ) -> list | None:
        '''
        Reads every GPS fix logged inside a time window, ascending by time — the full
        path of a trip, drawn as the coloured route on the Trips-view map. Location is
        a value_dict stored as two separate fields "latitude" and "longitude" under the
        same id="Location" tag, so the two fields are pivoted back into one row per
        fix. Rows missing either coordinate are skipped.
        Arguments:
            time_start (str): Flux range start (RFC3339 or relative). Code-generated.
            time_end (str): Flux range stop (RFC3339 or relative). Code-generated.
        Returns:
            list | None: [(timestamp_ms (int), latitude (float), longitude (float)),
                ...] ascending, or None if InfluxDB is unreachable / the query fails /
                no fix was logged in the window.
        '''
        # "Location" is a fixed literal id (not caller input), so no _SAFE_ID needed.
        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += '\n  |> filter(fn: (r) => r["id"] == "Location")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "latitude" or r["_field"] == "longitude")'
        query += '\n  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        query += '\n  |> keep(columns: ["_time", "latitude", "longitude"])'
        query += '\n  |> sort(columns: ["_time"])'

        table = await self.__single_table(query, "location-history read failed")
        if table is None:
            return None

        path = []
        for record in table.records:
            latitude = record.values.get("latitude")
            longitude = record.values.get("longitude")
            if latitude is None or longitude is None:
                continue
            path.append(
                (int(record.get_time().timestamp() * 1000), float(latitude), float(longitude))
            )
        if not path:
            return None
        return path

    async def write_tesla_data(self, points: list) -> None:
        valid_points = [p for p in points if p is not None]
        if len(valid_points) == 0:
            return
        try:
            await self.__client.write_api().write(bucket=self.__bucket, record=valid_points)
            self.__answered()
            logger.info("Wrote %d points to InfluxDB", len(valid_points))
        except Exception as e:
            logger.error("Failed to write points to InfluxDB: %s", e)
            raise

    async def write_charger_data(self, points: list) -> None:
        '''
        Writes myenergi charger points to InfluxDB. The same write as write_tesla_data
        (the measurement is baked into each Point by the caller — MyEnergiService builds
        Point("myenergi_data") records), except that a failed write is logged and
        swallowed here — unlike write_tesla_data (whose raise lets Vehicle decide), a
        charger write must never break the poll loop / live broadcast, so it degrades
        quietly.
        Arguments:
            points (list): InfluxDB Point objects (or None entries, which are dropped).
        '''
        valid_points = [p for p in points if p is not None]
        if len(valid_points) == 0:
            return
        try:
            await self.__client.write_api().write(bucket=self.__bucket, record=valid_points)
            self.__answered()
            logger.info("Wrote %d charger points to InfluxDB", len(valid_points))
        except Exception as e:
            logger.error("Failed to write charger points to InfluxDB: %s", e)

    async def read_first_value_day(self, data_property_id: str):
        '''
        The first value a property logged today (from local midnight in the
        configured timezone), the baseline of a per-day calculated field.  None
        when InfluxDB is unreachable or nothing was logged yet, so
        CalculatedVehicleDataProperty falls back to the live value.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag).
        '''
        return await self.__first_value_since(data_property_id, "day", day=None)

    async def read_first_value_month(self, data_property_id: str):
        '''
        The first value a property logged this month (from the 1st, local
        midnight), the baseline of a per-month calculated field; None as for
        read_first_value_day.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag).
        '''
        return await self.__first_value_since(data_property_id, "month", day=1)

    async def __first_value_since(self, data_property_id: str, period: str, day: int | None):
        '''
        The first value of a property since local midnight of today (day=None) or
        of the given day of this month.
        Arguments:
            data_property_id (str): The property id; validated against _SAFE_ID.
            period (str): "day" or "month", for the log lines.
            day (int | None): Day of the month to start from, or None for today.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        start = datetime.now(self.__timezone).replace(hour=0, minute=0, second=0, microsecond=0)
        if day is not None:
            start = start.replace(day=day)

        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {start.isoformat()})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> first()'

        table = await self.__single_table(
            query, f"first-of-{period} read failed for {data_property_id}")
        if table is None or not table.records:
            return None

        value = table.records[0].get_value()
        logger.debug("First value of %s for %s: %s", period, data_property_id, value)
        return value
