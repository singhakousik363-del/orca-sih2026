"""
Geofence — how far is this boat from a line it must not cross.

The India-Bangladesh maritime boundary matters most off South 24 Parganas,
where our field interviews are being done. The coordinates below are an
approximate polyline for demonstration; before the finale, replace them with
the published IMBL geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_R_KM = 6371.0

# Three international maritime boundaries, because a fisherman off Rameswaram
# is not at risk from the Bangladesh line and one off Namkhana is not at risk
# from the Sri Lanka line.
#
# ALL THREE ARE APPROXIMATE DEMONSTRATION GEOMETRY. Replace each with the
# published IMBL coordinates before the finale, and say so in the deck until
# you have. A boundary warning that is wrong by a few kilometres is worse than
# no warning, because it will be trusted.

BOUNDARIES: dict[str, dict] = {
    "bangladesh": {
        "name": "India–Bangladesh IMBL",
        "line": [(21.62, 89.12), (21.30, 89.08), (20.95, 89.02),
                 (20.55, 88.96), (20.10, 88.90)],
    },
    "sri_lanka": {
        # Palk Bay through the Katchatheevu area into the Gulf of Mannar —
        # the stretch where Indian fishermen are most often detained.
        "name": "India–Sri Lanka IMBL",
        "line": [(10.30, 79.85), (10.00, 79.70), (9.60, 79.58),
                 (9.38, 79.52), (9.00, 79.15), (8.60, 78.80)],
    },
    "pakistan": {
        # Sir Creek and seaward. The most dangerous line on the Indian coast.
        "name": "India–Pakistan boundary (Sir Creek)",
        "line": [(23.95, 68.15), (23.70, 68.02), (23.45, 67.88),
                 (23.10, 67.70), (22.75, 67.55)],
    },
}

# kept for callers that still want the Bay of Bengal line by itself
IMBL_SEGMENT: list[tuple[float, float]] = BOUNDARIES["bangladesh"]["line"]

WARN_KM = 12.0     # start warning
URGENT_KM = 5.0    # turn now


@dataclass(frozen=True)
class Geofence:
    distance_km: float
    bearing_to_line_deg: float
    level: str          # "clear" | "warn" | "urgent"
    turn_to_deg: float  # heading that increases distance
    boundary: str = ""  # which line — the user needs to know which country
    line: list = None   # the nearest line, for drawing on a map


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _point_to_segment_km(p, a, b) -> tuple[float, tuple[float, float]]:
    """Distance from p to segment ab, plus the closest point on it.

    Flat-earth projection is fine at these scales (tens of km).
    """
    lat0 = math.radians(p[0])
    to_xy = lambda q: (q[1] * math.cos(lat0) * 111.32, q[0] * 110.57)

    px, py = to_xy(p)
    ax, ay = to_xy(a)
    bx, by = to_xy(b)

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return distance_km(p, a), a

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return distance_km(p, closest), closest


def check(lat: float, lon: float) -> Geofence:
    """Distance to the nearest international maritime boundary, whichever it is."""
    best_km = float("inf")
    best_pt = BOUNDARIES["bangladesh"]["line"][0]
    best_name = ""
    best_line: list = []

    for meta in BOUNDARIES.values():
        line = meta["line"]
        for a, b in zip(line, line[1:]):
            d, pt = _point_to_segment_km((lat, lon), a, b)
            if d < best_km:
                best_km, best_pt = d, pt
                best_name, best_line = meta["name"], line

    to_line = bearing_deg((lat, lon), best_pt)
    away = (to_line + 180) % 360

    level = "urgent" if best_km <= URGENT_KM else "warn" if best_km <= WARN_KM else "clear"
    return Geofence(round(best_km, 1), round(to_line), level, round(away),
                    best_name, best_line)


def compass_bn(deg: float) -> str:
    """Bearing to a Bengali compass word — a heading in degrees is useless
    to someone steering a boat by eye."""
    names = ["উত্তর", "উত্তর-পূর্ব", "পূর্ব", "দক্ষিণ-পূর্ব",
             "দক্ষিণ", "দক্ষিণ-পশ্চিম", "পশ্চিম", "উত্তর-পশ্চিম"]
    return names[int((deg + 22.5) % 360 // 45)]
