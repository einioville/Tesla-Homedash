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
