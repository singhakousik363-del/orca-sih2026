"""
What changed in the water.

The problem statement asks, among its example questions, why fish production
has declined in an area. That question deserves care, because the honest answer
is narrower than the question.

WHAT THIS CAN SAY

Two things drive where fish are, and both are visible from orbit: how much
plankton is in the water, and how warm it is. If the chlorophyll off a stretch
of coast is a third of what it was this time last year, that is a real finding
and it is worth telling someone.

WHAT THIS CANNOT SAY

It cannot say why the catch dropped. A catch is fish minus effort minus gear
minus market minus everything else that happens on a boat, and none of that is
in a satellite image. Overfishing does not show up in ocean colour. Nor does a
change in mesh size, or a fuel price that kept half the fleet ashore.

So the answer says what the water did and then says, in the same breath, what
it has not looked at. A fisherman who is told "the plankton is down by half"
has learned something. One who is told "that is why you caught less" has been
misled, and would be right to stop trusting the rest of it.

HOW THE COMPARISON IS MADE

The same calendar window, this year and last. Not the last month against the
month before it — the Bay of Bengal in June is a different sea from the Bay of
Bengal in March, and comparing across a monsoon would find a difference every
time and mean nothing by it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

import httpx

from . import chlorophyll as chl

# How much water to average over. Wide enough that cloud gaps and a few bad
# pixels do not decide the answer.
BOX_DEG = 0.5

# How long a window to compare. A month smooths out weather; a week would be
# reporting one cloudy fortnight against another.
WINDOW_DAYS = 30

# Ocean colour is noisy and DINEOF is an interpolation. Below this a difference
# is not worth reporting as a change.
MEANINGFUL_CHANGE = 0.20        # 20 per cent


@dataclass(frozen=True)
class Window:
    label: str                  # "now" or "last_year"
    start: date
    end: date
    chlorophyll: float | None
    pixels: int


@dataclass(frozen=True)
class Comparison:
    now: Window
    before: Window
    citation: str

    @property
    def change(self) -> float | None:
        """Fractional change in chlorophyll. -0.4 means down by 40 per cent."""
        if not self.now.chlorophyll or not self.before.chlorophyll:
            return None
        return (self.now.chlorophyll - self.before.chlorophyll) / self.before.chlorophyll

    @property
    def direction(self) -> str:
        c = self.change
        if c is None:
            return "unknown"
        if abs(c) < MEANINGFUL_CHANGE:
            return "steady"
        return "down" if c < 0 else "up"


def _url(ds: dict, lat: float, lon: float, start: date, end: date) -> str:
    """A dated slice, rather than the usual last-N-days one."""
    lat0, lat1 = round(lat - BOX_DEG, 3), round(lat + BOX_DEG, 3)
    lon0, lon1 = round(lon - BOX_DEG, 3), round(lon + BOX_DEG, 3)
    alt = "[0]" if ds["altitude"] else ""
    return (f"{ds['host']}/{ds['id']}.json"
            f"?chlor_a[({start}T00:00:00Z):3:({end}T00:00:00Z)]{alt}"
            f"[({lat0}):4:({lat1})][({lon0}):4:({lon1})]")


async def _window(client: httpx.AsyncClient, lat: float, lon: float,
                  label: str, start: date, end: date):
    """Median chlorophyll over one window, or None."""
    for ds in chl.DATASETS:
        if not ds["gap_filled"]:
            continue                    # a cloud-gapped month is not a mean
        try:
            r = await client.get(_url(ds, lat, lon, start, end),
                                 headers=chl.HEADERS,
                                 timeout=httpx.Timeout(connect=4.0, read=12.0,
                                                       write=4.0, pool=4.0))
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            table = r.json()["table"]
            i_v = table["columnNames"].index("chlor_a")
            values = [float(row[i_v]) for row in table["rows"]
                      if chl._valid(row[i_v])]
        except Exception:
            continue
        if len(values) < chl.MIN_PIXELS:
            continue
        # median, because river sediment near a delta pulls a mean upward and
        # would show as productivity that is not there
        return Window(label, start, end, round(median(values), 2), len(values)), ds
    return Window(label, start, end, None, 0), None


async def compare(client: httpx.AsyncClient, lat: float, lon: float,
                  today: date | None = None):
    """This calendar window against the same one a year ago."""
    today = today or date.today()

    # Satellite products lag by a few days, so end the window before the gap.
    end_now = today - timedelta(days=4)
    start_now = end_now - timedelta(days=WINDOW_DAYS)

    end_then = end_now - timedelta(days=365)
    start_then = start_now - timedelta(days=365)

    now, ds = await _window(client, lat, lon, "now", start_now, end_now)
    before, _ = await _window(client, lat, lon, "last_year", start_then, end_then)

    label = ds["label"] if ds else "satellite ocean colour"
    cite = (f"{label} · {start_now}–{end_now} against {start_then}–{end_then}"
            f" · {now.pixels} and {before.pixels} px")
    return Comparison(now, before, cite)
