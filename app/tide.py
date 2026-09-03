"""
Tide, read as a direction rather than a height.

Open-Meteo now carries sea level, and its own documentation is blunt about what
that number is worth:

  - the model runs at about 8 km, which cannot resolve a complex coastline, and
    tides are intensely local;
  - the heights are referenced to global mean sea level, not to the chart datum
    (lowest astronomical tide) that navigation uses, so the two cannot be
    compared at all.

So a figure like "tide 1.2 m" from this source is not a number anyone should
act on, and presenting one next to a real depth would be worse than saying
nothing. Publishing it would also be the kind of thing that looks impressive
until a judge who sails asks what datum it is referenced to.

What survives that, and is what a fisherman actually uses, is the *shape*: is
the water rising or falling, and when does it turn. Crossing a river bar or
getting over a shallow mouth is timed against the turn, not against a figure.
The model's error in absolute height mostly cancels when you ask which way it
is going, because that is a difference between two of its own values rather
than a comparison with a chart.

So this module reports direction and the next turn, and never a height.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# A tide that moves less than this over an hour is between states rather than
# clearly doing either. Roughly 5 cm/h, well inside the model's own noise.
FLAT_M_PER_HOUR = 0.05


@dataclass(frozen=True)
class Tide:
    state: str                  # rising | falling | slack
    turns_at: datetime | None   # when it next changes direction
    turns_to: str               # what it turns into — "high" or "low"


def _turning_points(hours: list) -> list[tuple[datetime, str]]:
    """Where the sea level stops going one way and starts going the other."""
    points: list[tuple[datetime, str]] = []
    for i in range(1, len(hours) - 1):
        before, here, after = (hours[i - 1].sea_level_m,
                               hours[i].sea_level_m,
                               hours[i + 1].sea_level_m)
        if before is None or here is None or after is None:
            continue
        if here >= before and here >= after:
            points.append((hours[i].at, "high"))
        elif here <= before and here <= after:
            points.append((hours[i].at, "low"))
    return points


def read(hours: list, at: datetime) -> Tide | None:
    """Which way the tide is going at a moment, and when it next turns.

    `hours` is the oceanography reading; anything without a sea level is
    skipped rather than interpolated.
    """
    usable = [h for h in hours if h.sea_level_m is not None]
    if len(usable) < 3:
        return None

    # the pair straddling the moment we care about
    after = [h for h in usable if h.at >= at]
    if len(after) < 2:
        return None
    now, next_hour = after[0], after[1]

    change = next_hour.sea_level_m - now.sea_level_m
    if abs(change) < FLAT_M_PER_HOUR:
        state = "slack"
    else:
        state = "rising" if change > 0 else "falling"

    turn = next((t for t in _turning_points(usable) if t[0] > now.at), None)
    return Tide(state=state,
                turns_at=turn[0] if turn else None,
                turns_to=turn[1] if turn else "")
