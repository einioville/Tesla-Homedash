from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
import logging
import re
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from ..utils.config_parser import get_env

_SAFE_ID = re.compile(r'^[A-Za-z0-9_\-]+$')
# aggregate_window is interpolated into Flux, so it gets the same injection guard
# as the id: only a positive integer followed by a Flux duration unit (e.g. 15s,
# 5m, 1h, 30d).
_SAFE_WINDOW = re.compile(r'^[1-9][0-9]*[smhd]$')

logger = logging.getLogger("influxdb_service.influxdb_handler")


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
        logger.info(
            "InfluxDB handler initialized: url=%s, org=%s, tz=%s",
            url, org, zone_info.key,
        )

    async def connected(self) -> bool:
        return await self.__client.ping()

    async def close(self) -> None:
        await self.__client.close()

    async def read_tesla_data_property(
        self,
        data_property_id: str,
        time_start: str,
        time_end: str,
        aggregate_window: str | None = None,
    ) -> tuple:
        '''
        Reads a logged numeric property's history from InfluxDB over a time range.
        When aggregate_window is given, the series is downsampled onto a regular
        grid (mean per window) and gaps are forward-filled — so e.g. a value held
        constant for ten minutes with a single stored record is replayed at every
        window step (the History graph relies on this).  Leading windows before
        the first real sample stay null and are dropped.
        Arguments:
            data_property_id (str): The property id (InfluxDB "id" tag). Validated
                against _SAFE_ID before interpolation.
            time_start (str): Flux range start (relative like "-1h" or RFC3339).
            time_end (str): Flux range stop ("now()" or RFC3339).
            aggregate_window (str | None): Flux duration (e.g. "15s", "5m", "1h")
                to downsample + forward-fill onto, or None for the raw series.
                Validated against _SAFE_WINDOW before interpolation.
        Returns:
            tuple | None: (count, timestamps_ms (int64), values (float64)), or None
                if InfluxDB is unreachable / the query fails / there is no data.
        '''
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")
        if aggregate_window is not None and not _SAFE_WINDOW.match(aggregate_window):
            raise ValueError(f"Invalid aggregate_window: {aggregate_window!r}")

        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        # Graphable properties store their value under the "value_float" field;
        # restricting to it keeps a single result table and excludes any
        # non-numeric fields that might share the id tag.
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
        if aggregate_window is not None:
            query += f'\n  |> aggregateWindow(every: {aggregate_window}, fn: mean, createEmpty: true)'
            query += '\n  |> fill(usePrevious: true)'
        query += '\n  |> keep(columns: ["_time", "_value"])'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable or query failure must not propagate to the
            # caller — degrade to "no data" so a history read just comes back empty.
            logger.warning(
                "InfluxDB history read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None
        logger.debug("Query returned results for property: %s", data_property_id)

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]

        # Drop null values: aggregateWindow(createEmpty=true) + fill(usePrevious)
        # leaves the windows before the first real sample null (nothing to carry
        # forward yet), and a raw series can carry None for an absent reading.
        records = [r for r in table if r.get_value() is not None]
        if not records:
            return None

        timestamps = np.array(
            [record.get_time().timestamp() * 1000 for record in records], dtype=np.int64
        )
        values = np.array([record.get_value() for record in records], dtype=np.float64)

        return len(values), timestamps, values

    async def read_charger_data_property(
        self, data_property_id: str, time_start: str, time_end: str
    ) -> tuple | None:
        '''
        Reads a logged charger (myenergi) numeric property's raw history over a time
        range — the charger analogue of read_tesla_data_property. The only difference
        is the measurement: myenergi charger points live under "myenergi_data" (written
        by MyEnergiService), kept separate from "tesla_data" but queryable over the same
        time window so a charging session's charger energy can be joined to the vehicle's
        telemetry. Values come back raw and ascending; the caller (ChargingSession) takes
        the in-window delta/max it needs.
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

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # Same degrade-to-None contract as the tesla reads: an unreachable InfluxDB
            # or a failed query yields "no data" so a charging-loss computation simply
            # comes back with NaN charger energy rather than propagating to the caller.
            logger.warning(
                "InfluxDB charger history read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        records = [r for r in table if r.get_value() is not None]
        if not records:
            return None

        timestamps = np.array(
            [record.get_time().timestamp() * 1000 for record in records], dtype=np.int64
        )
        values = np.array([record.get_value() for record in records], dtype=np.float64)

        return len(values), timestamps, values

    async def read_last_value_before(
        self, data_property_id: str, stop_time: str
    ) -> float | None:
        '''
        Reads the most recent stored value of a property strictly before a given
        time — used by the History path to draw a flat held line for a window in
        which nothing was logged (a value that stayed constant). Scans from the
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

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable or query failure must degrade to "no prior value"
            # so an empty-window history read simply stays empty ("Ei dataa") rather
            # than fabricating a line — and never propagates to the caller.
            logger.warning(
                "InfluxDB last-value-before read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
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
        by time — e.g. the Gear / ShiftState transition timeline that trip detection
        segments on. Records are returned raw, with no de-duplication: logged fields
        are written on every telemetry event (not only on change), so the caller must
        collapse consecutive identical readings to recover the real transitions.
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
        # under the "value_string" field — the only difference from the numeric read.
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_string")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> sort(columns: ["_time"])'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable or query failure degrades to "no data" so a trip
            # scan simply finds nothing rather than propagating to the caller.
            logger.warning(
                "InfluxDB string-history read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
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
        given time — used by trip detection to learn the held Gear / ShiftState at
        the start of a query window, so a trip already in progress at the window
        boundary is still recognised. The string analogue of read_last_value_before.
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

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            logger.warning(
                "InfluxDB last-string-before read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
            return None

        value = table.records[0].get_value()
        if value is None:
            return None
        return str(value)

    async def read_location_endpoint(
        self, time_start: str, time_end: str, last: bool
    ) -> tuple | None:
        '''
        Reads the first or last GPS fix inside a time window — a trip's start or end
        point. Location is a value_dict, stored as two separate fields "latitude" and
        "longitude" under the same id="Location" tag (the Fleet Telemetry Location
        signal's own keys), so the two fields are pivoted back into one row and the
        earliest (last=False) or latest (last=True) row in the window is returned.
        Arguments:
            time_start (str): Flux range start (RFC3339 or relative). Code-generated.
            time_end (str): Flux range stop (RFC3339 or relative). Code-generated.
            last (bool): True for the latest fix in the window (trip end point), False
                for the earliest (trip start point).
        Returns:
            tuple | None: (latitude (float), longitude (float)), or None if InfluxDB
                is unreachable / the query fails / no fix was logged in the window.
        '''
        # "Location" is a fixed literal id (not caller input), so no _SAFE_ID needed.
        query = f'from(bucket:"{self.__bucket}")'
        query += f"\n  |> range(start: {time_start}, stop: {time_end})"
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += '\n  |> filter(fn: (r) => r["id"] == "Location")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "latitude" or r["_field"] == "longitude")'
        query += '\n  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        query += '\n  |> keep(columns: ["_time", "latitude", "longitude"])'
        query += f'\n  |> sort(columns: ["_time"], desc: {"true" if last else "false"})'
        query += '\n  |> limit(n: 1)'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            logger.warning(
                "InfluxDB location-endpoint read failed (last=%s): %s: %s",
                last, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
            return None

        record = table.records[0]
        latitude = record.values.get("latitude")
        longitude = record.values.get("longitude")
        if latitude is None or longitude is None:
            return None
        return float(latitude), float(longitude)

    async def read_location_history(
        self, time_start: str, time_end: str
    ) -> list | None:
        '''
        Reads every GPS fix logged inside a time window, ascending by time — the full
        path of a trip, drawn as the coloured route on the Trips-view map. Location is
        a value_dict stored as two separate fields "latitude" and "longitude" under the
        same id="Location" tag, so the two fields are pivoted back into one row per
        fix. Unlike read_location_endpoint (which limits to a single endpoint), this
        returns the whole series. Rows missing either coordinate are skipped.
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

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable or query failure degrades to "no data" so a trip
            # route simply comes back empty rather than propagating to the caller.
            logger.warning(
                "InfluxDB location-history read failed: %s: %s",
                type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
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
            logger.info("Wrote %d points to InfluxDB", len(valid_points))
        except Exception as e:
            logger.error("Failed to write points to InfluxDB: %s", e)
            raise

    async def write_charger_data(self, points: list) -> None:
        '''
        Writes myenergi charger points to InfluxDB. Identical mechanics to
        write_tesla_data (the measurement is baked into each Point by the caller —
        MyEnergiService builds Point("myenergi_data") records), kept as a separate
        method so the charger's write path reads clearly at the call site and can
        diverge later (e.g. its own retry policy) without touching the tesla path.
        A failed write is logged and swallowed here — unlike write_tesla_data (whose
        raise lets Vehicle decide), a charger write must never break the poll loop /
        live broadcast, so it degrades quietly.
        Arguments:
            points (list): InfluxDB Point objects (or None entries, which are dropped).
        '''
        valid_points = [p for p in points if p is not None]
        if len(valid_points) == 0:
            return
        try:
            await self.__client.write_api().write(bucket=self.__bucket, record=valid_points)
            logger.info("Wrote %d charger points to InfluxDB", len(valid_points))
        except Exception as e:
            logger.error("Failed to write charger points to InfluxDB: %s", e)

    async def read_first_value_day(self, data_property_id: str):
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        current_day = datetime.now(self.__timezone).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {current_day})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> first()'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable (at startup or a midnight reset): return None
            # so CalculatedVehicleDataProperty falls back to the live value
            # instead of crashing the app.
            logger.warning(
                "InfluxDB first-of-day read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
            return None

        value = table.records[0].get_value()
        logger.debug("First value of day for %s: %s", data_property_id, value)
        return value
    
    async def read_first_value_month(self, data_property_id: str):
        if not _SAFE_ID.match(data_property_id):
            raise ValueError(f"Invalid data_property_id: {data_property_id!r}")

        current_day = datetime.now(self.__timezone).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {current_day})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> first()'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            # InfluxDB unreachable (at startup or a month reset): return None so
            # CalculatedVehicleDataProperty falls back to the live value instead
            # of crashing the app.
            logger.warning(
                "InfluxDB first-of-month read failed for %s: %s: %s",
                data_property_id, type(e).__name__, e,
            )
            return None

        if len(result) > 1:
            raise Exception("There was more than one table")

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
            return None

        value = table.records[0].get_value()
        logger.debug("First value of month for %s: %s", data_property_id, value)
        return value

    async def read_grid_import_kwh_month(self) -> float | None:
        '''
        Integrates the logged grid power (myenergi "GridPower", W) over the current
        calendar month (from the 1st, 00:00 in the configured timezone) into energy (kWh),
        counting only import (positive power) so grid export does not subtract from
        "energy bought" — the Charging view's month-to-date home grid-import figure. Uses
        Flux integral(unit: 1h) (W integrated over hours -> Wh), converted to kWh. Relies
        on GridPower being logged every poll (MyEnergiService), so the integral has a dense
        series to trapezoid over. Degrades to None on an unreachable/failed query or a
        month with no samples yet, matching the other reads' contract.
        Returns:
            float | None: Imported energy this month in kWh, or None.
        '''
        month_start = datetime.now(self.__timezone).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        # "GridPower" is a fixed literal id (not caller input), so no _SAFE_ID needed.
        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {month_start})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "myenergi_data")'
        query += '\n  |> filter(fn: (r) => r["id"] == "GridPower")'
        query += '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> sort(columns: ["_time"])'
        # Clamp export (negative) to zero so only imported energy is counted, then
        # integrate W over hours to get Wh.
        query += '\n  |> map(fn: (r) => ({ r with _value: if r._value < 0.0 then 0.0 else r._value }))'
        query += '\n  |> integral(unit: 1h)'

        try:
            result = await self.__client.query_api().query(query=query)
        except Exception as e:
            logger.warning(
                "InfluxDB grid-import-month read failed: %s: %s", type(e).__name__, e
            )
            return None

        if len(result) == 0:
            return None

        table = result[0]
        if not table.records:
            return None

        value = table.records[0].get_value()
        if value is None:
            return None
        return float(value) / 1000.0  # Wh -> kWh
