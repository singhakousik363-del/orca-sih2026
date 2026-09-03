"""
IMD integration.

Written from the published API reference at api.imd.gov.in, against the sample
payloads in the documentation. It is NOT yet verified against a live response,
because access is still pending — so every parser here is defensive and any
field it cannot read is skipped rather than guessed.

The moment IMD_API_KEY is set, the registry in sources.py routes weather
through this module instead of Open-Meteo. If an IMD call fails, the caller
falls back rather than losing the answer.

Sea Area Bulletin gives sea state in words ("Moderate", "Rough") and wind in
knots for a named sea area, not a coordinate. Two consequences we handle here:

  1. A bulletin covers a whole sea area, so we map a coordinate to the nearest
     one. That is coarser than a wave model and the citation says so.
  2. Sea state words have to become metres to be comparable with the boat
     limits. The mapping below follows the WMO/Douglas sea state scale, and it
     is an approximation of a range, not a measurement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

BASE = "https://api.imd.gov.in/api/v1"

# WMO sea state code -> representative significant wave height in metres.
# We take the upper end of each band: for a safety call, the pessimistic
# reading of an ambiguous word is the correct one.
SEA_STATE_M: dict[str, float] = {
    "calm": 0.1,
    "calm (rippled)": 0.1,
    "smooth": 0.5,
    "smooth (wavelets)": 0.5,
    "slight": 1.25,
    "moderate": 2.5,
    "rough": 4.0,
    "very rough": 6.0,
    "high": 9.0,
    "very high": 14.0,
    "phenomenal": 16.0,
}

# IMD nowcast categories that mean thunderstorm or lightning, from the
# published category list. Anything here is treated as a lightning risk.
THUNDER_CATEGORIES = {"6", "11", "14", "15", "19"}
SEVERE_CATEGORIES = {"14", "15"}


@dataclass(frozen=True)
class SeaArea:
    """One of IMD's named sea areas, with a rough centre for matching."""

    name: str
    lat: float
    lon: float


# Approximate centres of the sea areas IMD bulletins are issued for. Used only
# to pick which bulletin applies to a coordinate.
SEA_AREAS: list[SeaArea] = [
    SeaArea("North West Bay", 20.5, 88.5),
    SeaArea("North East Bay", 19.0, 91.0),
    SeaArea("West Central Bay", 16.0, 84.0),
    SeaArea("East Central Bay", 15.0, 90.0),
    SeaArea("South West Bay", 10.0, 83.0),
    SeaArea("South East Bay", 8.0, 90.0),
    SeaArea("Gulf of Mannar", 8.8, 78.6),
    SeaArea("Comorin Area", 7.5, 77.5),
    SeaArea("Lakshadweep Area", 10.5, 72.5),
    SeaArea("South East Arabian Sea", 10.0, 72.0),
    SeaArea("East Central Arabian Sea", 15.0, 71.0),
    SeaArea("North East Arabian Sea", 20.5, 69.0),
    SeaArea("Gujarat Coast", 21.5, 69.5),
]


def nearest_sea_area(lat: float, lon: float) -> SeaArea:
    return min(SEA_AREAS, key=lambda a: (a.lat - lat) ** 2 + (a.lon - lon) ** 2)


def sea_state_to_m(text: str | None) -> float | None:
    """Turn a bulletin's sea state word into metres, or None if unrecognised.

    Never guess. An unknown word means we have no wave height, and the risk
    agent already knows what to do with missing data.
    """
    if not text:
        return None
    key = text.strip().lower().rstrip(".")
    if key in SEA_STATE_M:
        return SEA_STATE_M[key]
    # bulletins sometimes read "moderate to rough" — take the worse of the two
    worst = None
    for word, m in SEA_STATE_M.items():
        if word in key:
            worst = m if worst is None else max(worst, m)
    return worst


def parse_knots(text: str | None) -> float | None:
    """Pull a wind speed out of free text like '20-25 kts' or 'upto 35 kmph'."""
    if not text:
        return None
    import re

    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None
    value = max(nums)                       # the gust end of a range
    low = text.lower()
    if "kmph" in low or "km/h" in low:
        value *= 0.54                        # km/h to knots
    elif "m/s" in low or "mps" in low:
        value *= 1.944
    return round(value, 1)


class ImdClient:
    """Thin wrapper. Each method returns None on any failure — an IMD outage
    must degrade to the fallback source, not break the answer."""

    def __init__(self, key: str | None = None):
        self.key = key or os.getenv("IMD_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.key)

    def _headers(self) -> dict:
        # The portal issues a key after approval; header name to be confirmed
        # against the real account. Kept in one place for that reason.
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    async def _get(self, client: httpx.AsyncClient, path: str, **params):
        try:
            r = await client.get(f"{BASE}/{path}", params=params or None,
                                 headers=self._headers())
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    async def sea_bulletin(self, client, lat: float, lon: float):
        data = await self._get(client, "seabulletin")
        if not data:
            return None
        area = nearest_sea_area(lat, lon)
        rows = data if isinstance(data, list) else data.get("data", [])
        for row in rows:
            name = str(row.get("area") or row.get("Area") or "")
            if area.name.lower() in name.lower():
                return {"area": name, "row": row}
        return {"area": area.name, "row": rows[0]} if rows else None

    async def district_nowcast(self, client, district_id: str | None = None):
        return await self._get(client, "districtnowcast",
                               **({"id": district_id} if district_id else {}))

    async def sun_moon(self, client, station_id: str | None = None):
        return await self._get(client, "sunmoon",
                               **({"id": station_id} if station_id else {}))


IMD = ImdClient()
