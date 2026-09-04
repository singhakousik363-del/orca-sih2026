"""
The agents.

Findings carry facts, never sentences. The language layer turns them into text
at the very end. That is why adding a language is a phrase pack rather than a
fork of the reasoning.

Every number in an answer was fetched from a source and carries its citation.
The model produces no forecasts, so it cannot invent one.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import httpx

from . import geofence, lang, sources
from . import session as sess
from .lang import Phrase
from .session import Resolved, Session, Turn

BoatClass = Literal["small", "medium", "trawler"]

# PLACEHOLDER THRESHOLDS — replace with what fishermen actually say. The field
# interviews exist to fill in this dictionary.
WAVE_LIMIT_M: dict[BoatClass, float] = {"small": 1.5, "medium": 2.5, "trawler": 4.0}
WIND_LIMIT_KN: dict[BoatClass, float] = {"small": 20.0, "medium": 27.0, "trawler": 33.0}

# How long the whole round of agents gets. Past this an answer is no longer
# useful, and a partial answer that says what is missing beats a complete one
# nobody waited for.
ANSWER_BUDGET_S = 12.0

# The route runs last, on what is left. It is the one agent whose absence
# costs the least: without it the answer is still an answer.
ROUTE_BUDGET_S = 5.0

CAPE_THUNDER = 1000.0
CAPE_SEVERE = 2500.0

# A system moving in shows itself as a barometer falling fast alongside a wind
# that is already strong. Either alone is ordinary weather; together they are
# the signature every fisherman's grandfather knew to read.
#
# We report the signature and send the user to IMD. We do not say "cyclone":
# naming one is the India Meteorological Department's statutory function, and a
# student project declaring a cyclone from a global model field would be both
# wrong and out of order. What we can honestly say is that the barometer is
# dropping and the official warning is the one to check.
PRESSURE_FALL_HPA = 3.0        # over three hours — a recognised trigger
GALE_KN = 34.0                 # Beaufort 8

# Sentence-final punctuation differs by script.
DANDA = {"bn", "hi", "mr", "or"}


def _stop(language: str) -> str:
    return "।" if language in DANDA else "."


def classify_boat(length_m: float) -> BoatClass:
    return "small" if length_m <= 9 else "medium" if length_m <= 15 else "trawler"


# ------------------------------------------------------------------ findings


@dataclass
class Finding:
    agent: str
    phrase: Phrase          # the fact, not the sentence
    headline: str           # English, for logs and the evidence list
    citation: str
    blocking: bool = False
    fell_back: list = field(default_factory=list)   # sources tried and skipped
    # a fishing zone has a place on the map; everything else is a statement
    # about the water the boat is already in
    zone_lat: float | None = None
    zone_lon: float | None = None
    zone_km: float | None = None
    zone_strength: str = ""
    legs: list = field(default_factory=list)   # a route, for the map


# Stable identifiers for the interface to translate against. The display name
# is English so logs stay readable; the key is what the language pack keys on.
def _failure_word(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "src_timeout"
    """Turn an exception into something a person can read.

    "RuntimeError" and "HTTPStatusError" were being shown verbatim in a
    Bengali interface. The class name tells a developer something and the user
    nothing, so the trace carries a word and the English detail keeps the class
    name for the logs.
    """
    name = type(exc).__name__
    if "Timeout" in name:
        return "src_timeout"
    if "Connect" in name or "Network" in name:
        return "src_unreachable"
    if "HTTPStatus" in name or "Status" in name:
        return "src_refused"
    return "src_failed"


AGENT_KEYS = {
    "User Interaction": "user_interaction",
    "Marine Data Discovery": "discovery",
    "Planner": "planner",
    "Ocean": "ocean",
    "Weather": "weather",
    "Ocean Analytics": "analytics",
    "PFZ": "pfz",
    "Geospatial": "geospatial",
    "Trends": "trends",
    "Route": "route",
    "Risk": "risk",
    "Visualization": "visualization",
    "Reporting": "reporting",
    "Total": "total",
}


@dataclass
class Trace:
    """One agent's turn on stage. The pipeline is the product's main claim —
    if it is invisible, nobody believes it ran."""

    agent: str
    role: str
    status: str            # ran | skipped | failed
    detail: str
    ms: int = 0
    parallel: bool = False
    # Detail split into pieces the interface can translate. Each piece is
    # either {"t": "verbatim"} for a product name, {"w": "key"} for a word, or
    # {"n": 3, "w": "key"} for a count with its noun. Without this the panel
    # ends up half translated, which reads worse than not translating at all.
    parts: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return AGENT_KEYS.get(self.agent, self.agent.lower().replace(" ", "_"))


@dataclass
class Decision:
    verdict: Literal["go", "caution", "stay", "unknown"]
    when_key: str
    answer: str
    lang: str
    findings: list[Finding] = field(default_factory=list)
    map: dict = field(default_factory=dict)
    context_carried: list[str] = field(default_factory=list)
    trace: list[Trace] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ planner


@dataclass
class Task:
    needs_trends: bool = False
    needs_ocean: bool = True
    needs_weather: bool = True
    needs_geofence: bool = False
    needs_pfz: bool = False
    needs_route: bool = False
    start: datetime = field(default_factory=datetime.now)
    end: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=12))
    when_key: str = "today"
    intent: str = "safety"


BOUNDARY_WORDS = ("সীমা", "সীমানা", "सीमा", "સીમા", "ସୀମା",
                  "எல்லை", "సరిహద్దు", "അതിർത്തി", "boundary", "border")
# "why is the catch down", "fish has decreased", "কেন কমে গেল"
# "which way should I go" — a question about getting somewhere.
ROUTE_WORDS = ("পথ", "রাস্তা", "কোন দিকে", "যাব কীভাবে",
               "रास्ता", "मार्ग", "किस दिशा",
               "मार्गा", "कोणत्या दिशेने",
               "રસ્તો", "કઈ દિશા",
               "ପଥ", "ରାସ୍ତା", "କେଉଁ ଦିଗ",
               "பாதை", "வழி", "எந்த திசை",
               "మార్గం", "దారి", "ఏ దిశ",
               "വഴി", "പാത", "ഏത് ദിശ",
               "route", "which way", "safest way", "how do i get")

DECLINE_WORDS = ("কম", "কমে", "কমেছে", "কমল", "কেন",
                 "कम", "क्यों", "घट",
                 "कमी", "का",
                 "ઓછું", "કેમ", "ઘટ",
                 "କମ", "କାହିଁକି",
                 "குறை", "ஏன்",
                 "తగ్గ", "ఎందుకు",
                 "കുറ", "എന്തുകൊണ്ട്",
                 "why", "decline", "declin", "less", "fewer", "drop")

FISHING_WORDS = ("মাছ", "মৎস",                    # bn
                 "मछली", "मत्स्य",                  # hi
                 "मासे",                            # mr
                 "માછલી", "મત્સ્ય",                 # gu
                 "ମାଛ",                             # or
                 "மீன்",                            # ta
                 "చేప", "మత్స్య",                   # te
                 "മത്സ്യ", "മീൻ", "മീന",            # ml
                 "fish", "pfz",
                 # a catch is what a fisherman calls it in English, and
                 # "why is the catch down" never says the word fish
                 "catch", "haul", "মাছ ধরা", "মৎস্য উৎপাদন")


def plan(resolved: Resolved) -> Task:
    """Intent to sub-tasks. Rules, not a model — a demo must not fail because
    an LLM timed out. The Planner agent slot is here when we swap it in."""
    q = resolved.question.lower()
    now = datetime.now()

    intent = resolved.intent
    if not intent:
        if any(w in resolved.question or w in q for w in ROUTE_WORDS):
            intent = "route"
        elif any(w in resolved.question or w in q for w in BOUNDARY_WORDS):
            intent = "boundary"
        elif any(w in resolved.question or w in q for w in FISHING_WORDS):
            # "where are the fish" and "why are there fewer fish" both mention
            # fish, and they are not the same question. The second is about a
            # season; the first is about this morning.
            intent = ("decline"
                      if any(w in resolved.question or w in q
                             for w in DECLINE_WORDS)
                      else "fishing")
        else:
            intent = "safety"

    if intent == "decline":
        # a question about a season, not about today's weather
        return Task(needs_ocean=False, needs_weather=False, needs_geofence=False,
                    needs_pfz=False, needs_trends=True,
                    start=now, end=now + timedelta(hours=2),
                    when_key="now", intent=intent)

    if intent == "route":
        # a route needs somewhere to go, and the zone estimate is what knows
        # where that is; the weather sets the cost of crossing
        return Task(needs_ocean=True, needs_weather=True, needs_geofence=False,
                    needs_pfz=True, needs_route=True,
                    start=now, end=now + timedelta(hours=6),
                    when_key="now", intent=intent)

    if intent == "boundary":
        return Task(needs_ocean=False, needs_weather=False, needs_geofence=True,
                    needs_pfz=False, start=now, end=now + timedelta(hours=2),
                    when_key="now", intent=intent)

    if resolved.when_key == "tomorrow":
        base = (now + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
        window = (base, base + timedelta(hours=10))
    elif resolved.when_key == "dayafter":
        base = (now + timedelta(days=2)).replace(hour=4, minute=0, second=0, microsecond=0)
        window = (base, base + timedelta(hours=10))
    else:
        window = (now, now + timedelta(hours=12))

    # Keywords, not positions. A field added in the middle of this dataclass
    # silently reshuffles every positional call — which is exactly what just
    # happened.
    return Task(needs_ocean=True, needs_weather=True, needs_geofence=False,
                needs_pfz=(intent == "fishing"),
                needs_trends=(intent == "decline"),
                start=window[0], end=window[1],
                when_key=resolved.when_key, intent=intent)


# ------------------------------------------------------------------ workers


async def discover(client, capability: str, lat: float, lon: float, days: int):
    """Marine Data Discovery agent.

    Walks the source chain for a capability and returns the first that answers,
    plus a note of what it skipped. This is what "autonomously discovering,
    retrieving and integrating datasets" means in practice: the worker agents
    do not know or care which provider they got.
    """
    from . import cache

    tried: list[str] = []
    for src in sources.chain(capability):
        try:
            reading, cached, age = await cache.get_or_fetch(
                capability, lat, lon,
                lambda s=src: s.fetch(client, lat, lon, days=days),
                extra=str(days))
            if cached:
                tried.append(f"__cached__{int(age)}")
            return reading, tried
        except Exception as e:
            # keep the message, not just the type — "RuntimeError" alone told us
            # nothing when chlorophyll went quiet
            tried.append(f"{src.name.split('(')[0].strip()}: "
                         f"{type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError(
        f"no source answered for {capability} — tried " + "; ".join(tried))


async def ocean_agent(client, lat, lon, task, boat) -> Finding | None:
    reading, skipped = await discover(client, "sea_state", lat, lon, days=4)
    window = [h for h in reading.hours
              if task.start <= h.at <= task.end and h.wave_m is not None]
    if not window:
        return None

    worst = max(window, key=lambda h: h.wave_m)
    limit = WAVE_LIMIT_M[boat]

    return Finding(
        agent="Ocean",
        phrase=Phrase("waves", {"wave": f"{worst.wave_m:.1f}", "limit": f"{limit:.1f}"}),
        headline=f"waves up to {worst.wave_m:.1f} m (limit {limit:.1f} m for {boat})",
        citation=reading.cite(worst.at),
        blocking=worst.wave_m > limit,
        fell_back=skipped,
    )


async def weather_agent(client, lat, lon, task, boat) -> list[Finding]:
    reading, skipped = await discover(client, "weather", lat, lon, days=4)
    window = [h for h in reading.hours if task.start <= h.at <= task.end]
    if not window:
        return []

    out: list[Finding] = []

    gusts = [h for h in window if h.gust_kn is not None]
    if gusts:
        worst = max(gusts, key=lambda h: h.gust_kn)
        limit = WIND_LIMIT_KN[boat]
        out.append(Finding(
            agent="Weather",
            phrase=Phrase("wind", {"gust": f"{worst.gust_kn:.0f}"}),
            headline=f"gusts to {worst.gust_kn:.0f} kn (limit {limit:.0f} kn)",
            citation=reading.cite(worst.at),
            blocking=worst.gust_kn > limit,
            fell_back=skipped,
        ))

    # a falling barometer under an already strong wind
    pressures = [h for h in window if h.pressure_msl is not None]
    if len(pressures) >= 4:
        worst_fall, fall_at = 0.0, None
        for i in range(len(pressures) - 3):
            drop = pressures[i].pressure_msl - pressures[i + 3].pressure_msl
            if drop > worst_fall:
                worst_fall, fall_at = drop, pressures[i + 3].at
        strong = max((h.gust_kn or 0) for h in window) >= GALE_KN
        if worst_fall >= PRESSURE_FALL_HPA and strong:
            out.append(Finding(
                agent="Weather",
                phrase=Phrase("system", {"hpa": f"{worst_fall:.0f}"}),
                headline=(f"pressure falling {worst_fall:.1f} hPa/3h with gale "
                          f"force gusts — check the IMD bulletin"),
                citation=reading.cite(fall_at or window[0].at),
                blocking=True,
            ))

    capes = [h for h in window if h.cape is not None and h.cape >= CAPE_THUNDER]
    if capes:
        first = min(capes, key=lambda h: h.at)
        severe = max(h.cape for h in capes) >= CAPE_SEVERE
        out.append(Finding(
            agent="Weather",
            # hour24 is carried raw; the language layer picks the word for it
            phrase=Phrase("thunder", {"hour24": first.at.hour,
                                      "hour": f"{lang.hour12(first.at.hour)}"}),
            headline=f"thunderstorm potential from {first.at:%H:%M}"
                     + (" (severe)" if severe else ""),
            citation=reading.cite(first.at),
            blocking=severe,
            fell_back=skipped,
        ))

    return out


async def ocean_analytics_agent(client, lat, lon, task,
                                notes: dict | None = None) -> list[Finding]:
    """Ocean Analytics agent — satellite-derived state rather than forecasts.

    SST and currents are not safety limits, so nothing here blocks a decision.
    They are context: temperature tells a fisherman where fish are likely to be,
    and current tells him where his boat will drift while he works.
    """
    reading, skipped = await discover(client, "oceanography", lat, lon, days=3)
    window = [h for h in reading.hours if task.start <= h.at <= task.end]
    if not window:
        return []

    out: list[Finding] = []

    temps = [h for h in window if h.sst_c is not None]
    if temps:
        mid = temps[len(temps) // 2]
        out.append(Finding(
            agent="Ocean Analytics",
            phrase=Phrase("sst", {"sst": f"{mid.sst_c:.1f}"}),
            headline=f"SST {mid.sst_c:.1f} °C",
            citation=reading.cite(mid.at),
            fell_back=skipped,
        ))

    # Chlorophyll is its own source and often has no pixel (cloud), so it is
    # fetched separately. Whether it worked goes into the returned note so the
    # panel can say why it is missing — a silent gap is indistinguishable from
    # a bug, which is exactly the trap this project keeps falling into.
    chl_note = ""
    try:
        # Ask about the fishing ground, not the harbour basin. A box drawn
        # around a harbour is half land, and land has no ocean colour.
        from . import ports as _ports
        near = _ports.nearest(lat, lon)
        chl_lat, chl_lon = _ports.seaward(near)
        chl_reading, _ = await discover(client, "chlorophyll",
                                        chl_lat, chl_lon, days=1)
        chl = next((h.chlorophyll for h in chl_reading.hours
                    if h.chlorophyll is not None), None)
        if chl is None:
            chl_note = "chlorophyll: source returned no value"
        else:
            from .chlorophyll import band_for
            band = band_for(chl)
            out.append(Finding(
                agent="Ocean Analytics",
                phrase=Phrase("chl", {"band": band, "v": f"{chl:.2f}"}),
                headline=f"chlorophyll {chl:.2f} mg/m3 ({band})",
                citation=chl_reading.source,
            ))
    except Exception as e:
        chl_note = f"chlorophyll — {str(e)[:400]}"
        if os.getenv("ORCA_DEBUG"):
            print(f"[ocean-analytics] {chl_note}")

    # Tide as a direction and a turn, never a height. The model is 8 km and
    # referenced to mean sea level rather than chart datum, so a figure would
    # be unusable beside a real depth — but which way it is going, and when it
    # turns, is what a bar crossing is timed against.
    from . import tide as tide_mod
    t = tide_mod.read(reading.hours, task.start)
    if t:
        if t.state == "slack" or not t.turns_at:
            out.append(Finding(
                agent="Ocean Analytics",
                phrase=Phrase("tide_flat", {}),
                headline=f"tide {t.state}",
                citation=reading.cite(task.start),
            ))
        else:
            out.append(Finding(
                agent="Ocean Analytics",
                phrase=Phrase("tide", {"state": t.state,
                                       "hour24": t.turns_at.hour,
                                       "hour": f"{lang.hour12(t.turns_at.hour)}",
                                       "turns": t.turns_to}),
                headline=(f"tide {t.state}, {t.turns_to} water at "
                          f"{t.turns_at:%H:%M}"),
                citation=reading.cite(t.turns_at),
            ))

    flows = [h for h in window
             if h.current_kn is not None and h.current_dir_deg is not None]
    if flows:
        strongest = max(flows, key=lambda h: h.current_kn)
        # below about half a knot the drift is not worth a line in the answer
        if strongest.current_kn >= 0.5:
            out.append(Finding(
                agent="Ocean Analytics",
                phrase=Phrase("current", {"kn": f"{strongest.current_kn:.1f}",
                                          "dir": strongest.current_dir_deg}),
                headline=f"current {strongest.current_kn:.1f} kn",
                citation=reading.cite(strongest.at),
                fell_back=skipped,
            ))

    if chl_note and notes is not None:
        notes["Ocean Analytics"] = chl_note
    return out


async def pfz_agent(client, lat, lon, boat: str = "small") -> list[Finding]:
    """Potential Fishing Zone agent.

    Follows the principle INCOIS publishes — a temperature front and high
    chlorophyll in the same water — but on a model SST field rather than 1 km
    infrared, so the estimate is coarser than theirs and the citation says so.
    """
    from . import pfz as pfz_mod
    from . import ports as _ports

    near = _ports.nearest(lat, lon)
    sea_lat, sea_lon = _ports.seaward(near)

    # PFZ does its own grid fetches rather than going through discover(), so it
    # needs caching of its own — and it is the slowest thing in the app, being
    # 25 temperature points plus a satellite grid.
    #
    # The cached part is the zone geometry, which depends only on the water.
    # Distance and bearing depend on where the boat is, so they are recomputed
    # against this caller's position every time.
    from . import cache

    result, cached, age = await cache.get_or_fetch(
        "pfz", sea_lat, sea_lon,
        lambda: pfz_mod.find(client, sea_lat, sea_lon,
                             boat_lat=sea_lat, boat_lon=sea_lon))

    result = pfz_mod.recentre(result, lat, lon, boat)

    if not result.zones:
        return [Finding(
            agent="PFZ",
            phrase=Phrase("pfz_none", {}),
            headline="no zone where both signals coincide",
            citation=f"{result.sst_citation} · {result.chl_citation}",
        )]

    out = []
    for z in result.zones:
        out.append(Finding(
            agent="PFZ",
            phrase=Phrase("pfz", {"dist": round(z.distance_km),
                                  "dir": z.bearing_deg,
                                  "strength": z.strength}),
            headline=(f"{z.strength} zone {z.distance_km:.0f} km at "
                      f"{z.bearing_deg:.0f}° · front {z.front_c_per_10km} °C/10km"
                      f" · chl {z.chl_mg_m3} mg/m3"),
            citation=f"{result.sst_citation} · {result.chl_citation}",
            zone_lat=z.lat, zone_lon=z.lon,
            zone_km=z.distance_km, zone_strength=z.strength,
        ))
    return out


def protected_agent(lat, lon, language: str) -> Finding | None:
    """Sanctuaries and seasonal closures.

    The problem statement asks for geofence alerts near ecologically sensitive
    zones as well as maritime boundaries. For many crews this is the half that
    actually catches them: entering a sanctuary is an offence, and Gahirmatha
    shuts to fishing for seven months of every year while turtles nest.

    The warning never says a boat is inside one. The geometry is a circle sized
    from a published area figure, which cannot tell anyone which side of a
    gazetted line they are on.
    """
    from . import protected as mpa

    near = mpa.check(lat, lon)
    if not near:
        return None

    name = near.area.name(language)

    if near.closed:
        return Finding(
            agent="Geospatial",
            phrase=Phrase("mpa_closed", {"name": name,
                                         "reason": near.area.closure.reason,
                                         "dist": near.distance_km}),
            headline=(f"{near.area.name('en')} closed to fishing "
                      f"({near.area.closure.reason}), {near.distance_km} km"),
            citation=f"{near.area.state} protected area (approximate extent)",
            blocking=True,
        )

    if near.opens_in_days is not None:
        return Finding(
            agent="Geospatial",
            phrase=Phrase("mpa_soon", {"name": name, "dist": near.distance_km,
                                       "days": near.opens_in_days,
                                       "reason": near.area.closure.reason}),
            headline=(f"{near.area.name('en')} closes in "
                      f"{near.opens_in_days} days"),
            citation=f"{near.area.state} protected area (approximate extent)",
        )

    if near.touching:
        return Finding(
            agent="Geospatial",
            phrase=Phrase("mpa_edge", {"name": name}),
            headline=f"at the edge of {near.area.name('en')}",
            citation=f"{near.area.state} protected area (approximate extent)",
        )

    return Finding(
        agent="Geospatial",
        phrase=Phrase("mpa_near", {"name": name, "dist": near.distance_km}),
        headline=f"{near.area.name('en')} {near.distance_km} km away",
        citation=f"{near.area.state} protected area (approximate extent)",
    )


async def trends_agent(client, lat, lon) -> list[Finding]:
    """What the water did over a season, compared with the same season a year ago.

    This is the one agent that must be careful about what it does not know. A
    catch is fish minus effort minus gear minus market, and a satellite sees
    none of that. So it reports the water, and says so in the same answer.
    """
    from . import trends as trends_mod

    cmp = await trends_mod.compare(client, lat, lon)

    if cmp.change is None:
        return [Finding(
            agent="Trends",
            phrase=Phrase("trend_nodata", {}),
            headline="not enough imagery to compare years",
            citation=cmp.citation,
        )]

    pct = abs(round(cmp.change * 100))
    kind = {"down": "trend_down", "up": "trend_up"}.get(cmp.direction,
                                                        "trend_steady")
    out = [Finding(
        agent="Trends",
        phrase=Phrase(kind, {"pct": pct} if kind != "trend_steady" else {}),
        headline=(f"chlorophyll {cmp.now.chlorophyll} vs "
                  f"{cmp.before.chlorophyll} mg/m3 a year ago ({cmp.change:+.0%})"),
        citation=cmp.citation,
    )]

    # Always, not only when the news is bad. Someone told the water improved
    # would otherwise take the silence to mean the tool had ruled everything
    # else out.
    out.append(Finding(
        agent="Trends",
        phrase=Phrase("trend_limits", {}),
        headline="effort, gear and market are not visible to a satellite",
        citation="scope of this comparison",
    ))
    return out


async def route_agent(client, lat, lon, findings, gust_kn: float) -> list[Finding]:
    """A lower-risk way to wherever the fishing-zone estimate points.

    This runs after the zone estimate rather than beside it, because a route
    needs a destination and that is what the estimate provides. With nowhere to
    go there is nothing to route to, and saying so is better than routing to an
    arbitrary point offshore.
    """
    from . import route as route_mod

    zone = next((f for f in findings
                 if f.agent == "PFZ" and f.zone_lat is not None), None)
    if not zone:
        return []

    r = await route_mod.find(client, (lat, lon), (zone.zone_lat, zone.zone_lon),
                             gust_kn=gust_kn)

    bearing = geofence.bearing_deg((lat, lon), (r.legs[len(r.legs) // 2].lat,
                                                r.legs[len(r.legs) // 2].lon))
    straight = r.detour_km < 2.0

    out = [Finding(
        agent="Route",
        phrase=(Phrase("route_direct", {"dist": round(r.distance_km),
                                        "dir": bearing})
                if straight else
                Phrase("route_detour", {"dir": bearing,
                                        "dist": round(r.distance_km),
                                        "extra": round(r.detour_km)})),
        legs=[[l.lat, l.lon] for l in r.legs],
        headline=(f"{r.distance_km} km via {len(r.legs)} legs, "
                  f"{r.detour_km:+.1f} km against the shortest grid path, "
                  f"worst wave {r.worst_wave_m} m"),
        citation=r.citation,
    )]

    # Said every time, not only when the route bends. Someone who is told to go
    # a particular way and is not told what that advice cannot see may take it
    # for more than it is.
    out.append(Finding(
        agent="Route",
        phrase=Phrase("route_limits", {}),
        headline="no depth, no sandbars, no other vessels",
        citation=r.citation,
    ))
    return out


def _route_legs(findings) -> list:
    """The path the route agent found, for the map to draw."""
    for f in findings:
        if f.agent == "Route" and getattr(f, "legs", None):
            return f.legs
    return []


def geofence_agent(lat, lon, always=False) -> Finding | None:
    g = geofence.check(lat, lon)
    if g.level == "clear" and not always:
        return None

    if g.level == "clear":
        return Finding(
            agent="Geospatial",
            phrase=Phrase("fence_clear", {"km": g.distance_km}),
            headline=f"{g.distance_km} km from the {g.boundary} — clear",
            citation=f"{g.boundary} layer (approximate)",
            blocking=False,
        )

    return Finding(
        agent="Geospatial",
        phrase=Phrase("fence_near", {"km": g.distance_km, "dir": g.turn_to_deg}),
        headline=f"{g.distance_km} km from the {g.boundary} ({g.level})",
        citation=f"{g.boundary} layer (approximate)",
        blocking=(g.level == "urgent"),
    )


# ------------------------------------------------------------------ risk


def risk_agent(task: Task, findings: list[Finding], language: str,
               missing: list[str] | None = None) -> Decision:
    _ = missing          # applied by _with_caveat after the verdict is chosen
    """The only place a decision is made. Everything above it just reports.

    This is the answer to "what is actually hard here". Fetching a wave height
    is easy. Deciding that 1.8 m is fine for a trawler and dangerous for a 9 m
    boat, and that a lightning warning outranks wave height either way, is not.
    """
    stop = _stop(language)

    # Both the maritime boundary and the protected-area warning are filed under
    # Geospatial, and the sanctuary one is added first. Taking whichever came
    # first meant "how far is the boundary?" answered with a sanctuary, and
    # carried that finding's verdict — so the badge read "safe" above a
    # sentence saying "do not enter".
    fence = next((f for f in findings
                  if f.agent == "Geospatial"
                  and f.phrase.kind.startswith("fence")), None)
    mpa = next((f for f in findings
                if f.agent == "Geospatial"
                and f.phrase.kind.startswith("mpa")), None)

    # A boundary question gets a boundary answer, not a sailing verdict.
    if task.intent == "boundary" and fence:
        near = fence.phrase.kind == "fence_near"
        verdict = "stay" if fence.blocking else "caution" if near else "go"
        answer = lang.render(fence.phrase, language) + stop
        # a sanctuary alongside is worth saying, but it must not silently
        # become the headline or override the verdict badge
        if mpa:
            answer += " " + lang.render(mpa.phrase, language) + stop
            if mpa.blocking:
                verdict = "stay"
            elif verdict == "go":
                verdict = "caution"
        return Decision(
            verdict=verdict,
            when_key="now",
            answer=answer,
            lang=language,
            findings=findings,
        )

    # Boundary proximity outranks weather — an arrest is not a weather risk.
    if fence and fence.blocking:
        return Decision("stay", "now", lang.render(fence.phrase, language) + stop,
                        language, findings)

    # No data is not the same as no danger. Never fall through to "go".
    if not findings:
        return Decision("unknown", task.when_key, lang.NO_DATA.get(language, lang.NO_DATA["en"]),
                        language, findings)

    blockers = [f for f in findings if f.blocking]
    thunder = next((f for f in findings if f.phrase.kind == "thunder"), None)

    # A question about a season is not a question about this morning. Someone
    # asking why the catch is down does not want to be told the sea is calm.
    if task.intent == "decline":
        trend = next((f for f in findings if f.agent == "Trends"), None)
        if trend:
            answer = lang.render(trend.phrase, language) + stop
            limits = next((f for f in findings
                           if f.phrase.kind == "trend_limits"), None)
            if limits:
                answer += " " + lang.render(limits.phrase, language) + stop
            return Decision("unknown", task.when_key, answer, language, findings)

    # A fishing question deserves a fishing answer. But safety still outranks
    # it: a good zone in dangerous water is not a recommendation, and blockers
    # are handled below before we ever get here.
    # A route question gets a route answer. Safety still comes first: there is
    # no point describing a way across water nobody should be on.
    if task.intent == "route" and not blockers:
        way = next((f for f in findings
                    if f.agent == "Route"
                    and f.phrase.kind.startswith("route_")
                    and f.phrase.kind != "route_limits"), None)
        if way:
            answer = lang.render(way.phrase, language) + stop
            limits = next((f for f in findings
                           if f.phrase.kind == "route_limits"), None)
            if limits:
                answer += " " + lang.render(limits.phrase, language) + stop
            if thunder:
                answer += " " + lang.render(thunder.phrase, language) + stop
            return Decision("caution" if thunder else "go", task.when_key,
                            answer, language, findings)

    if task.intent == "fishing" and not blockers:
        best = next((f for f in findings if f.agent == "PFZ"), None)
        if best:
            answer = lang.render(best.phrase, language) + stop
            if thunder:
                answer += " " + lang.render(thunder.phrase, language) + stop
            return Decision("caution" if thunder else "go", task.when_key,
                            answer, language, findings)

    if blockers:
        why = lang.render(blockers[0].phrase, language)
        return Decision("stay", task.when_key,
                        lang.verdict_line("stay", task.when_key, why, language),
                        language, findings)

    if thunder:
        why = lang.render(thunder.phrase, language)
        return Decision("caution", task.when_key,
                        lang.verdict_line("caution", task.when_key, why, language),
                        language, findings)

    why = lang.render(findings[0].phrase, language)
    return Decision("go", task.when_key,
                    lang.verdict_line("go", task.when_key, why, language),
                    language, findings)


def _with_caveat(d: Decision, missing: list[str] | None, language: str) -> Decision:
    """An answer built on half the sources must say which half is missing.
    A confident verdict with silent gaps is how a safety tool gets someone hurt."""
    if not missing:
        return d
    d.missing = missing
    # the caveat is read as a sentence, so the names in it have to be in the
    # user's language rather than the English label the panel shows
    agents_txt = ", ".join(lang.agent_short(m, language) for m in missing)

    if d.verdict == "go":
        # Never claim safe on partial data, and never let the sentence say one
        # thing while the badge says another.
        why = lang.render(d.findings[0].phrase, language) if d.findings else ""
        tpl = lang.UNCONFIRMED.get(language, lang.UNCONFIRMED["en"])
        d.answer = tpl.format(agents=agents_txt, why=why)
        d.verdict = "caution"
        return d

    note = lang.PARTIAL.get(language, lang.PARTIAL["en"])
    d.answer = d.answer.rstrip() + " " + note.format(agents=agents_txt)
    return d


# ------------------------------------------------------------------ orchestrate


CAPABILITIES = ("sea_state", "oceanography", "chlorophyll", "weather")


def _planned(task) -> list[tuple[str, bool]]:
    """Which workers this task will actually use, in display order."""
    return [(n, on) for n, on in (("ocean", task.needs_ocean),
                                  ("analytics", task.needs_ocean),
                                  ("pfz", task.needs_pfz),
                            ("trends", task.needs_trends),
                                  ("weather", task.needs_weather),
                                  ("geofence", task.needs_geofence)) if on]


async def answer(question: str, session: Session,
                 boat_override: float | None = None,
                 prefer_lang: str | None = None) -> Decision:
    import time

    t0 = time.perf_counter()
    ms = lambda t: int((time.perf_counter() - t) * 1000)

    # Detection handles the case where someone speaks a language other than the
    # one selected. The picker wins otherwise, so choosing Hindi and tapping a
    # suggestion does what the user plainly meant.
    detected = lang.detect(question)
    language = prefer_lang if prefer_lang in lang.LANG_NAMES else detected
    if prefer_lang and detected != prefer_lang and detected != "en":
        language = detected          # they actually spoke another language
    session.lang = language

    resolved = sess.resolve(session, question, boat_override)
    task = plan(resolved)
    boat = classify_boat(resolved.boat_length_m)

    trace = [
        Trace("User Interaction", "language and intent", "ran",
              f"{lang.LANG_NAMES.get(language, language)}"
              + ("" if language == detected else f" (picker; detected {detected})")
              + (f" · carried {', '.join(resolved.carried)}" if resolved.carried else ""),
              ms(t0),
              parts=[{"t": lang.LANG_NAMES.get(language, language)}]
                    + ([] if language == detected
                       else [{"t": f"(picker; detected {detected})"}])
                    # words, not verbatim text: {"t": ...} is printed as it
                    # came, which put "boat_switched_to_safety, time, intent"
                    # on a Bengali screen
                    + [{"w": c} for c in resolved.carried]),

        Trace("Marine Data Discovery", "choose sources for the task", "ran",
              " · ".join(f"{cap}: {len(sources.chain(cap))}"
                         for cap in CAPABILITIES)
              + (" · IMD configured" if sources.IMD_KEY else " · IMD pending"),
              0,
              parts=[{"n": len(sources.chain(cap)),
                      "w": "weather_cap" if cap == "weather" else cap}
                     for cap in CAPABILITIES]
                    + ([] if sources.IMD_KEY else [{"w": "imd_pending"}])),

        Trace("Planner", "decompose the question", "ran",
              f"{task.intent} · {task.when_key} · "
              + " + ".join(n for n, on in _planned(task)),
              ms(t0),
              parts=[{"w": task.intent}, {"w": task.when_key}]
                    + [{"w": "weather_cap" if n == "weather" else n}
                       for n, on in _planned(task)]),
    ]

    findings: list[Finding] = []
    # A fisherman at 4 a.m. will not wait 25 s. Fail fast and say so instead.
    timeout = httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0)
    # follow_redirects matters: the standalone chlorophyll check worked while
    # the same query inside the app returned nothing, because ERDDAP redirects
    # and this client was silently dropping the redirect.
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        jobs, names = [], []
        failed: list[str] = []
        # per-request, not module level: keying a global by id(task) can hand a
        # stale note to a different request once the old object is collected
        notes: dict[str, str] = {}
        if task.needs_ocean:
            jobs.append(ocean_agent(client, session.lat, session.lon, task, boat))
            names.append(("Ocean", "wave height and period", sources.OCEAN.name))
        if task.needs_weather:
            jobs.append(weather_agent(client, session.lat, session.lon, task, boat))
            names.append(("Weather", "wind, gusts, lightning", sources.WEATHER.name))
        if task.needs_ocean:
            jobs.append(ocean_analytics_agent(client, session.lat, session.lon,
                                              task, notes))
            names.append(("Ocean Analytics", "sea temperature and currents",
                          "Open-Meteo marine"))
        if task.needs_trends:
            jobs.append(trends_agent(client, session.lat, session.lon))
            names.append(("Trends", "this season against last year",
                          "satellite ocean colour archive"))
        if task.needs_pfz:
            jobs.append(pfz_agent(client, session.lat, session.lon, boat))
            names.append(("PFZ", "where fronts and plankton coincide",
                          "SST gradient + satellite chlorophyll"))

        t1 = time.perf_counter()
        # A budget for the whole round, not per call. One slow agent once held
        # an answer for eighty seconds and then failed anyway; a fisherman
        # deciding at four in the morning had long since put the phone down.
        # Whatever has arrived by the deadline is what the answer is built on,
        # and the trace says which agent did not make it.
        results = await asyncio.gather(
            *[asyncio.wait_for(j, timeout=ANSWER_BUDGET_S) for j in jobs],
            return_exceptions=True)
        fetch_ms = ms(t1)

        for (agent, role, src), result in zip(names, results):
            if isinstance(result, Exception):
                trace.append(Trace(agent, role, "failed",
                                   type(result).__name__, fetch_ms,
                                   parts=[{"w": _failure_word(result)}]))
                failed.append(agent)
                continue
            items = result if isinstance(result, list) else ([result] if result else [])
            findings.extend(items)
            used = items[0].citation.split(" · ")[0] if items else src
            fell = [f for f in (items[0].fell_back if items else [])
                    if not f.startswith("__cached__")]
            cached_for = next((int(f.removeprefix("__cached__"))
                               for f in (items[0].fell_back if items else [])
                               if f.startswith("__cached__")), None)
            detail = f"{used} · {len(items)} finding" + ("s" if len(items) != 1 else "")
            if fell:
                detail += f" · fell back from {', '.join(fell)}"
            notes_shown = notes.pop(agent, "")
            if notes_shown:
                detail += " · " + notes_shown
            parts = [{"t": used},
                     {"n": len(items), "w": "findings" if len(items) != 1 else "finding"}]
            if fell:
                parts += [{"w": "fell_back"}, {"t": ", ".join(fell)}]
            if cached_for is not None:
                # an answer that arrives in 200 ms deserves an explanation
                parts.append({"w": "cached"})
                detail += " · cached"
            trace.append(Trace(agent, role, "ran" if items else "skipped",
                               detail, fetch_ms, parallel=len(jobs) > 1,
                               parts=parts))

    if not task.needs_ocean:
        trace.append(Trace("Ocean", "wave height and period", "skipped",
                           "not needed for this question",
                           parts=[{"w": "not_needed"}]))
    if not task.needs_weather:
        trace.append(Trace("Weather", "wind, gusts, lightning", "skipped",
                           "not needed for this question",
                           parts=[{"w": "not_needed"}]))

    t2 = time.perf_counter()
    # The boundary goes in the list before the sanctuary, because the answer
    # says them in that order. Evidence that reads back-to-front against the
    # sentence above it makes a reader check which one to believe.
    if task.needs_route:
        gust = 0.0
        for f in findings:
            if f.phrase.kind == "gust":
                gust = float(f.phrase.data.get("kn", 0) or 0)
        try:
            async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=4.0, read=10.0,
                                          write=4.0, pool=4.0),
                    follow_redirects=True) as rc:
                findings.extend(
                    # A budget of its own, and a small one. The route runs
                    # after everything else, so whatever it takes is added to
                    # an answer that is already most of the way to being late.
                    await asyncio.wait_for(
                        route_agent(rc, session.lat, session.lon, findings, gust),
                        timeout=ROUTE_BUDGET_S))
            # "ran" with nothing to show is a false claim: without a zone
            # there was nowhere to route to, and the panel should say that
            # rather than imply a search happened.
            drew = any(f.agent == "Route" for f in findings)
            trace.append(Trace("Route", "a lower-risk way across",
                               "ran" if drew else "skipped",
                               "grid search over waves, currents and boundaries"
                               if drew else "no zone to head for",
                               0,
                               parts=[] if drew else [{"w": "no_destination"}]))
        except Exception as e:
            trace.append(Trace("Route", "a lower-risk way across", "failed",
                               type(e).__name__, 0,
                               parts=[{"w": _failure_word(e)}]))
            failed.append("Route")

    mpa_finding = protected_agent(session.lat, session.lon, language)

    g = geofence_agent(session.lat, session.lon, always=task.needs_geofence)
    fence_now = geofence.check(session.lat, session.lon)
    if g:
        findings.append(g)
    if mpa_finding:
        findings.append(mpa_finding)
    trace.append(Trace("Geospatial", "distance to maritime boundary", "ran",
                       f"{fence_now.boundary} · {fence_now.distance_km} km · {fence_now.level}",
                       ms(t2),
                       parts=[{"t": fence_now.boundary},
                              {"t": f"{fence_now.distance_km} km"},
                              {"w": fence_now.level}]))

    t3 = time.perf_counter()
    decision = risk_agent(task, findings, language, missing=failed)
    decision = _with_caveat(decision, failed, language)

    # A "do not go" headline with "good fishing 37 km east" listed underneath is
    # mixed messaging in a safety tool, and the second line is the one someone
    # in a hurry acts on. Withhold the destinations; the trace still records
    # that they were found, so nothing is hidden from review.
    withheld = 0
    if decision.verdict == "stay":
        keep = [f for f in decision.findings if f.agent != "PFZ"]
        withheld = len(decision.findings) - len(keep)
        decision.findings = keep
    blockers = sum(1 for f in findings if f.blocking)
    if withheld:
        # The PFZ agent already has a row saying it ran and what it found.
        # Adding a second row for the same agent reads as a contradiction —
        # succeeded here, skipped there — so amend the row that exists.
        for t in trace:
            if t.agent == "PFZ":
                t.status = "skipped"
                t.detail = (f"{withheld} zone"
                            + ("s" if withheld != 1 else "")
                            + " withheld — conditions are unsafe")
                t.parts = [{"n": withheld,
                            "w": "zones" if withheld != 1 else "zone"},
                           {"w": "withheld"}]
                break

    # Count what the user is actually looking at. Reporting the pre-withholding
    # total put "8 findings" on the same screen as a list of six, and a reader
    # who notices that stops trusting both numbers.
    weighed = len(decision.findings)
    trace.append(Trace("Risk", "correlate and decide", "ran",
                       f"{weighed} finding"
                       + ("s" if weighed != 1 else "")
                       + f", {blockers} blocking → {decision.verdict}",
                       ms(t3),
                       parts=[{"n": weighed,
                               "w": "findings" if weighed != 1 else "finding"},
                              {"n": blockers, "w": "blocking_w"},
                              {"t": "→"},
                              {"w": decision.verdict}]))

    decision.trace = trace
    decision.context_carried = resolved.carried

    fence = geofence.check(session.lat, session.lon)
    zones = [
        {"lat": f.zone_lat, "lon": f.zone_lon,
         "km": f.zone_km, "strength": f.zone_strength}
        for f in decision.findings
        if f.agent == "PFZ" and f.zone_lat is not None
    ]
    decision.map = {
        "lat": session.lat, "lon": session.lon,
        "boundary_km": fence.distance_km,
        "boundary_level": fence.level,
        "boundary_name": fence.boundary,
        "imbl": fence.line or geofence.IMBL_SEGMENT,
        "zones": zones,
        "route": [[f.zone_lat, f.zone_lon] for f in []] or _route_legs(findings),
    }

    # These two were doing their work without appearing: the map is drawn from
    # decision.map, and every finding already carries its source and timestamp.
    # Leaving them off the panel made the architecture look smaller than it is.
    #
    # They sit here, after decision.map is built, and not where they were
    # first written — above it, where the map was still empty and the layer
    # count therefore always came out as one.
    zones_drawn = len(decision.map.get("zones", []))
    layers = 1 + (1 if decision.map.get("imbl") else 0) + (1 if zones_drawn else 0)
    trace.append(Trace("Visualization", "put it on a map", "ran",
                       f"{layers} layers · boat, boundary"
                       + (f", {zones_drawn} zones" if zones_drawn else ""),
                       0,
                       parts=[{"n": layers, "w": "layers"}]))

    cited = sum(1 for f in decision.findings if f.citation)
    trace.append(Trace("Reporting", "say where every number came from", "ran",
                       f"{cited} of {len(decision.findings)} findings cited",
                       0,
                       parts=[{"n": cited, "w": "cited"}]))

    # Last, because it counts the rows above it — and Visualization and
    # Reporting run after the map is built, which is after everything else.
    trace.append(Trace("Total", "end to end", "ran",
                       f"{len(trace)} agents", ms(t0),
                       parts=[{"n": len(trace), "w": "agents"}]))

    session.turns.append(Turn(question, task.when_key, task.intent, decision.verdict))
    return decision
