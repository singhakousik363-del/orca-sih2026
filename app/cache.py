"""
Caching, keyed to how often each source actually changes.

The app took four to five seconds to answer, and a fisherman deciding at 4 a.m.
whether to launch will not wait that long. Almost all of it was network time,
and almost none of it bought anything: the slowest source is also the one that
changes least.

    chlorophyll   one satellite image per day, already two or three days old
    sea state     hourly steps, the model reruns roughly every three hours
    weather       hourly steps, reruns roughly hourly

So a chlorophyll fetch repeated within the same day cannot produce a different
answer. It can only produce the same answer more slowly.

TWO RULES THAT MATTER MORE THAN THE SPEED

  A cached value carries its own age. Every reading already shows the timestamp
  of the data behind it, and caching must not quietly turn "measured at 09:00"
  into something that looks live. The citation is unchanged by caching, because
  it describes the data, not the fetch.

  Nothing is cached across a location change. Keys include the coordinates,
  rounded only as far as the source's own resolution — a 4 km satellite product
  genuinely cannot distinguish two points 2 km apart, but it can distinguish
  two harbours, and pretending otherwise would answer for the wrong water.

IMD asks in its implementation guidelines that clients cache to limit request
volume during severe weather, which is exactly when everyone asks at once. This
module is how that commitment is kept.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

# How long a value stays usable, per capability. Set from how often the source
# behind it is refreshed, not from what would look fastest.
TTL_SECONDS: dict[str, int] = {
    "chlorophyll": 6 * 3600,     # one image a day; six hours is still cautious
    "sea_state": 45 * 60,        # model reruns about every three hours
    "oceanography": 45 * 60,
    "weather": 20 * 60,          # reruns about hourly, and drives the verdict
    "pfz": 45 * 60,              # follows sea state and chlorophyll
}

# How finely each source can actually tell places apart. Rounding a key more
# coarsely than this would answer for water the user did not ask about.
GRID_DEG: dict[str, float] = {
    "chlorophyll": 0.1,          # 4 km product, sampled over a 28 km box
    "sea_state": 0.1,
    "oceanography": 0.1,
    "weather": 0.1,
    "pfz": 0.1,
}

DEFAULT_TTL = 15 * 60
DEFAULT_GRID = 0.1
MAX_ENTRIES = 500                # a few hundred harbours' worth; then oldest go


@dataclass
class Entry:
    value: Any
    stored_at: float
    ttl: int

    @property
    def age(self) -> float:
        return time.time() - self.stored_at

    @property
    def fresh(self) -> bool:
        return self.age < self.ttl


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    saved_ms: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


_STORE: dict[str, Entry] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
STATS = Stats()


def key_for(capability: str, lat: float, lon: float, extra: str = "") -> str:
    g = GRID_DEG.get(capability, DEFAULT_GRID)
    return (f"{capability}:{round(lat / g) * g:.3f},{round(lon / g) * g:.3f}"
            + (f":{extra}" if extra else ""))


def _evict_if_full() -> None:
    if len(_STORE) <= MAX_ENTRIES:
        return
    # drop expired first, then the oldest — a store this small never needs
    # anything cleverer
    for k in [k for k, e in _STORE.items() if not e.fresh]:
        _STORE.pop(k, None)
    while len(_STORE) > MAX_ENTRIES:
        oldest = min(_STORE, key=lambda k: _STORE[k].stored_at)
        _STORE.pop(oldest, None)


async def get_or_fetch(capability: str, lat: float, lon: float, fetch,
                       extra: str = ""):
    """Return a cached value, or run `fetch` and remember what it gave.

    Returns (value, from_cache, age_seconds).

    Concurrent callers asking for the same key wait on one lock rather than all
    hitting the source: during severe weather everyone asks at once, which is
    exactly when the source can least afford it.
    """
    k = key_for(capability, lat, lon, extra)

    entry = _STORE.get(k)
    if entry and entry.fresh:
        STATS.hits += 1
        return entry.value, True, entry.age

    lock = _LOCKS.setdefault(k, asyncio.Lock())
    async with lock:
        # someone else may have filled it while we waited
        entry = _STORE.get(k)
        if entry and entry.fresh:
            STATS.hits += 1
            return entry.value, True, entry.age

        started = time.perf_counter()
        value = await fetch()
        took = int((time.perf_counter() - started) * 1000)

        STATS.misses += 1
        _STORE[k] = Entry(value, time.time(), TTL_SECONDS.get(capability, DEFAULT_TTL))
        _evict_if_full()

        # what a later hit on this key will save
        STATS.saved_ms = max(STATS.saved_ms, took)
        return value, False, 0.0


def clear() -> None:
    _STORE.clear()
    _LOCKS.clear()


def snapshot() -> dict:
    fresh = sum(1 for e in _STORE.values() if e.fresh)
    return {
        "entries": len(_STORE),
        "fresh": fresh,
        "hits": STATS.hits,
        "misses": STATS.misses,
        "hit_rate": round(STATS.hit_rate, 3),
        "ttl_seconds": TTL_SECONDS,
    }
