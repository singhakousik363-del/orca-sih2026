"""
Data sources. Agents never call an API directly — they call a Source.

That is what makes the answer to "what if IMD access never arrives" a
one-line change instead of a rewrite.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Sequence

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Set IMD_API_KEY in the environment once IMD approves the account.
IMD_KEY = os.getenv("IMD_API_KEY")


# ----------------------------------------------------------------- data models


@dataclass(frozen=True)
class SeaHour:
    at: datetime
    wave_m: float | None
    period_s: float | None
    direction_deg: float | None
    swell_m: float | None


@dataclass(frozen=True)
class OceanographyHour:
    """Satellite-derived ocean state. SST and currents come from the marine
    model; chlorophyll needs a different source and is not wired yet."""

    at: datetime
    sst_c: float | None
    current_kn: float | None
    current_dir_deg: float | None
    chlorophyll: float | None = None      # mg/m3, pending a source
    # Height above GLOBAL mean sea level, not the chart datum a navigator uses.
    # Open-Meteo says so plainly and so must we: this tells you whether the
    # water is rising or falling, never how much of it is under the keel.
    sea_level_m: float | None = None


@dataclass(frozen=True)
class WeatherHour:
    at: datetime
    wind_kn: float | None
    gust_kn: float | None
    wind_dir_deg: float | None
    precip_mm: float | None
    cape: float | None          # thunderstorm energy — our lightning proxy
    visibility_m: float | None
    # A falling barometer is what separates an afternoon squall from a system
    # moving in. It is the one signal a fisherman has always read himself.
    pressure_msl: float | None = None


@dataclass(frozen=True)
class Reading:
    """Everything one agent fetched, plus where it came from."""

    hours: Sequence
    source: str
    fetched_at: datetime

    def cite(self, at: datetime) -> str:
        return f"{self.source} · {at:%d %b %H:%M} IST"


class Source(Protocol):
    name: str

    async def fetch(self, client: httpx.AsyncClient, lat: float, lon: float,
                    days: int) -> Reading: ...


# ----------------------------------------------------------------- ocean


class OpenMeteoOcean:
    name = "Open-Meteo wave model (DWD/NOAA)"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        r = await client.get(MARINE_URL, params={
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_period,wave_direction,swell_wave_height",
            "timezone": "Asia/Kolkata", "forecast_days": days,
        })
        r.raise_for_status()
        h = r.json()["hourly"]
        hours = [
            SeaHour(
                at=datetime.fromisoformat(t),
                wave_m=h["wave_height"][i],
                period_s=h["wave_period"][i],
                direction_deg=h["wave_direction"][i],
                swell_m=h["swell_wave_height"][i],
            )
            for i, t in enumerate(h["time"])
        ]
        return Reading(hours, self.name, datetime.now())


class IncoisOcean:
    """Placeholder — do not implement against a guessed endpoint.

    Open the INCOIS geoportal, watch the network tab, write this against a
    response you have actually seen.
    """

    name = "INCOIS Ocean State Forecast"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        raise NotImplementedError("INCOIS endpoint not yet confirmed")


# ----------------------------------------------------------------- weather


class OpenMeteoOceanography:
    """Sea surface temperature and surface currents.

    Same marine endpoint as the wave model, different variables. SST matters
    because fish aggregate along temperature fronts, and currents matter for
    drift — a boat that stops fishing does not stay where it stopped.
    """

    name = "Open-Meteo marine (Copernicus SST & currents)"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        r = await client.get(MARINE_URL, params={
            "latitude": lat, "longitude": lon,
            "hourly": "sea_surface_temperature,ocean_current_velocity,"
                      "ocean_current_direction,sea_level_height_msl",
            "timezone": "Asia/Kolkata", "forecast_days": days,
        })
        r.raise_for_status()
        h = r.json()["hourly"]

        def col(key):
            return h.get(key) or [None] * len(h["time"])

        sst, vel, dirn = col("sea_surface_temperature"), \
                         col("ocean_current_velocity"), col("ocean_current_direction")
        level = col("sea_level_height_msl")
        hours = [
            OceanographyHour(
                at=datetime.fromisoformat(t),
                sst_c=sst[i],
                # the API reports current velocity in km/h
                current_kn=round(vel[i] * 0.54, 2) if vel[i] is not None else None,
                current_dir_deg=dirn[i],
                sea_level_m=level[i],
            )
            for i, t in enumerate(h["time"])
        ]
        return Reading(hours, self.name, datetime.now())


class ChlorophyllSource:
    """Chlorophyll-a from NOAA CoastWatch ERDDAP — open, no key.

    Satellite ocean colour, so cloud creates gaps. The client tries the daily
    near-real-time product and falls back to the 8-day composite; if neither
    saw this pixel it returns nothing rather than a guess.
    """

    name = "NOAA CoastWatch chlorophyll (DINEOF gap-filled)"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        from . import chlorophyll as chl

        hit = await chl.around(client, lat, lon)
        if not hit:
            why = "; ".join(chl.LAST_ATTEMPTS) or "no reason recorded"
            raise RuntimeError(f"no pixel — {why}")

        # Ocean colour is a snapshot, not an hourly series. One reading is held
        # across the window and the citation names the image date, so nobody
        # mistakes a week-old composite for this morning's measurement.
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        hours = [
            OceanographyHour(at=now + timedelta(hours=i), sst_c=None,
                             current_kn=None, current_dir_deg=None,
                             chlorophyll=hit.mg_m3)
            for i in range(days * 24)
        ]
        return Reading(hours, hit.citation, datetime.now())


class OpenMeteoWeather:
    name = "Open-Meteo forecast (ECMWF/GFS)"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        r = await client.get(WEATHER_URL, params={
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
                      "precipitation,cape,visibility,pressure_msl",
            "timezone": "Asia/Kolkata", "forecast_days": days,
            "wind_speed_unit": "kn",
        })
        r.raise_for_status()
        h = r.json()["hourly"]
        hours = [
            WeatherHour(
                at=datetime.fromisoformat(t),
                wind_kn=h["wind_speed_10m"][i],
                gust_kn=h["wind_gusts_10m"][i],
                wind_dir_deg=h["wind_direction_10m"][i],
                precip_mm=h["precipitation"][i],
                cape=h["cape"][i],
                visibility_m=h["visibility"][i],
                pressure_msl=(h.get("pressure_msl") or [None] * len(h["time"]))[i],
            )
            for i, t in enumerate(h["time"])
        ]
        return Reading(hours, self.name, datetime.now())


class ImdWeather:
    """IMD Sea Area Bulletin + District Nowcast.

    Written against the published sample payloads, not yet against a live
    response — access is pending. Every field is read defensively; anything
    unreadable is skipped rather than guessed, and the caller falls back.
    """

    name = "IMD Sea Area Bulletin"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        from . import imd

        if not imd.IMD.configured:
            raise RuntimeError("IMD_API_KEY not set — account not approved yet")

        bulletin = await imd.IMD.sea_bulletin(client, lat, lon)
        if not bulletin:
            raise RuntimeError("IMD sea bulletin unavailable")

        row = bulletin["row"]
        gust = imd.parse_knots(
            row.get("wind") or row.get("Wind") or row.get("wind_speed"))
        now = datetime.now().replace(minute=0, second=0, microsecond=0)

        nowcast = await imd.IMD.district_nowcast(client)
        cape = None
        if nowcast:
            rows = nowcast if isinstance(nowcast, list) else nowcast.get("data", [])
            cats = {str(r.get("Category") or r.get("category") or "") for r in rows}
            if cats & imd.SEVERE_CATEGORIES:
                cape = 3000.0            # severe thunderstorm signalled
            elif cats & imd.THUNDER_CATEGORIES:
                cape = 1500.0            # thunderstorm likely

        # A bulletin is one statement about the next several hours, not an
        # hourly series. We hold it flat across the window and the citation
        # names the bulletin so nobody mistakes it for a model run.
        hours = [
            WeatherHour(at=now + timedelta(hours=i), wind_kn=gust, gust_kn=gust,
                        wind_dir_deg=None, precip_mm=None, cape=cape,
                        visibility_m=None)
            for i in range(days * 24)
        ]
        return Reading(hours, f"{self.name} — {bulletin['area']}", datetime.now())


class ImdOcean:
    """Sea state from the same bulletin, converted to metres.

    Coarser than a wave model: a bulletin describes a whole sea area in words.
    Used only when IMD is configured and preferred over a global model for
    being the official Indian source.
    """

    name = "IMD Sea Area Bulletin (sea state)"

    async def fetch(self, client, lat, lon, days=2) -> Reading:
        from . import imd

        if not imd.IMD.configured:
            raise RuntimeError("IMD_API_KEY not set — account not approved yet")

        bulletin = await imd.IMD.sea_bulletin(client, lat, lon)
        if not bulletin:
            raise RuntimeError("IMD sea bulletin unavailable")

        row = bulletin["row"]
        wave_m = imd.sea_state_to_m(
            row.get("sea") or row.get("Sea") or row.get("sea_condition"))
        if wave_m is None:
            raise RuntimeError("sea state not recognised in bulletin")

        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        hours = [
            SeaHour(at=now + timedelta(hours=i), wave_m=wave_m, period_s=None,
                    direction_deg=None, swell_m=None)
            for i in range(days * 24)
        ]
        return Reading(hours, f"{self.name} — {bulletin['area']}", datetime.now())


# ----------------------------------------------------------------- registry
#
# Preference order per capability. The first source that answers wins; the rest
# are fallbacks. Official Indian sources rank above global models — but a
# fallback that works beats an official source that is down, so the chain
# matters more than the ranking.

CATALOGUE: dict[str, list[dict]] = {
    "sea_state": [
        {"source": ImdOcean(),        "authority": "official",
         "coverage": "Indian sea areas", "resolution": "sea area, in words"},
        {"source": OpenMeteoOcean(),  "authority": "global model",
         "coverage": "worldwide",        "resolution": "hourly, ~25 km"},
        {"source": IncoisOcean(),     "authority": "official",
         "coverage": "Indian EEZ",       "resolution": "not yet wired"},
    ],
    "oceanography": [
        {"source": OpenMeteoOceanography(), "authority": "global model",
         "coverage": "worldwide", "resolution": "hourly, ~8 km"},
    ],
    "chlorophyll": [
        {"source": ChlorophyllSource(), "authority": "satellite",
         "coverage": "global ocean colour", "resolution": "4 km, daily or 8-day"},
    ],
    "weather": [
        {"source": ImdWeather(),      "authority": "official",
         "coverage": "Indian sea areas", "resolution": "bulletin, several hours"},
        {"source": OpenMeteoWeather(),"authority": "global model",
         "coverage": "worldwide",        "resolution": "hourly, ~11 km"},
    ],
}


def chain(capability: str) -> list:
    """Sources to try, in order, for one capability."""
    usable = []
    for entry in CATALOGUE.get(capability, []):
        src = entry["source"]
        if isinstance(src, (ImdOcean, ImdWeather)) and not IMD_KEY:
            continue                     # not approved yet
        if isinstance(src, IncoisOcean):
            continue                     # endpoint unconfirmed
        usable.append(src)
    return usable


# What the agents reach for. Kept as module-level names so existing callers and
# the test stubs keep working.
OCEAN: Source = chain("sea_state")[0]
WEATHER: Source = chain("weather")[0]
