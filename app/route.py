"""
A lower-risk way across.

The problem statement asks for route optimisation — *what is the safest route
to reach a fishing zone*. This is the part where it is easiest to promise more
than can be delivered, so the promise is set first.

WHAT THIS IS NOT

It is not navigation. There is no depth here, no sandbar, no wreck, no channel
marker, no other vessel, no tidal stream atlas. A skipper who followed a line
drawn by this instead of his own knowledge of the ground would be worse off,
not better.

WHAT IT IS

A grid is laid between where the boat is and where it wants to go. Each cell
is scored on what this system can actually see — wave height, gusts, how near
it passes an international boundary or a sanctuary, and whether the current is
with the boat or across it. Then the cheapest path across that grid is found.

The result is a direction and a rough distance, offered as "this way is easier
than straight across", not as a course to steer. That is a real thing to say:
going twelve kilometres further to keep out of a steep beam sea is the kind of
decision this data can genuinely inform, and the kind a chart cannot make for
you.

HOW LAND IS AVOIDED

There is no coastline dataset here. There does not need to be one: the marine
model returns nothing over land, so a cell with no wave height is a cell that
is not sea. That falls out of the same bulk request that provides the wave
cost, and it is honest in a way a coarse polygon would not be — it is the
model's own opinion about where the water is.

WHAT IT COSTS

One request. Open-Meteo takes a list of coordinates, so the whole grid arrives
at once, the way the fishing-zone estimate already does it.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import httpx

from . import geofence, protected

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# About 5.5 km a cell. Finer would be a false precision — the wave model
# itself is coarser than this.
CELL_DEG = 0.05

# A corridor this much wider than the straight line, so the search has room to
# go around something without wandering.
MARGIN_DEG = 0.18

# Above this many cells the request gets large and the answer stops being
# quick enough to be useful.
# 400 points was too many. The route request competes for the same budget as
# everything else, and a grid that large made the whole answer late — the
# fishing-zone estimate timed out and the route then had nowhere to go, so the
# user got neither. Fewer, coarser cells give a direction just as well.
MAX_CELLS = 180

# What each hazard adds to the cost of crossing a cell. These are weights, not
# measurements: they say a boundary matters more than a wave, which is a
# judgement, and one the deck should own rather than dress up.
W_WAVE = 3.0            # per metre of significant wave height
W_GUST = 0.06           # per knot of gust
W_BOUNDARY = 40.0       # within the warning distance of an international line
W_PROTECTED = 25.0      # within the warning distance of a sanctuary
W_CURRENT = 1.5         # per knot, and only across the track, not along it

# The least any cell can cost to cross, used to keep the A* guide admissible.
CHEAPEST_CELL = 1.0


@dataclass(frozen=True)
class Leg:
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    legs: list[Leg]
    distance_km: float
    direct_km: float
    worst_wave_m: float
    avoided: list[str]          # what the detour keeps clear of
    citation: str

    @property
    def detour_km(self) -> float:
        return round(self.distance_km - self.direct_km, 1)


def _grid_axes(a: tuple[float, float], b: tuple[float, float]):
    lat0 = min(a[0], b[0]) - MARGIN_DEG
    lat1 = max(a[0], b[0]) + MARGIN_DEG
    lon0 = min(a[1], b[1]) - MARGIN_DEG
    lon1 = max(a[1], b[1]) + MARGIN_DEG

    step = CELL_DEG
    # widen the step rather than refuse, if the trip is a long one
    while ((lat1 - lat0) / step + 1) * ((lon1 - lon0) / step + 1) > MAX_CELLS:
        step *= 1.5

    lats = [round(lat0 + i * step, 4)
            for i in range(int((lat1 - lat0) / step) + 1)]
    lons = [round(lon0 + j * step, 4)
            for j in range(int((lon1 - lon0) / step) + 1)]
    return lats, lons, step


async def _sea_grid(client: httpx.AsyncClient, points):
    """Wave, gust and current at every grid point, in one request.

    A point with no wave height is land: the marine model simply has no water
    there. That is the land mask, and it arrives free with the cost data.
    """
    lats = ",".join(str(p[0]) for p in points)
    lons = ",".join(str(p[1]) for p in points)
    r = await client.get(MARINE_URL, params={
        "latitude": lats, "longitude": lons,
        "hourly": "wave_height,ocean_current_velocity,ocean_current_direction",
        "timezone": "Asia/Kolkata", "forecast_days": 1,
    }, timeout=httpx.Timeout(connect=4.0, read=10.0, write=4.0, pool=4.0))
    r.raise_for_status()

    payload = r.json()
    blocks = payload if isinstance(payload, list) else [payload]
    if len(blocks) != len(points):
        raise RuntimeError(f"asked for {len(points)} points, got {len(blocks)}")

    out = []
    for b in blocks:
        h = b.get("hourly") or {}
        def first(name):
            series = h.get(name) or []
            vals = [v for v in series[:6] if v is not None]
            return max(vals) if vals else None
        out.append({
            "wave": first("wave_height"),
            "current": first("ocean_current_velocity"),
            "current_dir": first("ocean_current_direction"),
        })
    return out


def _cell_cost(cell: dict, lat: float, lon: float, heading: float,
               gust_kn: float) -> tuple[float, str | None]:
    """What it costs to cross one cell, and what hazard drove that cost."""
    if cell["wave"] is None:
        return math.inf, "land"          # the model has no water here

    cost = 1.0 + W_WAVE * cell["wave"] + W_GUST * gust_kn
    worst = None

    fence = geofence.check(lat, lon)
    if fence.level != "clear":
        cost += W_BOUNDARY * (2.0 if fence.level == "urgent" else 1.0)
        worst = "boundary"

    # Only what a boat can actually be prosecuted for. The warning band that
    # is right for "a sanctuary is near you" is wrong here: the Sundarbans are
    # modelled as a 35 km circle with a 15 km band around it, which shades
    # nearly half of the water off Namkhana. Charging every one of those cells
    # the same penalty makes them all equally bad, and a search that sees no
    # difference between cells picks any path at all.
    #
    # So routing charges for being inside the area, not near it, and the
    # penalty rises steeply as the boat gets closer to the middle.
    near = protected.check(lat, lon)
    if near and near.distance_km <= 0.0:
        cost += W_PROTECTED * (2.0 if near.closed else 1.0)
        worst = worst or "protected"

    # A current across the track is what makes a crossing uncomfortable; one
    # along it is a help. Only the across-track part is charged for.
    if cell["current"] and cell["current_dir"] is not None:
        knots = cell["current"] * 0.54
        across = abs(math.sin(math.radians(cell["current_dir"] - heading)))
        cost += W_CURRENT * knots * across

    return cost, worst


async def find(client: httpx.AsyncClient, start: tuple[float, float],
               goal: tuple[float, float], gust_kn: float = 0.0) -> Route:
    """The cheapest way across the grid between two points. Raises if there is none."""
    lats, lons, step = _grid_axes(start, goal)
    points = [(la, lo) for la in lats for lo in lons]
    cells = await _sea_grid(client, points)

    n_lat, n_lon = len(lats), len(lons)
    grid = {}
    for idx, (la, lo) in enumerate(points):
        grid[(lats.index(la), lons.index(lo))] = cells[idx]

    def nearest_node(p):
        i = min(range(n_lat), key=lambda k: abs(lats[k] - p[0]))
        j = min(range(n_lon), key=lambda k: abs(lons[k] - p[1]))
        return (i, j)

    s, g = nearest_node(start), nearest_node(goal)
    heading = geofence.bearing_deg(start, goal)

    def km_between(a, b):
        return geofence.distance_km((lats[a[0]], lons[a[1]]),
                                    (lats[b[0]], lons[b[1]]))

    # A* needs its guide in the same units as its cost, and never larger than
    # the true remaining cost, or it explores in the wrong order and settles
    # for a path that merely reaches the goal.
    #
    # Cost is (cell weight x kilometres), and the cheapest a cell can be is
    # CHEAPEST_CELL, so remaining kilometres times that is the largest guide
    # that is still safe. Plain kilometres — which is what this used at first —
    # is far too weak once weights run to five or six, and the search wandered
    # south before turning back east.
    open_set = [(0.0, s)]
    came, best = {}, {s: 0.0}
    hazards: dict = {}

    while open_set:
        _, node = heapq.heappop(open_set)
        if node == g:
            break
        i, j = node
        for di, dj in ((1,0), (-1,0), (0,1), (0,-1),
                       (1,1), (1,-1), (-1,1), (-1,-1)):
            nxt = (i + di, j + dj)
            if not (0 <= nxt[0] < n_lat and 0 <= nxt[1] < n_lon):
                continue
            cell = grid.get(nxt)
            if cell is None:
                continue
            cost, hazard = _cell_cost(cell, lats[nxt[0]], lons[nxt[1]],
                                      heading, gust_kn)
            if math.isinf(cost):
                continue
            step_km = km_between(node, nxt)
            tentative = best[node] + cost * step_km
            if tentative < best.get(nxt, math.inf):
                best[nxt] = tentative
                came[nxt] = node
                if hazard:
                    hazards[nxt] = hazard
                # The guide has to be in the same units as the cost, and never
                # larger than the true remaining cost, or A* stops finding the
                # cheapest path. Cost is (weight x km) and the cheapest any
                # cell can be is 1.0, so plain remaining kilometres is the
                # largest guide that is still safe.
                heapq.heappush(
                    open_set,
                    (tentative + CHEAPEST_CELL * km_between(nxt, g), nxt))

    if g not in came and g != s:
        raise RuntimeError("no way across that is not land")

    path, node = [], g
    while node != s:
        path.append(node)
        node = came[node]
    path.append(s)
    path.reverse()

    legs = [Leg(lats[i], lons[j]) for i, j in path]
    distance = sum(km_between(path[k], path[k + 1]) for k in range(len(path) - 1))

    # Compare with the shortest path this grid can express, not with the great
    # circle. A grid can only step along its own axes and diagonals, so even a
    # perfectly straight crossing measures longer than the direct line — and
    # reporting that difference as a detour would invent one that is not there.
    di, dj = abs(g[0] - s[0]), abs(g[1] - s[1])
    diag, straight = min(di, dj), abs(di - dj)
    unit_diag = km_between(s, (s[0] + (1 if g[0] > s[0] else -1),
                               s[1] + (1 if g[1] > s[1] else -1))) if diag else 0.0
    unit_str = km_between(s, (s[0] + (1 if di > dj else 0),
                              s[1] + (0 if di > dj else 1))) if straight else 0.0
    direct = round(diag * unit_diag + straight * unit_str, 1)
    waves = [grid[n]["wave"] for n in path if grid[n]["wave"] is not None]

    # what the detour keeps clear of, judged on the cells it did not take
    avoided = sorted({h for h in hazards.values()} - {"land"})

    return Route(
        legs=legs,
        distance_km=round(distance, 1),
        direct_km=round(direct, 1),
        worst_wave_m=round(max(waves), 1) if waves else 0.0,
        avoided=avoided,
        citation="Open-Meteo marine (waves and currents) · land from the model's own coverage",
    )
