from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError
from zoneinfo import ZoneInfo

import aiohttp

logger = logging.getLogger("weather_service.weather_view")

_TIMESERIES_URL = "https://opendata.fmi.fi/timeseries"
_CAP_URL = "https://alerts.fmi.fi/cap/feed/atom_fi-FI.xml"

_WEEKDAYS = ["ma", "ti", "ke", "to", "pe", "la", "su"]

# The observation fields, each taken from the nearest station that reports it: the place's
# own station seldom measures everything (Tampere resolves to Siilinkari, which has no
# precipitation, snow, visibility or cloud), so up to five stations within 50 km are asked.
_OBS_FIELDS = ["t2m", "ws_10min", "wg_10min", "wd_10min", "rh", "td", "p_sea", "vis",
               "wawa", "ri_10min", "r_1h", "snow_aws"]

# The edited forecast (what ilmatieteenlaitos.fi shows) runs about 230 hours ahead; asking
# for more returns what there is.
_FORECAST_HOURS = 300

# Present weather (WMO 4680 "wawa") as a short Finnish text, by code range. Codes 20-25
# (precipitation in the past hour, none now) have no text: the 0 mm/h beside it says as much.
_WAWA_TEXTS = [
    ((4, 5), "auerta"), ((10, 10), "utua"),
    ((30, 35), "sumua"), ((40, 42), "sadetta"), ((50, 53), "tihkua"),
    ((54, 56), "jäätävää tihkua"), ((57, 58), "tihkua ja sadetta"),
    ((60, 63), "vesisadetta"), ((64, 66), "jäätävää sadetta"), ((67, 68), "räntää"),
    ((70, 73), "lumisadetta"), ((74, 78), "jääjyväsiä"), ((80, 84), "sadekuuroja"),
    ((85, 87), "lumikuuroja"), ((89, 89), "raekuuroja"),
]

# FMI's potential precipitation form (0 drizzle, 1 rain, 2 sleet, 3 snow, 4 freezing drizzle,
# 5 freezing rain, 6 hail) as the view tells them apart: sleet and snow by name, the rest as rain.
_PRECIP_FORMS = {2: "sleet", 3: "snow"}

# Present weather (WMO 4680) codes that say what is falling now, the same way; codes 40-42
# ("precipitation", form unknown) are left to the forecast.
_WAWA_FORMS = [((50, 66), "rain"), ((67, 68), "sleet"), ((70, 78), "snow"), ((80, 84), "rain"),
               ((85, 87), "snow"), ((89, 89), "rain")]

# CAP severities as the warning colours FMI uses.
_WARNING_COLORS = {"Moderate": "yellow", "Severe": "orange", "Extreme": "red"}

# Everything a failed fetch can raise. asyncio.TimeoutError is listed on its own: before
# Python 3.11 it is not an OSError.
_FETCH_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, OSError, ParseError,
                 ValueError, KeyError, IndexError, TypeError)


def _wawa_text(code) -> str | None:
    '''
    Returns the short Finnish text for a present-weather code, or None for codes that
    describe nothing worth showing (clear, haze-free, no precipitation).
    Arguments:
        code (float | None): WMO 4680 code as FMI reports it.
    '''
    if code is None:
        return None
    c = int(code)
    for (lo, hi), text in _WAWA_TEXTS:
        if lo <= c <= hi:
            return text
    return None


def _wawa_form(code) -> str | None:
    '''
    Returns what a present-weather code says is falling ("rain", "sleet" or "snow"), or None
    when it says nothing falls or not what.
    Arguments:
        code (float | None): WMO 4680 code as FMI reports it.
    '''
    if code is None:
        return None
    c = int(code)
    for (lo, hi), form in _WAWA_FORMS:
        if lo <= c <= hi:
            return form
    return None


def _uv_index(radiation, elevation) -> float | None:
    '''
    Estimates the UV index, which FMI does not publish: a clear-sky index from the sun's
    elevation (Madronich's 12.5·μ^2.42, scaled to 350 DU of ozone, about Finland's column),
    times the share of clear-sky radiation that gets through the cloud — HARMONIE's global
    radiation against a clear-sky model (Haurwitz). Radiation alone cannot carry it: a low
    spring or autumn sun gives far less UV per W/m². About 6 on a clear midsummer noon in
    the south, about 1 in October. An estimate, not a measurement.
    Arguments:
        radiation (float | None): HARMONIE RadiationGlobal for the hour, W/m².
        elevation (float | None): The sun's elevation for the hour, degrees.
    '''
    if radiation is None or elevation is None:
        return None
    mu = math.sin(math.radians(elevation))
    if mu <= 0:
        return 0.0
    clear_uv = 12.5 * mu ** 2.42 * (350 / 300) ** -1.23
    clear_radiation = 1098 * mu * math.exp(-0.057 / mu)
    return round(clear_uv * min(1.0, max(0.0, radiation) / clear_radiation), 1)


def _inside(polygon: list[tuple[float, float]], lat: float, lon: float) -> bool:
    '''
    Even-odd point-in-polygon test, for whether a warning area covers the place.
    Arguments:
        polygon (list[tuple[float, float]]): The area's corners as (lat, lon).
        lat (float): The place's latitude.
        lon (float): The place's longitude.
    '''
    hit = False
    for i in range(len(polygon)):
        (y1, x1), (y2, x2) = polygon[i], polygon[i - 1]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


# A warning's areas as the Kartta view draws them (`shapes`): FMI's polygons, thousands of
# points per warning, simplified to about half a kilometre and rounded to about a hundred
# metres — finer than the map shows a region, and small enough to send every ten minutes.
_SHAPE_TOLERANCE_DEG = 0.005
_SHAPE_DECIMALS = 3


def _simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    '''
    Douglas-Peucker: drops every point that lies within `tolerance` of the line its kept
    neighbours draw. Longitude is scaled by the cosine of latitude, so the tolerance is the
    same distance east-west as north-south.
    Arguments:
        points (list[tuple[float, float]]): A ring or line as (lat, lon).
        tolerance (float): The largest deviation dropped, in degrees of latitude.
    '''
    if len(points) < 3:
        return list(points)
    scale = math.cos(math.radians(points[0][0]))
    xy = [(lon * scale, lat) for lat, lon in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = xy[first], xy[last]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        farthest, index = 0.0, -1
        for i in range(first + 1, last):
            x, y = xy[i]
            # From the chord, or from its end when the chord is a point (a closed ring).
            d = (abs(dy * x - dx * y + x2 * y1 - y2 * x1) / length if length
                 else math.hypot(x - x1, y - y1))
            if d > farthest:
                farthest, index = d, i
        if farthest > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep) if k]


def describe(where: dict) -> str:
    '''
    A weather location for the log: the place name or the coordinates.
    Arguments:
        where (dict): The location as FMI query arguments (Config.weather_location).
    '''
    return ", ".join(f"{k}={v}" for k, v in where.items())


def _utc(t: datetime) -> str:
    '''
    Formats an aware datetime as the UTC timestamp FMI's starttime takes.
    Arguments:
        t (datetime): Any timezone-aware datetime.
    '''
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WeatherViewBuilder:
    '''
    Builds the Weather view's document — the current weather merged from the nearest
    stations, the hourly forecast as far as it goes, the days, sun and moon, and FMI's
    warnings — from FMI's open data. The document is sent as one WEATHER_VIEW frame.

    Each part is fetched on its own and a part that fails keeps its last good value, so one
    stalled request costs that part a refresh instead of costing the view all of its data.
    The parts are dropped when the location changes.
    '''

    def __init__(self, zone_info: ZoneInfo, timeout: aiohttp.ClientTimeout):
        '''
        Arguments:
            zone_info (ZoneInfo): The configured timezone; every time in the document is in it.
            timeout (aiohttp.ClientTimeout): The per-request ceiling (see weather_service).
        '''
        self.__zone = zone_info
        self.__timeout = timeout
        self.__loop = asyncio.get_running_loop()
        self.__where: dict | None = None
        self.__location: dict | None = None
        self.__observation: dict | None = None
        self.__hourly: list[dict] | None = None
        self.__radiation: tuple[str, float | None] | None = None
        self.__astro: dict | None = None
        self.__warnings: list[dict] | None = None

    async def build(self, where: dict) -> dict | None:
        '''
        Fetches every part for the location and returns the document, or None when there
        is no forecast to show — a document without hours would blank the chart and the days.
        Arguments:
            where (dict): The location as FMI query arguments (Config.weather_location):
                a place name, or the home's coordinates, which FMI takes as they are.
        '''
        if where != self.__where:
            self.__where = where
            self.__location = self.__observation = self.__hourly = None
            self.__radiation = self.__astro = self.__warnings = None

        now = datetime.now(self.__zone)
        hour0 = now.replace(minute=0, second=0, microsecond=0)
        async with aiohttp.ClientSession(timeout=self.__timeout) as session:
            if self.__location is None:
                self.__location = await self.__part("location", self.__fetch_location(session, where))
            if self.__location is None:
                return None
            localtz = ZoneInfo(self.__location["localtz"])
            observation, hourly, radiation, astro, warnings = await asyncio.gather(
                self.__part("observation", self.__fetch_observation(session, where)),
                self.__part("forecast", self.__fetch_forecast(session, where, hour0)),
                self.__part("radiation", self.__fetch_radiation(session, where, hour0)),
                self.__part("sun and moon", self.__fetch_astro(session, where, now, localtz)),
                self.__part("warnings", self.__fetch_warnings(session)),
            )
        if observation is not None:
            self.__observation = observation
        if hourly:
            self.__hourly = hourly
        if radiation is not None:
            self.__radiation = (hour0.isoformat(), radiation)
        if astro is not None:
            self.__astro = astro
        if warnings is not None:
            self.__warnings = warnings

        # A forecast kept from an earlier cycle still starts at the hour it was fetched in;
        # the chart's first hour is now, so the hours already past are dropped.
        hour_iso = hour0.strftime("%Y-%m-%dT%H:%M")
        hours = [h for h in (self.__hourly or []) if h["iso"] >= hour_iso]
        if not hours:
            logger.warning("Weather view has no forecast hours for %s — not sent", describe(where))
            return None

        # The UV estimate is for this hour only, so radiation from another hour is not used.
        radiation_now = (self.__radiation[1] if self.__radiation
                         and self.__radiation[0] == hour0.isoformat() else None)
        # The feed keeps a warning for a while after it ends.
        in_force = [w for w in self.__warnings or [] if w["span"][1] is None or w["span"][1] > now]
        warnings = self.__mark_warnings(in_force, self.__location["lat"], self.__location["lon"])
        here = [w for w, sent in zip(in_force, warnings) if sent["appliesHere"]]
        return {
            "meta": {"place": self.__location["name"], "lat": self.__location["lat"],
                     "lon": self.__location["lon"], "fetchedMs": int(now.timestamp() * 1000)},
            "now": self.__now_block(hours[0], radiation_now),
            "hourly": self.__warned_hours(hours, here),
            "daily": self.__daily(hours),
            "astro": self.__astro or {},
            "warnings": warnings,
        }

    async def __part(self, label: str, fetch):
        '''
        Runs one part's fetch, logging and swallowing any failure as None.
        Arguments:
            label (str): The part's name for the log.
            fetch: The part's fetch coroutine.
        '''
        try:
            return await fetch
        except _FETCH_ERRORS as e:
            logger.warning("Weather view %s fetch failed for %s: %s: %s",
                           label, describe(self.__where), type(e).__name__, e)
            return None

    async def __timeseries(self, session: aiohttp.ClientSession, params: dict) -> list[dict]:
        '''
        One request to FMI's timeseries service, which answers in JSON.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            params (dict): The query; format, precision and language are added here.
        '''
        query = {"format": "json", "precision": "double", "lang": "fi", **params}
        async with session.get(_TIMESERIES_URL, params=query) as response:
            response.raise_for_status()
            rows = json.loads(await response.read())
        if not isinstance(rows, list):
            raise ValueError("timeseries answered with no rows")
        return rows

    def __local(self, epoch) -> datetime:
        '''
        Converts FMI's epochtime to the configured zone.
        Arguments:
            epoch (float): Seconds since the epoch.
        '''
        return datetime.fromtimestamp(epoch, self.__zone)

    async def __fetch_location(self, session: aiohttp.ClientSession, where: dict) -> dict:
        '''
        Resolves the location to its name (FMI's nearest place name, for coordinates),
        coordinates and own timezone; the radar centres on the coordinates and the warnings
        are tested against them.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            where (dict): The location as FMI query arguments (Config.weather_location).
        '''
        row = (await self.__timeseries(session, {
            **where, "timesteps": 1, "param": "name,latitude,longitude,localtz"}))[0]
        return {"name": row["name"], "lat": row["latitude"], "lon": row["longitude"],
                "localtz": row["localtz"]}

    async def __fetch_observation(self, session: aiohttp.ClientSession, where: dict) -> dict:
        '''
        The newest value of each observation field from the nearest station reporting it,
        with where each came from and the time of the newest one used.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            where (dict): The location as FMI query arguments (Config.weather_location).
        '''
        rows = await self.__timeseries(session, {
            "producer": "opendata", **where, "numberofstations": 5,
            "maxdistance": 50000, "starttime": "-70m", "timestep": 10,
            "param": "fmisid,stationname,distance,epochtime," + ",".join(_OBS_FIELDS)})
        # Rows come grouped by station, nearest first, and oldest first within a station.
        stations: list[tuple[int, str, float, list[dict]]] = []
        for r in rows:
            if not stations or stations[-1][0] != r["fmisid"]:
                stations.append((r["fmisid"], r["stationname"], r["distance"], []))
            stations[-1][3].append(r)
        values, sources, latest = {}, {}, None
        for field in _OBS_FIELDS:
            for _, name, distance, station_rows in stations:
                hit = next((r for r in reversed(station_rows) if r[field] is not None), None)
                if hit:
                    values[field] = hit[field]
                    sources[field] = {"station": name, "distance": distance}
                    t = self.__local(hit["epochtime"])
                    latest = max(latest, t) if latest else t
                    break
        if not values:
            raise ValueError("no station reported anything")
        return {"values": values, "sources": sources,
                "time": latest.strftime("%H:%M") if latest else None}

    async def __fetch_forecast(self, session: aiohttp.ClientSession, where: dict,
                               hour0: datetime) -> list[dict]:
        '''
        The edited hourly forecast from the current hour to its end, about ten days.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            where (dict): The location as FMI query arguments (Config.weather_location).
            hour0 (datetime): The start of the current hour.
        '''
        rows = await self.__timeseries(session, {
            **where, "timesteps": _FORECAST_HOURS, "timestep": 60,
            "starttime": _utc(hour0),
            "param": "epochtime,temperature,feelslike,smartsymbol,smartsymboltext,pop,"
                     "precipitation1h,potentialprecipitationform,windspeedms,winddirection,"
                     "hourlymaximumgust,totalcloudcover,humidity,probabilitythunderstorm,sunelevation"})
        hourly = []
        for r in rows:
            # The forecast's end is padded with empty hours.
            if r["temperature"] is None or r["smartsymbol"] is None:
                continue
            t = self.__local(r["epochtime"])
            hourly.append({
                "iso": t.strftime("%Y-%m-%dT%H:%M"), "day": t.strftime("%Y-%m-%d"),
                "hour": t.hour, "wd": _WEEKDAYS[t.weekday()], "date": f"{t.day}.{t.month}.",
                "temp": r["temperature"], "feels": r["feelslike"], "symbol": int(r["smartsymbol"]),
                "text": r["smartsymboltext"], "pop": r["pop"] or 0, "precip": r["precipitation1h"] or 0,
                "precipForm": _PRECIP_FORMS.get(r["potentialprecipitationform"], "rain"),
                "wind": r["windspeedms"], "windDir": r["winddirection"], "gust": r["hourlymaximumgust"],
                "cloud": r["totalcloudcover"], "humidity": r["humidity"],
                "thunder": r["probabilitythunderstorm"] or 0, "sunElev": r["sunelevation"],
            })
        return hourly

    async def __fetch_radiation(self, session: aiohttp.ClientSession, where: dict,
                                hour0: datetime) -> float | None:
        '''
        HARMONIE's global radiation for the current hour, for the UV estimate; the edited
        forecast has none.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            where (dict): The location as FMI query arguments (Config.weather_location).
            hour0 (datetime): The start of the current hour.
        '''
        rows = await self.__timeseries(session, {
            **where, "producer": "harmonie_scandinavia_surface", "timesteps": 1,
            "starttime": _utc(hour0), "param": "epochtime,RadiationGlobal"})
        return rows[0].get("RadiationGlobal") if rows else None

    async def __fetch_astro(self, session: aiohttp.ClientSession, where: dict, now: datetime,
                            localtz: ZoneInfo) -> dict:
        '''
        Today's sun and moon. Yesterday is fetched for the day length's change and tomorrow
        for whether the moon is waxing.
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
            where (dict): The location as FMI query arguments (Config.weather_location).
            now (datetime): The current time in the configured zone.
            localtz (ZoneInfo): The place's own zone, which FMI's rise and set times are in.
        '''
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self.__timeseries(session, {
            **where, "timestep": 1440, "timesteps": 3,
            "starttime": _utc(midnight - timedelta(days=1)),
            "param": "sunrise,sunset,noon,daylength,moonphase,moonrise,moonset"})
        yesterday, today, tomorrow = rows[0], rows[1], rows[2]

        # Rise and set come as '20261011T075653' in the place's zone, or empty on a day
        # without one (the moon, often; the sun, in the far north).
        def at(s):
            if not s:
                return None
            return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=localtz).astimezone(self.__zone)

        def hhmm(s):
            t = at(s)
            return t.strftime("%H:%M") if t else None

        def iso(s):
            t = at(s)
            return t.strftime("%Y-%m-%dT%H:%M") if t else None

        return {
            "sunrise": hhmm(today["sunrise"]), "sunset": hhmm(today["sunset"]),
            "noon": hhmm(today["noon"]),
            "sunriseIso": iso(today["sunrise"]), "sunsetIso": iso(today["sunset"]),
            "dayLength": today["daylength"],
            "dayLengthDelta": today["daylength"] - yesterday["daylength"],
            "moonPhase": today["moonphase"], "moonWaxing": tomorrow["moonphase"] > today["moonphase"],
            "moonrise": hhmm(today["moonrise"]), "moonset": hhmm(today["moonset"]),
        }

    async def __fetch_warnings(self, session: aiohttp.ClientSession) -> list[dict]:
        '''
        FMI's current warnings for all of Finland, each with its area polygons; whether one
        covers the place is decided per document (__mark_warnings).
        Arguments:
            session (aiohttp.ClientSession): Session carrying the request timeout.
        '''
        async with session.get(_CAP_URL) as response:
            response.raise_for_status()
            xml = await response.read()
        # The feed is a few hundred kilobytes of XML; parse it off the event loop.
        return await self.__loop.run_in_executor(None, self.__parse_warnings, xml)

    def __parse_warnings(self, xml: bytes) -> list[dict]:
        '''
        Parses the CAP Atom feed into one entry per distinct headline.
        Arguments:
            xml (bytes): The feed as fetched.
        '''
        def at(s):
            return datetime.fromisoformat(s).astimezone(self.__zone) if s else None

        def when(t):
            return f"{_WEEKDAYS[t.weekday()]} {t.hour}.{t.minute:02d}" if t else None

        warnings, seen = [], set()
        for alert in ElementTree.fromstring(xml).iter():
            if not alert.tag.endswith("}alert"):
                continue
            ns = alert.tag[:-len("alert")]
            info = next((i for i in alert.findall(ns + "info")
                         if (i.findtext(ns + "language") or "").startswith("fi")),
                        alert.find(ns + "info"))
            if info is None:
                continue
            headline = info.findtext(ns + "headline") or ""
            if headline in seen:
                continue
            seen.add(headline)
            areas, polygons = [], []
            for area in info.findall(ns + "area"):
                name = area.findtext(ns + "areaDesc") or ""
                areas.append(name)
                for p in area.findall(ns + "polygon"):
                    polygon = [tuple(map(float, pt.split(","))) for pt in (p.text or "").split()]
                    if len(polygon) > 2:
                        polygons.append((name, polygon))
            severity = info.findtext(ns + "severity") or ""
            onset, expires = at(info.findtext(ns + "onset")), at(info.findtext(ns + "expires"))
            warnings.append({
                "event": info.findtext(ns + "event"), "severity": severity,
                "color": _WARNING_COLORS.get(severity, "yellow"), "headline": headline,
                "areas": areas[:4], "onset": when(onset), "expires": when(expires),
                "description": (info.findtext(ns + "description") or "").strip(),
                "polygons": polygons, "span": (onset, expires),
                "shapes": [
                    [[round(lat, _SHAPE_DECIMALS), round(lon, _SHAPE_DECIMALS)]
                     for lat, lon in ring]
                    for ring in (_simplify(p, _SHAPE_TOLERANCE_DEG) for _, p in polygons)
                    if len(ring) > 3
                ],
            })
        return warnings

    @staticmethod
    def __mark_warnings(warnings: list[dict], lat: float, lon: float) -> list[dict]:
        '''
        The warnings as sent: each with the areas that cover the place (`hereAreas`; the
        headline names the warning's whole region, which can lead with one far away) and
        whether any does, and without the full polygons, which only that test needs — the
        map draws the simplified `shapes` — or the times, which go as text.
        Arguments:
            warnings (list[dict]): Parsed warnings, polygons included.
            lat (float): The place's latitude.
            lon (float): The place's longitude.
        '''
        marked = []
        for w in warnings:
            entry = {k: v for k, v in w.items() if k not in ("polygons", "span")}
            here = [name for name, p in w["polygons"] if _inside(p, lat, lon)]
            entry["hereAreas"] = list(dict.fromkeys(here))
            entry["appliesHere"] = bool(here)
            marked.append(entry)
        return marked

    def __warned_hours(self, hours: list[dict], warnings: list[dict]) -> list[dict]:
        '''
        The hours as sent: each hour a warning covering the place is in force in carries the
        strongest such warning's colour (`warning`), which the dashboard's hourly card marks.
        Arguments:
            hours (list[dict]): The forecast hours from the current one.
            warnings (list[dict]): The parsed warnings in force that cover the place.
        '''
        levels = list(_WARNING_COLORS.values())
        marked = []
        for h in hours:
            start = datetime.fromisoformat(h["iso"]).replace(tzinfo=self.__zone)
            end = start + timedelta(hours=1)
            colors = [w["color"] for w in warnings
                      if (w["span"][0] is None or w["span"][0] < end)
                      and (w["span"][1] is None or w["span"][1] > start)]
            marked.append({**h, "warning": max(colors, key=levels.index)} if colors else h)
        return marked

    def __now_block(self, hour: dict, radiation) -> dict:
        '''
        The current weather: each observed value where a station reports it, the forecast's
        current hour for the rest and for the symbol, text and feels-like.
        Arguments:
            hour (dict): The forecast's current hour.
            radiation (float | None): HARMONIE's global radiation for this hour.
        '''
        observed = self.__observation or {}
        v = observed.get("values", {})
        return {
            "time": observed.get("time"),
            "temp": v.get("t2m", hour["temp"]), "feels": hour["feels"],
            "wind": v.get("ws_10min", hour["wind"]), "gust": v.get("wg_10min", hour["gust"]),
            "windDir": v.get("wd_10min", hour["windDir"]), "humidity": v.get("rh", hour["humidity"]),
            "dewPoint": v.get("td"), "pressure": v.get("p_sea"), "visibility": v.get("vis"),
            "uvIndex": _uv_index(radiation, hour["sunElev"]),
            "precipRate": v.get("ri_10min"), "precip1h": v.get("r_1h"), "snowDepth": v.get("snow_aws"),
            "precipForm": _wawa_form(v.get("wawa")) or hour["precipForm"],
            "wawa": v.get("wawa"), "wawaText": _wawa_text(v.get("wawa")),
            "symbol": hour["symbol"], "text": hour["text"], "sources": observed.get("sources", {}),
        }

    @staticmethod
    def __daily(hours: list[dict]) -> list[dict]:
        '''
        Folds the hourly forecast into days: low and high, the day's precipitation and the
        part of it that falls as snow (both mm of water), the strongest wind, and the symbol
        and text of the hour closest to 14:00.
        Arguments:
            hours (list[dict]): The hourly forecast, oldest first.
        '''
        days: list[dict] = []
        for h in hours:
            if not days or days[-1]["day"] != h["day"]:
                days.append({"day": h["day"], "wd": h["wd"], "date": h["date"], "hours": []})
            days[-1]["hours"].append(h)
        for d in days:
            hs = d.pop("hours")
            rep = min(hs, key=lambda h: abs(h["hour"] - 14))
            # The day's symbol is a daytime one (FMI adds 100 for night) unless the day
            # has no daylight to show.
            daylight = (rep["sunElev"] is not None and rep["sunElev"] >= 0) or 9 <= rep["hour"] <= 18
            d.update({
                "min": min(h["temp"] for h in hs), "max": max(h["temp"] for h in hs),
                "precip": round(sum(h["precip"] for h in hs), 1),
                "snow": round(sum(h["precip"] for h in hs if h["precipForm"] == "snow"), 1),
                "popMax": max(h["pop"] for h in hs),
                "symbol": rep["symbol"] % 100 if daylight else rep["symbol"], "text": rep["text"],
                "windMax": max(h["wind"] or 0 for h in hs), "gustMax": max(h["gust"] or 0 for h in hs),
                "hours": len(hs),
            })
        return days
