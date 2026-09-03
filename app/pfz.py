"""
Potential Fishing Zones.

INCOIS has issued PFZ advisories since the late 1990s, and the principle they
work on is documented plainly:

    "Regions in which SST gradients occur along with a higher chlorophyll
     concentration are considered to be strong potential for fishing."

Two things have to line up. A sharp change in sea temperature over a short
distance — a thermal front — is where water masses meet, and that convergence
concentrates nutrients and the plankton that feed on them. Chlorophyll measures
the plankton directly. Either signal alone means little; together they mean
fish are likely to gather.

So the method here is:

  1. Lay a grid over the water near the user.
  2. Get sea surface temperature at every grid point.
  3. Compute the temperature gradient at each point from its neighbours. A
     large gradient is a front.
  4. Get satellite chlorophyll over the same water.
  5. Score each cell on both, and require both.
  6. Discard anything across an international maritime boundary — a productive
     patch on the wrong side of the line is not an opportunity.

WHERE THIS DIFFERS FROM THE REAL THING, and it matters

  INCOIS uses NOAA-AVHRR infrared SST at about 1 km, and detects fronts with
  the Cayula-Cornillon histogram algorithm. We use a model SST field at about
  8 km and a plain gradient magnitude. A model field is smoothed, so our fronts
  are weaker and blurrier than the ones INCOIS sees, and small fronts vanish
  entirely.

  Because of that, cells are scored RELATIVE to the other cells in the same
  grid — "the strongest front around here today" — not against an absolute
  threshold. Claiming an absolute front strength from a smoothed model field
  would be dressing up a weaker measurement as a stronger one.

  This is an estimate built on INCOIS's published principle. It is not an
  INCOIS advisory, and the answer says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from . import chlorophyll as chl
from . import geofence

# Grid geometry. 5x5 at 0.15 degrees spans about 66 km, which is the working
# range of a day boat, and gives a gradient baseline of roughly 16 km — coarse
# enough to survive an 8 km model field, fine enough to see a real front.
GRID_N = 5
GRID_STEP = 0.15

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Below this the two signals do not really coincide and calling it a zone
# would be overselling a coincidence.
MIN_SCORE = 0.35

# How far a boat of each class can reasonably work from harbour and still get
# home. Rich water 72 km out is a serious undertaking for a nine-metre open
# boat and a routine morning for a trawler, and until now the estimate ignored
# the difference — which is the exact reasoning the rest of this system is
# built on.
#
# PLACEHOLDER, like the wave and wind limits. These come from what boats of
# each size are generally described as doing, not from anyone who fishes.
# Question three of the field interviews should replace them.
RANGE_KM = {"small": 40.0, "medium": 80.0, "trawler": 150.0}


@dataclass(frozen=True)
class Zone:
    lat: float
    lon: float
    score: float             # 0 to 1, relative to the rest of this grid
    sst_c: float
    front_c_per_10km: float
    chl_mg_m3: float
    distance_km: float
    bearing_deg: float

    @property
    def strength(self) -> str:
        if self.score >= 0.75:
            return "strong"
        if self.score >= 0.55:
            return "moderate"
        return "weak"


@dataclass(frozen=True)
class PfzResult:
    zones: list[Zone]
    sst_citation: str
    chl_citation: str
    note: str = ""


def _grid_points(lat: float, lon: float) -> list[tuple[float, float]]:
    half = GRID_N // 2
    return [(round(lat + dy * GRID_STEP, 4), round(lon + dx * GRID_STEP, 4))
            for dy in range(-half, half + 1)
            for dx in range(-half, half + 1)]


async def _sst_grid(client: httpx.AsyncClient, points):
    """One request for every grid point. Open-Meteo accepts comma-separated
    coordinate lists and answers with an array in the same order."""
    lats = ",".join(str(p[0]) for p in points)
    lons = ",".join(str(p[1]) for p in points)
    r = await client.get(MARINE_URL, params={
        "latitude": lats, "longitude": lons,
        "hourly": "sea_surface_temperature",
        "timezone": "Asia/Kolkata", "forecast_days": 1,
    }, timeout=httpx.Timeout(connect=4.0, read=10.0, write=4.0, pool=4.0))
    r.raise_for_status()

    payload = r.json()
    blocks = payload if isinstance(payload, list) else [payload]
    if len(blocks) != len(points):
        raise RuntimeError(f"asked for {len(points)} points, got {len(blocks)}")

    out = []
    for b in blocks:
        series = (b.get("hourly") or {}).get("sea_surface_temperature") or []
        valid = [v for v in series if v is not None]
        # the daily mean is steadier than any single hour, and a front is a
        # feature of the water mass rather than of the time of day
        out.append(sum(valid) / len(valid) if valid else None)
    return out


def _front_strength(sst: list, n: int) -> list:
    """Temperature gradient at each cell, in degrees per 10 km.

    Central differences where both neighbours exist, one-sided at the edges.
    A cell with no usable neighbour gets None rather than a guess.
    """
    # 0.15 degrees of latitude is about 16.6 km; longitude shrinks with
    # latitude but over a 66 km grid the difference is small enough to ignore
    step_km = GRID_STEP * 111.0
    grads = []

    for i in range(n * n):
        row, col = divmod(i, n)
        here = sst[i]
        if here is None:
            grads.append(None)
            continue

        def diff(a_idx, b_idx, span):
            a, b = sst[a_idx], sst[b_idx]
            if a is None or b is None:
                return None
            return (a - b) / span

        dx = None
        if col > 0 and col < n - 1:
            dx = diff(i + 1, i - 1, 2 * step_km)
        elif col > 0:
            dx = diff(i, i - 1, step_km)
        elif col < n - 1:
            dx = diff(i + 1, i, step_km)

        dy = None
        if row > 0 and row < n - 1:
            dy = diff(i + n, i - n, 2 * step_km)
        elif row > 0:
            dy = diff(i, i - n, step_km)
        elif row < n - 1:
            dy = diff(i + n, i, step_km)

        if dx is None and dy is None:
            grads.append(None)
        else:
            g = math.hypot(dx or 0.0, dy or 0.0)
            grads.append(g * 10.0)          # per 10 km reads better than per km
    return grads


def _nearest_chl(pixels, lat: float, lon: float, max_deg: float = 0.15):
    """Chlorophyll at the pixel closest to a grid cell, if one is close enough."""
    best, best_d = None, max_deg ** 2
    for p in pixels:
        d = (p.lat - lat) ** 2 + (p.lon - lon) ** 2
        if d < best_d:
            best, best_d = p, d
    return best.mg_m3 if best else None


def recentre(result: "PfzResult", boat_lat: float, boat_lon: float,
             boat_class: str = "trawler") -> "PfzResult":
    """Recompute distance and bearing from a different boat position, and drop
    what this boat cannot reach.

    The zones themselves are a property of the water and can be cached. How far
    away they are is a property of who is asking, and cannot be — two boats in
    the same harbour are close enough, but a cached distance would follow the
    first caller's position around. Whether the trip is sensible belongs here
    too, for the same reason: it depends on the boat, not the water.

    The default is the most permissive class, so a caller that forgets to say
    what boat it is asking about gets everything rather than silently losing
    zones.
    """
    moved = [
        Zone(lat=z.lat, lon=z.lon, score=z.score, sst_c=z.sst_c,
             front_c_per_10km=z.front_c_per_10km, chl_mg_m3=z.chl_mg_m3,
             distance_km=round(geofence.distance_km((boat_lat, boat_lon),
                                                    (z.lat, z.lon)), 1),
             bearing_deg=round(geofence.bearing_deg((boat_lat, boat_lon),
                                                    (z.lat, z.lon))))
        for z in result.zones
    ]
    limit = RANGE_KM.get(boat_class, RANGE_KM["trawler"])
    reachable = [z for z in moved if z.distance_km <= limit]
    beyond = len(moved) - len(reachable)

    note = result.note
    if beyond:
        far = (f"{beyond} zone" + ("s" if beyond != 1 else "")
               + f" beyond a {boat_class} boat's range")
        note = f"{note} · {far}" if note else far

    reachable.sort(key=lambda z: (-z.score, z.distance_km))
    return PfzResult(zones=reachable, sst_citation=result.sst_citation,
                     chl_citation=result.chl_citation, note=note)


async def find(client: httpx.AsyncClient, lat: float, lon: float,
               boat_lat: float | None = None, boat_lon: float | None = None):
    """Estimate fishing zones near a point. Returns PfzResult, or raises."""
    origin_lat = boat_lat if boat_lat is not None else lat
    origin_lon = boat_lon if boat_lon is not None else lon

    points = _grid_points(lat, lon)

    sst = await _sst_grid(client, points)
    if sum(v is not None for v in sst) < GRID_N * 2:
        raise RuntimeError("not enough sea surface temperature over this water")

    span = GRID_N * GRID_STEP / 2 + 0.1
    pixels, chl_cite = await chl.grid(client, lat, lon, box=span)
    if not pixels:
        raise RuntimeError(f"no chlorophyll grid — {chl_cite}")

    fronts = _front_strength(sst, GRID_N)

    # Score relative to this grid. An absolute threshold would be pretending a
    # smoothed model field measures front strength the way 1 km infrared does.
    usable = [(i, fronts[i], _nearest_chl(pixels, *points[i]))
              for i in range(len(points))
              if fronts[i] is not None and sst[i] is not None]
    usable = [(i, f, c) for i, f, c in usable if c is not None]
    if not usable:
        raise RuntimeError("temperature and chlorophyll do not overlap here")

    max_front = max(f for _, f, _ in usable) or 1e-9
    max_chl = max(c for _, _, c in usable) or 1e-9

    zones: list[Zone] = []
    skipped_boundary = 0

    for i, front, c in usable:
        p_lat, p_lon = points[i]

        # A rich patch on the far side of an international line is not an
        # opportunity, it is an arrest. Drop it before it can be recommended.
        fence = geofence.check(p_lat, p_lon)
        if fence.level != "clear":
            skipped_boundary += 1
            continue

        f_norm = front / max_front
        c_norm = c / max_chl
        # geometric mean: a cell needs both signals, not one strong one
        score = math.sqrt(f_norm * c_norm)
        if score < MIN_SCORE:
            continue

        d_km = geofence.distance_km((origin_lat, origin_lon), (p_lat, p_lon))
        bearing = geofence.bearing_deg((origin_lat, origin_lon), (p_lat, p_lon))

        zones.append(Zone(
            lat=p_lat, lon=p_lon, score=round(score, 3),
            sst_c=round(sst[i], 1), front_c_per_10km=round(front, 3),
            chl_mg_m3=round(c, 2),
            distance_km=round(d_km, 1), bearing_deg=round(bearing),
        ))

    # Best first, and among equals the nearest — the whole point of a fishing
    # advisory is catch per unit effort, and 20 km of extra fuel for the same
    # water is a loss.
    zones.sort(key=lambda z: (-z.score, z.distance_km))

    # Adjacent cells are one patch of water, not three zones. Reporting them
    # separately would overstate how much choice the user has.
    spread: list[Zone] = []
    for z in zones:
        if all(math.hypot(z.lat - k.lat, z.lon - k.lon) > GRID_STEP * 1.5
               for k in spread):
            spread.append(z)
    zones = spread

    note = ""
    if skipped_boundary:
        near_line = (f"{skipped_boundary} productive cell"
                     + ("s" if skipped_boundary != 1 else "")
                     + " skipped for being near an international boundary")
        note = f"{note} · {near_line}" if note else near_line

    return PfzResult(
        zones=zones[:3],
        sst_citation="Open-Meteo marine SST (model field, ~8 km)",
        chl_citation=chl_cite,
        note=note,
    )
