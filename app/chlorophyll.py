"""
Chlorophyll-a from NOAA CoastWatch ERDDAP. Open access, no key.

This is the missing half of a fishing-zone estimate: SST shows where the
temperature fronts are, chlorophyll shows where the plankton is, and fish
gather where the two line up.

Everything below was settled by probing the servers rather than guessing —
see `app/find_erddap.py`, which is kept so the next person can re-run it.

WHAT THE PROBE ESTABLISHED

  1. coastwatch.noaa.gov returns 403 to a plain Python client and 200 to a
     browser-shaped user agent. So the user agent is not optional. We send the
     conventional "Mozilla/5.0 (compatible; ...)" form, which is how a
     well-behaved automated client identifies itself — it names the project and
     its purpose rather than pretending to be a person.

  2. coastwatch.pfeg.noaa.gov and upwell.pfeg.noaa.gov time out entirely from
     an Indian consumer connection. Dropped.

  3. polarwatch.noaa.gov mirrors the same NOAA products and answers without any
     user agent at all, so it is the fallback host.

  4. The DINEOF products are the important find. Ordinary daily ocean colour
     over the Bay of Bengal is almost entirely cloud: a plain daily query at
     Digha returned 252 pixels, all empty. The gap-filled DINEOF product for
     the same day and place returned 42 usable pixels out of 63.

`last` is an INDEX, so it takes no parentheses: `[last-6:1:last]`. Latitude and
longitude are requested by value, in parentheses. A correct query mixes both.

TWO HONESTY NOTES, both of which belong in the deck

  DINEOF is interpolation, not measurement. It reconstructs what the sensor
  could not see from the surrounding water and the recent past. That is a
  reasonable estimate and it is standard practice, but it is not the same as a
  satellite having looked at that pixel. The citation says which product was
  used so the difference is visible.

  Ocean colour over turbid coastal water reads high. Near the Hooghly mouth,
  suspended river sediment is misread as chlorophyll, so values off Digha and
  Namkhana are inflated. Treat the band as relative — is this water richer than
  the water next to it — not as an absolute measurement.

Verify:  python -m app.chlorophyll
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

DEBUG = bool(os.getenv("ORCA_DEBUG"))

# The conventional form for an automated client: Mozilla-compatible prefix so
# the server's filter passes it, then an honest identification of who we are.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ORCA/0.1; +SIH 2026 PS SIH26176; "
        "Siliguri Institute of Technology; academic marine safety project)"
    ),
    "Accept": "application/json",
}

COASTWATCH = "https://coastwatch.noaa.gov/erddap/griddap"
POLARWATCH = "https://polarwatch.noaa.gov/erddap/griddap"
OCEANWATCH = "https://oceanwatch.pifsc.noaa.gov/erddap/griddap"

# Ordered by preference. All four were confirmed reachable and returning values
# from an Indian connection on 30 Aug 2026.
DATASETS = [
    {
        "id": "noaacwNPPN20VIIRSDINEOFDaily",
        "host": COASTWATCH,
        "label": "NOAA VIIRS chlorophyll, gap-filled (DINEOF), daily 4 km",
        "days_back": 3,
        "altitude": True,
        "gap_filled": True,
    },
    {
        "id": "noaacwNPPN20S3ASCIDINEOF2kmDaily",
        "host": COASTWATCH,
        "label": "NOAA VIIRS + Sentinel-3 chlorophyll, gap-filled (DINEOF), daily 2 km",
        "days_back": 3,
        "altitude": True,
        "gap_filled": True,
    },
    {
        # same products, different host — answers even without a user agent
        "id": "noaacwNPPN20VIIRSDINEOFDaily",
        "host": POLARWATCH,
        "label": "NOAA VIIRS chlorophyll, gap-filled (DINEOF) [polarwatch mirror]",
        "days_back": 3,
        "altitude": True,
        "gap_filled": True,
    },
    {
        # true measurement, no interpolation, but a week old and holey
        "id": "aqua_chla_8d_2018_0",
        "host": OCEANWATCH,
        # index.html answers but griddap refused the connection on 30 Aug 2026.
        # Kept as a last resort in case that was transient.
        "label": "MODIS Aqua chlorophyll, 8-day composite (measured, not gap-filled)",
        "days_back": 2,
        "altitude": False,          # this product has no altitude dimension
        "gap_filled": False,
    },
]

BOX_DEG = 0.25       # about 28 km each way — a day boat's working range
STRIDE = 1           # take every pixel

# The first run returned only 6 to 9 usable pixels per location, because a
# stride of 2 discarded three quarters of a grid that cloud had already thinned.
# A median of six numbers is not worth much. Stride 1 over a slightly wider box
# gives roughly four times the sample for the same one request.

MIN_PIXELS = 4       # below this we report the value but flag it as thin

# A dataset can go stale without going down. The MODIS 8-day product on
# oceanwatch answered happily on 30 Aug 2026 with an image from April 2022 —
# its `last` index is frozen four years back. Nothing in the response says so;
# only the timestamp gives it away. Anything older than this is refused,
# because serving 2022 water as today's is worse than serving nothing.
MAX_AGE_DAYS = 21


def band_for(mg_m3: float) -> str:
    """Productivity band for a concentration. Open ocean sits near 0.1 mg/m3;
    coastal water rich enough to be worth fishing is usually above 0.5. Turbid
    river water reads higher than it really is — see the module note."""
    if mg_m3 < 0.1:
        return "very low"
    if mg_m3 < 0.3:
        return "low"
    if mg_m3 < 1.0:
        return "moderate"
    if mg_m3 < 3.0:
        return "high"
    return "very high"


@dataclass(frozen=True)
class Chlorophyll:
    mg_m3: float
    dataset: str
    when: str            # ISO timestamp of the image actually used
    pixels: int          # valid pixels behind the average
    gap_filled: bool     # interpolated where cloud hid the water
    lat: float
    lon: float

    @property
    def band(self) -> str:
        return band_for(self.mg_m3)

    @property
    def thin(self) -> bool:
        """Too few pixels for the median to mean much."""
        return self.pixels < MIN_PIXELS

    @property
    def age_days(self) -> float | None:
        return _age_days(self.when)

    @property
    def citation(self) -> str:
        note = " · gap-filled" if self.gap_filled else " · measured"
        sample = f" · {self.pixels} px" + (" (thin sample)" if self.thin else "")
        age = self.age_days
        old = f" · {age:.0f} days old" if age is not None and age >= 1 else ""
        return f"{self.dataset} ({self.when[:10]}){note}{sample}{old}"


def build_url(ds: dict, lat: float, lon: float, box: float | None = None) -> str:
    b = box or BOX_DEG
    lat0, lat1 = round(lat - b, 3), round(lat + b, 3)
    lon0, lon1 = round(lon - b, 3), round(lon + b, 3)
    alt = "[0]" if ds["altitude"] else ""
    # keep the response a sane size as the box grows
    stride = STRIDE if b <= BOX_DEG else (2 if b <= BOX_DEG * 2 else 4)
    return (f"{ds['host']}/{ds['id']}.json"
            f"?chlor_a[last-{ds['days_back']}:1:last]{alt}"
            f"[({lat0}):{stride}:({lat1})][({lon0}):{stride}:({lon1})]")


def _age_days(iso: str) -> float | None:
    """How old is this image, in days? None if the timestamp is unreadable."""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400
    except Exception:
        return None


def _valid(v) -> bool:
    if v is None:
        return False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    # ERDDAP fills unseen pixels with NaN; the sensor's valid range is
    # 0.001 to 1000 mg/m3, so anything outside that is not a measurement
    return not math.isnan(f) and 0.001 <= f <= 1000.0


async def _query(client: httpx.AsyncClient, ds: dict, lat: float, lon: float,
                 box: float | None = None):
    url = build_url(ds, lat, lon, box)
    try:
        r = await client.get(url, headers=HEADERS,
                             timeout=httpx.Timeout(connect=4.0, read=10.0,
                                                   write=4.0, pool=4.0))
    except Exception as e:
        LAST_ATTEMPTS.append(f"{ds['id']}: {type(e).__name__}")
        if DEBUG:
            print(f"[chl] {ds['id']}: {type(e).__name__}")
        return None

    if r.status_code != 200:
        body = r.text.strip().replace("\n", " ")[:110]
        LAST_ATTEMPTS.append(f"{ds['id']}: HTTP {r.status_code}")
        if DEBUG:
            print(f"[chl] {ds['id']}: HTTP {r.status_code} · {body}")
        return None

    try:
        table = r.json()["table"]
        cols, rows = table["columnNames"], table["rows"]
        i_t, i_v = cols.index("time"), cols.index("chlor_a")
    except Exception:
        LAST_ATTEMPTS.append(f"{ds['id']}: unparsed response")
        if DEBUG:
            print(f"[chl] {ds['id']}: unparsed · {r.text[:100]}")
        return None

    # group valid pixels by timestamp, take the most recent day that has any
    by_time: dict[str, list[float]] = {}
    for row in rows:
        if _valid(row[i_v]):
            by_time.setdefault(str(row[i_t]), []).append(float(row[i_v]))

    if not by_time:
        LAST_ATTEMPTS.append(f"{ds['id']}: {len(rows)} px all cloud")
        if DEBUG:
            print(f"[chl] {ds['id']}: {len(rows)} pixels, all cloud or gap")
        return None

    when = max(by_time)

    age = _age_days(when)
    if age is None or age > MAX_AGE_DAYS:
        shown = f"{age:.0f} days old" if age is not None else "unreadable date"
        LAST_ATTEMPTS.append(f"{ds['id']}: stale ({shown})")
        if DEBUG:
            print(f"[chl] {ds['id']}: refusing {when[:10]} — {shown}")
        return None

    values = by_time[when]

    # Median, not mean. A few sediment-contaminated pixels near a river mouth
    # can drag a mean far above what the water is actually doing.
    values.sort()
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    if DEBUG:
        print(f"[chl] {ds['id']}: {len(values)}/{len(rows)} valid on {when[:10]}")

    return Chlorophyll(round(median, 3), ds["label"], when, len(values),
                       ds["gap_filled"], lat, lon)


LAST_ATTEMPTS: list[str] = []      # why each dataset failed, for the caller


async def at_point(client: httpx.AsyncClient, lat: float, lon: float,
                   box: float | None = None):
    """Chlorophyll for the water around a position, or None if nothing saw it.

    Datasets sit on different hosts and any one can be unreachable, so they are
    tried concurrently — otherwise one server timing out delays every fallback
    behind it. Preference order is still honoured when picking the winner.
    """
    LAST_ATTEMPTS.clear()
    tasks = [asyncio.create_task(_query(client, ds, lat, lon, box))
             for ds in DATASETS]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()

    for r in results:
        if isinstance(r, Chlorophyll):
            return r
    return None


async def around(client: httpx.AsyncClient, lat: float, lon: float):
    """Same thing, but widen the search before giving up.

    A box that lands mostly on shore, or under a solid bank of cloud, returns
    nothing at the first size and plenty at the next. Two extra requests are
    cheaper than telling a fisherman we have no idea.
    """
    for box in (BOX_DEG, BOX_DEG * 2, BOX_DEG * 4):
        hit = await at_point(client, lat, lon, box=box)
        if hit:
            return hit
    return None


# --------------------------------------------------------------- grid

@dataclass(frozen=True)
class Pixel:
    lat: float
    lon: float
    mg_m3: float


async def _grid_one(client: httpx.AsyncClient, ds: dict, lat: float, lon: float,
                    box: float):
    """One dataset's worth of pixels, or None."""
    url = build_url(ds, lat, lon, box)
    try:
        r = await client.get(url, headers=HEADERS,
                             timeout=httpx.Timeout(connect=4.0, read=12.0,
                                                   write=4.0, pool=4.0))
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        table = r.json()["table"]
        cols, rows = table["columnNames"], table["rows"]
        i_t = cols.index("time")
        i_la, i_lo = cols.index("latitude"), cols.index("longitude")
        i_v = cols.index("chlor_a")
    except Exception:
        return None

    by_time: dict[str, list[Pixel]] = {}
    for row in rows:
        if _valid(row[i_v]):
            by_time.setdefault(str(row[i_t]), []).append(
                Pixel(float(row[i_la]), float(row[i_lo]), float(row[i_v])))
    if not by_time:
        return None

    when = max(by_time)
    age = _age_days(when)
    if age is None or age > MAX_AGE_DAYS:
        return None

    pixels = by_time[when]
    if len(pixels) < MIN_PIXELS:
        return None

    note = " · gap-filled" if ds["gap_filled"] else " · measured"
    cite = (f"{ds['label']} ({when[:10]}){note} · {len(pixels)} px"
            + (f" · {age:.0f} days old" if age >= 1 else ""))
    return pixels, cite


async def grid(client: httpx.AsyncClient, lat: float, lon: float,
               box: float = 0.4):
    """Every valid chlorophyll pixel in a box, not just a summary.

    at_point() answers "how rich is the water here". A fishing-zone estimate
    needs "where is it richest", which is a different question and needs the
    pattern, not the median.

    The datasets are tried at the same time, not one after another. Doing this
    in series once cost eighty seconds and then failed: four datasets on hosts
    that can each hang, each with its own read timeout, adding up. A fisherman
    would have given up long before, and an answer nobody waits for is not an
    answer.

    Returns (pixels, citation) or (None, reason).
    """
    tasks = [asyncio.create_task(_grid_one(client, ds, lat, lon, box))
             for ds in DATASETS]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for t in tasks:
            t.cancel()

    # preference order still decides the winner
    for r in results:
        if isinstance(r, tuple):
            return r
    return None, "no chlorophyll grid available"


# --------------------------------------------------------------- verification

async def _check():
    globals()["DEBUG"] = True
    spots = [("Digha", 21.6, 87.6), ("Namkhana", 21.7, 88.3),
             ("Rameswaram", 9.3, 79.3), ("Veraval", 20.8, 70.3),
             ("Kochi", 9.9, 76.1), ("Visakhapatnam", 17.6, 83.4)]
    print("Example query:\n  " + build_url(DATASETS[0], 21.6, 87.6) + "\n")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for name, la, lo in spots:
            print(f"--- {name} ({la}, {lo})")
            hit = await around(client, la, lo)
            if hit:
                print(f"    {hit.mg_m3:>8.3f} mg/m3  {hit.band:10s}")
                print(f"    {hit.citation}\n")
            else:
                print("    no value from any dataset\n")


if __name__ == "__main__":
    asyncio.run(_check())
