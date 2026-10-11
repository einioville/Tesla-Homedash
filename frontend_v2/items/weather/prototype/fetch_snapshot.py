"""PROTOTYPE — throwaway. Snapshots real FMI data for the Weather view prototype.

Writes WeatherProtoSnapshot.js beside this file; the prototype view reads it (the radar loop
and its lightning are the only live parts, fetched by QML straight from FMI). Rebuild the frontend after
running this — the .js is compiled into the binary.

    python3 frontend_v2/items/weather/prototype/fetch_snapshot.py [place]

Stdlib only, so the system python3 runs it. None of this is the real backend: no timeouts
policy, no retries, no error handling beyond what keeps the prototype runnable.
"""
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Helsinki")
TS = "https://opendata.fmi.fi/timeseries"
WFS = "https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0&request=getFeature&storedquery_id="
CAP = "https://alerts.fmi.fi/cap/feed/atom_fi-FI.xml"
OUT = Path(__file__).with_name("WeatherProtoSnapshot.js")

WEEKDAYS = ["ma", "ti", "ke", "to", "pe", "la", "su"]
MONTHS = ["tammikuu", "helmikuu", "maaliskuu", "huhtikuu", "toukokuu", "kesäkuu",
          "heinäkuu", "elokuu", "syyskuu", "lokakuu", "marraskuu", "joulukuu"]


def get(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=40) as r:
        return r.read()


def ts(params):
    return json.loads(get(TS, {"format": "json", "precision": "double", "lang": "fi", **params}))


def parse_local(s):
    """'20261011T075700' (local) → aware datetime."""
    return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=TZ)


def hhmm(s):
    return parse_local(s).strftime("%H:%M") if s else None


def wfs_rows(query, params):
    """Minimal multipointcoverage parser: one row dict per time step, plus station names."""
    root = ET.fromstring(get(WFS + query, params))
    sw = "{http://www.opengis.net/swe/2.0}"
    gml = "{http://www.opengis.net/gml/3.2}"
    cov = "{http://www.opengis.net/gmlcov/1.0}"
    fields = [f.get("name") for f in root.iter(sw + "field")]
    names = [n.text for n in root.iter(gml + "name")
             if n.get("codeSpace", "").endswith("locationcode/name")]
    pos = next(root.iter(cov + "positions"), None)
    vals = next(root.iter(gml + "doubleOrNilReasonTupleList"), None)
    if pos is None or vals is None:
        return [], names
    p = pos.text.split()
    times = [int(p[i]) for i in range(2, len(p), 3)]
    v = vals.text.split()
    rows = []
    for i, t in enumerate(times):
        chunk = v[i * len(fields):(i + 1) * len(fields)]
        row = {"time": datetime.fromtimestamp(t, timezone.utc).astimezone(TZ)}
        for f, x in zip(fields, chunk):
            row[f] = None if x.lower() == "nan" else float(x)
        rows.append(row)
    return rows, names


# --- present weather (WMO 4680 "wawa") → short Finnish text --------------------------
def wawa_text(code):
    if code is None:
        return None
    c = int(code)
    table = [
        ((4, 5), "auerta"), ((10, 10), "utua"), ((20, 25), "sade päättynyt"),
        ((30, 35), "sumua"), ((40, 42), "sadetta"), ((50, 53), "tihkua"),
        ((54, 56), "jäätävää tihkua"), ((57, 58), "tihkua ja sadetta"),
        ((60, 63), "vesisadetta"), ((64, 66), "jäätävää sadetta"), ((67, 68), "räntää"),
        ((70, 73), "lumisadetta"), ((74, 78), "jääjyväsiä"), ((80, 84), "sadekuuroja"),
        ((85, 87), "lumikuuroja"), ((89, 89), "raekuuroja"),
    ]
    for (lo, hi), text in table:
        if lo <= c <= hi:
            return text
    return None


def main():
    place = sys.argv[1] if len(sys.argv) > 1 else "Tampere"
    now = datetime.now(TZ)
    loc = ts({"place": place, "param": "name,latitude,longitude", "timesteps": 1})[0]
    lat, lon = loc["latitude"], loc["longitude"]

    # --- now: nearest station that reports each field ------------------------------------
    obs_fields = ["t2m", "ws_10min", "wg_10min", "wd_10min", "rh", "td", "p_sea", "vis",
                  "n_man", "wawa", "ri_10min", "r_1h", "snow_aws"]
    obs = ts({"producer": "opendata", "place": place, "numberofstations": 5,
              "maxdistance": 50000, "starttime": "-70m", "timestep": 10,
              "param": "fmisid,stationname,distance,localtime," + ",".join(obs_fields)})
    merged, sources, latest_time = {}, {}, None
    for f in obs_fields:
        # Rows are grouped by station, nearest first; within a station oldest first.
        stations = []
        for r in obs:
            if not stations or stations[-1][0] != r["fmisid"]:
                stations.append((r["fmisid"], r["stationname"], r["distance"], []))
            stations[-1][3].append(r)
        for _, name, dist, rows in stations:
            hit = next((r for r in reversed(rows) if r[f] is not None), None)
            if hit:
                merged[f] = hit[f]
                sources[f] = {"station": name, "distance": dist}
                t = parse_local(hit["localtime"])
                latest_time = max(latest_time, t) if latest_time else t
                break

    # --- hourly forecast (edited / "what ilmatieteenlaitos.fi shows") --------------------
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    fc = ts({"place": place, "timesteps": 300, "timestep": 60,
             "starttime": hour0.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "param": "localtime,temperature,feelslike,smartsymbol,smartsymboltext,pop,"
                      "precipitation1h,windspeedms,winddirection,hourlymaximumgust,"
                      "totalcloudcover,humidity,probabilitythunderstorm,sunelevation"})
    hourly = []
    for r in fc:
        if r["temperature"] is None or r["smartsymbol"] is None:
            continue
        t = parse_local(r["localtime"])
        hourly.append({
            "iso": t.strftime("%Y-%m-%dT%H:%M"), "day": t.strftime("%Y-%m-%d"),
            "hour": t.hour, "wd": WEEKDAYS[t.weekday()], "date": f"{t.day}.{t.month}.",
            "temp": r["temperature"], "feels": r["feelslike"], "symbol": int(r["smartsymbol"]),
            "text": r["smartsymboltext"], "pop": r["pop"] or 0, "precip": r["precipitation1h"] or 0,
            "wind": r["windspeedms"], "windDir": r["winddirection"], "gust": r["hourlymaximumgust"],
            "cloud": r["totalcloudcover"], "humidity": r["humidity"],
            "thunder": r["probabilitythunderstorm"] or 0, "sunElev": r["sunelevation"],
        })

    # --- daily aggregation from the hourly rows ------------------------------------------
    daily = []
    for h in hourly:
        if not daily or daily[-1]["day"] != h["day"]:
            daily.append({"day": h["day"], "wd": h["wd"], "date": h["date"], "hours": []})
        daily[-1]["hours"].append(h)
    for d in daily:
        hs = d.pop("hours")
        # Representative symbol: the 14:00 hour if there is one, else the latest daytime-ish hour.
        rep = min(hs, key=lambda h: abs(h["hour"] - 14))
        sym = rep["symbol"] % 100 if rep["sunElev"] is not None and rep["sunElev"] >= 0 or rep["hour"] in range(9, 19) else rep["symbol"]
        d.update({
            "min": min(h["temp"] for h in hs), "max": max(h["temp"] for h in hs),
            "precip": round(sum(h["precip"] for h in hs), 1),
            "popMax": max(h["pop"] for h in hs), "symbol": sym, "text": rep["text"],
            "windMax": max(h["wind"] or 0 for h in hs), "gustMax": max(h["gust"] or 0 for h in hs),
            "hours": len(hs),
        })

    first = hourly[0]
    now_block = {
        "time": latest_time.strftime("%H:%M") if latest_time else None,
        "temp": merged.get("t2m", first["temp"]), "feels": first["feels"],
        "wind": merged.get("ws_10min", first["wind"]), "gust": merged.get("wg_10min", first["gust"]),
        "windDir": merged.get("wd_10min", first["windDir"]), "humidity": merged.get("rh", first["humidity"]),
        "dewPoint": merged.get("td"), "pressure": merged.get("p_sea"), "visibility": merged.get("vis"),
        "cloudOktas": merged.get("n_man"), "precipRate": merged.get("ri_10min"),
        "precip1h": merged.get("r_1h"), "snowDepth": merged.get("snow_aws"),
        "wawa": merged.get("wawa"), "wawaText": wawa_text(merged.get("wawa")),
        "symbol": first["symbol"], "text": first["text"], "sources": sources,
    }

    # --- sun & moon ------------------------------------------------------------------------
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    astro_rows = ts({"place": place, "timestep": 1440, "timesteps": 3,
                     "starttime": (midnight - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "param": "localtime,sunrise,sunset,noon,daylength,moonphase,moonrise,moonset"})
    yday, today, tmrw = astro_rows[0], astro_rows[1], astro_rows[2]
    astro = {
        "sunrise": hhmm(today["sunrise"]), "sunset": hhmm(today["sunset"]), "noon": hhmm(today["noon"]),
        "sunriseIso": parse_local(today["sunrise"]).strftime("%Y-%m-%dT%H:%M"),
        "sunsetIso": parse_local(today["sunset"]).strftime("%Y-%m-%dT%H:%M"),
        "dayLength": today["daylength"], "dayLengthDelta": today["daylength"] - yday["daylength"],
        "moonPhase": today["moonphase"], "moonWaxing": tmrw["moonphase"] > today["moonphase"],
        "moonrise": hhmm(today["moonrise"]), "moonset": hhmm(today["moonset"]),
    }

    # --- past days + this month vs the 1991–2020 normal --------------------------------------
    # Daily stats come from the nearest station that measures precipitation.
    precip_station = sources.get("ri_10min") or sources.get("r_1h")
    fmisid = next((r["fmisid"] for r in obs if precip_station and r["stationname"] == precip_station["station"]), None)
    history, month = [], None
    if fmisid:
        start = min(midnight.replace(day=1), midnight - timedelta(days=7))
        rows, _ = wfs_rows("fmi::observations::weather::daily::multipointcoverage",
                           {"fmisid": fmisid, "starttime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        for r in rows:
            t = r["time"]
            history.append({"day": t.strftime("%Y-%m-%d"), "wd": WEEKDAYS[t.weekday()], "date": f"{t.day}.{t.month}.",
                            "min": r.get("tmin"), "max": r.get("tmax"), "mean": r.get("tday"),
                            "precip": max(r.get("rrday") or 0, 0), "snow": r.get("snow")})
        this_month = [h for h in history if h["day"].startswith(now.strftime("%Y-%m")) and h["mean"] is not None]
        normals, _ = wfs_rows("fmi::observations::weather::monthly::30year::multipointcoverage",
                              {"fmisid": fmisid, "starttime": "1991-01-01T00:00:00Z", "endtime": "1991-12-31T00:00:00Z"})
        n = next((r for r in normals if r["time"].month == now.month), None)
        if n and this_month:
            mean_so_far = sum(h["mean"] for h in this_month) / len(this_month)
            month = {"name": MONTHS[now.month - 1], "days": len(this_month), "station": precip_station["station"],
                     "meanSoFar": round(mean_so_far, 1), "normalMean": n.get("TAP1M"),
                     "normalMax": n.get("TAMAXP1M"), "normalMin": n.get("TAMINP1M"),
                     "normalPrecip": n.get("PRAP1M"),
                     "precipSoFar": round(sum(h["precip"] for h in this_month), 1),
                     "anomaly": round(mean_so_far - n["TAP1M"], 1) if n.get("TAP1M") is not None else None}
        history = history[-7:]

    # --- air quality ------------------------------------------------------------------------
    air = None
    for q in ("urban::observations::airquality::hourly::multipointcoverage",
              "fmi::observations::airquality::hourly::multipointcoverage"):
        rows, names = wfs_rows(q, {"place": place, "maxlocations": 1,
                                   "starttime": (now - timedelta(hours=4)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        rows = [r for r in rows if r.get("AQINDEX_PT1H_avg") is not None]
        if rows:
            r = rows[-1]
            air = {"station": names[0] if names else None, "time": r["time"].strftime("%H:%M"),
                   "index": int(r["AQINDEX_PT1H_avg"]), "pm25": r.get("PM25_PT1H_avg"),
                   "pm10": r.get("PM10_PT1H_avg"), "no2": r.get("NO2_PT1H_avg"), "o3": r.get("O3_PT1H_avg")}
            break

    # --- warnings (CAP), flagged when an area polygon covers the place -----------------------
    def inside(poly, y, x):
        hit = False
        for i in range(len(poly)):
            (y1, x1), (y2, x2) = poly[i], poly[i - 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
        return hit

    def fmt_time(s):
        t = datetime.fromisoformat(s).astimezone(TZ)
        return f"{WEEKDAYS[t.weekday()]} {t.hour}.{t.minute:02d}"

    warnings, seen = [], set()
    cap = ET.fromstring(get(CAP))
    for alert in cap.iter():
        if not alert.tag.endswith("}alert"):
            continue
        ns = alert.tag[:-len("alert")]
        info = next((i for i in alert.findall(ns + "info") if (i.findtext(ns + "language") or "").startswith("fi")),
                    alert.find(ns + "info"))
        if info is None:
            continue
        headline = info.findtext(ns + "headline") or ""
        if headline in seen:
            continue
        seen.add(headline)
        applies = False
        areas = []
        for area in info.findall(ns + "area"):
            areas.append(area.findtext(ns + "areaDesc") or "")
            for p in area.findall(ns + "polygon"):
                poly = [tuple(map(float, pt.split(","))) for pt in (p.text or "").split()]
                if len(poly) > 2 and inside(poly, lat, lon):
                    applies = True
        severity = info.findtext(ns + "severity") or ""
        color = {"Moderate": "yellow", "Severe": "orange", "Extreme": "red"}.get(severity, "yellow")
        warnings.append({"event": info.findtext(ns + "event"), "severity": severity, "color": color,
                         "headline": headline, "areas": areas[:4],
                         "onset": fmt_time(info.findtext(ns + "onset")) if info.findtext(ns + "onset") else None,
                         "expires": fmt_time(info.findtext(ns + "expires")) if info.findtext(ns + "expires") else None,
                         "description": (info.findtext(ns + "description") or "").strip(),
                         "appliesHere": applies})

    data = {
        "meta": {"place": loc["name"], "lat": lat, "lon": lon,
                 "fetched": f"{now.day}.{now.month}. {now:%H:%M}", "fetchedIso": now.isoformat()},
        "now": now_block, "hourly": hourly, "daily": daily, "astro": astro,
        "history": history, "month": month, "airQuality": air, "warnings": warnings,
    }
    OUT.write_text(
        "// PROTOTYPE — generated by fetch_snapshot.py; do not edit. Real FMI data for "
        f"{loc['name']}, fetched {data['meta']['fetched']}.\n.pragma library\n\nvar data = "
        + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"wrote {OUT} — {len(hourly)} hours, {len(daily)} days, {len(warnings)} warnings "
          f"({sum(w['appliesHere'] for w in warnings)} here), air={'yes' if air else 'no'}, "
          f"month={'yes' if month else 'no'}, now sources={ {k: v['station'] for k, v in sources.items()} }")


if __name__ == "__main__":
    main()
