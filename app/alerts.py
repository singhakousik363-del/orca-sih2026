"""
Proactive alerts.

Every other part of this system answers a question. This part is the one that
speaks without being asked, and the problem statement asks for it by name:
*proactively alerting users about adverse weather conditions or geofence
breaches near maritime boundaries*.

The reason it matters is not technical. A fisherman who checked at four in the
morning and went out has no reason to check again, and that is exactly when the
wind gets up. Asking him to remember to look is asking him to do the thing he
has no time for.

WHAT IT WATCHES

A boat registers a position and its length. Every interval the same risk agent
that answers questions is run again for that boat, and if the verdict has
turned worse than it was, an alert is raised. Only a change raises one — a boat
that was already told to stay ashore does not need telling every ten minutes,
and an alert that arrives when nothing has changed is one the user learns to
ignore.

WHAT THIS IS NOT

This is a poll, not a push. The app asks the server whether anything has
changed. Real push to a phone that is asleep needs Firebase or SMS, and SMS is
the one that reaches a feature phone in the middle of the Bay of Bengal — which
is the phone that actually matters here. That is a deployment question, not a
reasoning one, and the deck should say so rather than imply notifications
already reach a boat at sea.

The check interval is short here so a demonstration shows something within a
minute. In use it would be fifteen to thirty minutes, which is the rate at
which any of the underlying data changes.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from . import agents, geofence
from . import session as sess

# Short enough to show in a demo. Real use is 15-30 minutes; nothing underneath
# changes faster than that.
INTERVAL_SECONDS = 60

# A boat nobody has looked at for this long has probably gone home.
WATCH_TTL = 6 * 3600

# Verdicts ordered by how bad they are, so we can tell "got worse" from
# "changed". Unknown sits above go: losing the data is not reassurance.
SEVERITY = {"go": 0, "unknown": 1, "caution": 2, "stay": 3}


@dataclass
class Alert:
    kind: str                  # worsened | boundary
    text: str                  # already in the user's language
    verdict: str
    at: float = field(default_factory=time.time)


@dataclass
class Watch:
    session_id: str
    lat: float
    lon: float
    boat_length_m: float
    lang: str
    last_verdict: str = ""
    last_boundary: str = "clear"
    last_checked: float = 0.0
    touched: float = field(default_factory=time.time)


_watches: dict[str, Watch] = {}
_pending: dict[str, list[Alert]] = {}
_task: asyncio.Task | None = None


def watch(session_id: str, lat: float, lon: float,
          boat_length_m: float, lang: str) -> Watch:
    """Start watching a boat, or move one that has already been registered."""
    w = _watches.get(session_id)
    if w:
        w.lat, w.lon, w.boat_length_m, w.lang = lat, lon, boat_length_m, lang
        w.touched = time.time()
    else:
        w = Watch(session_id, lat, lon, boat_length_m, lang)
        _watches[session_id] = w
    return w


def unwatch(session_id: str) -> None:
    _watches.pop(session_id, None)
    _pending.pop(session_id, None)


def take(session_id: str) -> list[Alert]:
    """Hand over anything waiting, and clear it. Delivered once, not repeatedly."""
    return _pending.pop(session_id, [])


def watching(session_id: str) -> bool:
    return session_id in _watches


async def check_one(client: httpx.AsyncClient, w: Watch) -> Alert | None:
    """Re-run the same reasoning that answers a question, and see if it turned."""
    s = sess.get(w.session_id)
    s.lat, s.lon, s.boat_length_m = w.lat, w.lon, w.boat_length_m

    fence = geofence.check(w.lat, w.lon)

    # crossing towards a boundary is its own alert, whatever the weather says
    if fence.level != "clear" and fence.level != w.last_boundary:
        w.last_boundary = fence.level
        finding = agents.geofence_agent(w.lat, w.lon, always=True)
        if finding:
            from . import lang as lang_mod
            return Alert("boundary",
                         lang_mod.render(finding.phrase, w.lang),
                         "stay" if fence.level == "urgent" else "caution")
    w.last_boundary = fence.level

    decision = await agents.answer("__watch__", s, w.boat_length_m, w.lang)
    verdict = decision.verdict
    worse = SEVERITY.get(verdict, 0) > SEVERITY.get(w.last_verdict or "go", 0)
    w.last_verdict = verdict
    w.last_checked = time.time()

    # Only a turn for the worse. Telling someone every ten minutes that the sea
    # is still rough teaches them to ignore the next message, which is the one
    # that matters.
    return Alert("worsened", decision.answer, verdict) if worse else None


async def _loop() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=4.0, read=15.0,
                                                       write=4.0, pool=4.0),
                                 follow_redirects=True) as client:
        while True:
            await asyncio.sleep(INTERVAL_SECONDS)
            now = time.time()

            for sid in [k for k, w in _watches.items()
                        if now - w.touched > WATCH_TTL]:
                unwatch(sid)

            for w in list(_watches.values()):
                try:
                    alert = await check_one(client, w)
                except Exception:
                    # a failed check is not an alert; the next one will try again
                    continue
                if alert:
                    _pending.setdefault(w.session_id, []).append(alert)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


def summary() -> dict:
    return {
        "watching": len(_watches),
        "pending": sum(len(v) for v in _pending.values()),
        "interval_seconds": INTERVAL_SECONDS,
        "delivery": "poll — real push needs Firebase or SMS",
    }
