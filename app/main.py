"""ORCA API. Run: uvicorn app.main:app --reload"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agents, alerts, lang, panel_strings, ports, sources, ui_strings
from . import session as sess

app = FastAPI(title="ORCA", description="Marine decision support · SIH26176")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

STATIC = Path(__file__).parent.parent / "static"


class Ask(BaseModel):
    question: str = Field(..., examples=["কাল সকালে সমুদ্রে যাওয়া নিরাপদ হবে?"])
    session_id: str = "demo"
    lat: float | None = None
    lon: float | None = None
    boat_length_m: float | None = None
    prefer_lang: str | None = None


@app.on_event("startup")
async def _start_watching():
    alerts.start()


@app.on_event("shutdown")
async def _stop_watching():
    alerts.stop()


class Watch(BaseModel):
    session_id: str = "demo"
    lat: float
    lon: float
    boat_length_m: float = 9.0
    lang: str = "bn"
    on: bool = True


@app.post("/watch")
async def watch(body: Watch):
    """Start or stop watching a boat while it is out.

    This is the one part of the system that speaks without being asked.
    """
    if not body.on:
        alerts.unwatch(body.session_id)
        return {"watching": False}
    alerts.watch(body.session_id, body.lat, body.lon,
                 body.boat_length_m, body.lang)
    return {"watching": True, "interval_seconds": alerts.INTERVAL_SECONDS}


@app.get("/alerts")
async def poll_alerts(session_id: str = "demo"):
    """Anything that came up since the last time we were asked.

    A poll, not a push: the phone asks. Reaching a phone that is asleep on a
    boat needs Firebase or SMS, and SMS is the one that reaches the feature
    phone that actually matters here.
    """
    pending = alerts.take(session_id)
    return {
        "watching": alerts.watching(session_id),
        "alerts": [{"kind": a.kind, "text": a.text, "verdict": a.verdict,
                    "at": a.at} for a in pending],
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "ocean_source": sources.OCEAN.name,
        "weather_source": sources.WEATHER.name,
        "imd_configured": bool(sources.IMD_KEY),
        "alerts": alerts.summary(),
        "languages": list(lang.LANG_NAMES),
    }


@app.post("/ask")
async def ask(body: Ask):
    s = sess.get(body.session_id)
    if body.lat is not None and body.lon is not None:
        s.lat, s.lon = body.lat, body.lon

    if s.lat is None or s.lon is None:
        return {
            "verdict": "unknown",
            "answer": lang.NEED_PLACE.get(body.prefer_lang or "bn",
                                          lang.NEED_PLACE["en"]),
            "lang": body.prefer_lang or "bn",
            "lang_name": lang.LANG_NAMES.get(body.prefer_lang or "bn", ""),
            "speech_tag": lang.SPEECH_TAG.get(body.prefer_lang or "bn", "bn-IN"),
            "context_carried": [], "boat_length_m": s.boat_length_m,
            "turn": len(s.turns), "evidence": [], "missing": [],
            "map": {}, "series": {}, "trace": [], "place": None,
        }

    try:
        d = await agents.answer(body.question, s, body.boat_length_m,
                                body.prefer_lang)
    except Exception as e:
        raise HTTPException(502, f"source unavailable: {type(e).__name__}: {e}")

    return {
        "verdict": d.verdict,
        "answer": d.answer,
        "lang": d.lang,
        "lang_name": lang.LANG_NAMES.get(d.lang, d.lang),
        "speech_tag": lang.SPEECH_TAG.get(d.lang, "en-IN"),
        "context_carried": [lang.carried_label(c, d.lang)
                            for c in d.context_carried],
        "boat_length_m": s.boat_length_m,
        "turn": len(s.turns),
        "evidence": [
            {
                "agent": f.agent,
                "headline": f.headline,
                "detail": lang.render(f.phrase, d.lang),
                "citation": f.citation,
                "blocking": f.blocking,
            }
            for f in d.findings
        ],
        "missing": d.missing,
        "map": d.map,
        "series": d.series,
        # The position decides the sea area, the fishing zone and the
        # boundary. It is the one input nobody typed, so the answer has to
        # name the place it is about rather than let it be assumed.
        "place": (ports.nearest(s.lat, s.lon).name(d.lang)
                  if s.lat is not None and s.lon is not None else None),
        "trace": [
            {"agent": t.agent, "key": t.key, "role": t.role,
             "status": t.status, "detail": t.detail, "ms": t.ms,
             "parallel": t.parallel, "parts": t.parts}
            for t in d.trace
        ],
    }


@app.get("/strings")
async def strings(lang_code: str = "bn"):
    """Interface text for one language. The picker is only real if the whole
    interface follows it, not just the microphone."""
    return {
        "lang": lang_code,
        "lang_name": lang.LANG_NAMES.get(lang_code, lang_code),
        "speech_tag": lang.SPEECH_TAG.get(lang_code, "bn-IN"),
        "ui": ui_strings.strings(lang_code),
        "panel": panel_strings.panel(lang_code),
        "words": panel_strings.words(lang_code),
        "ports": ports.listing(lang_code),
        # English was left out of the picker at first, because the point of
        # this app is the eight regional languages and an English option
        # invites people to fall back to it. It is offered now for one
        # reason: the people evaluating it read English, and a demo they can
        # read themselves is worth more than one they have to be told about.
        # It sits last, after the eight.
        "languages": [
            {"code": c, "name": n, "tag": lang.SPEECH_TAG.get(c, "en-IN")}
            for c, n in lang.LANG_NAMES.items()
        ],
    }


@app.get("/nearest")
async def nearest(lat: float, lon: float, lang_code: str = "bn"):
    """Name a GPS fix by the harbour nearest to it.

    The name is for telling the user where we think they are. The position we
    answer for is the one they gave us, not the harbour's — someone who put out
    from a creek five kilometres along the coast is not at the harbour, and the
    distance to a boundary or a sanctuary is different there.
    """
    from . import geofence

    p = ports.nearest(lat, lon)
    away = geofence.distance_km((lat, lon), (p.lat, p.lon))
    return {"id": p.id, "name": p.name(lang_code),
            "lat": p.lat, "lon": p.lon,
            "state": ports.state_name(p.state, lang_code),
            "distance_km": lang.num(round(away, 1), lang_code),
            # far enough that calling it that harbour would be wrong
            "far": away > 25.0,
            # Beyond this the fix is not on the coast at all — someone testing
            # from inland, or a stale position. A marine forecast for a point
            # 500 km inside the land is not a forecast, it is a number with no
            # meaning, and answering with one would be worse than saying so.
            "inland": away > 120.0}


@app.get("/isro")
async def isro_preview(lang_code: str = "bn"):
    """Where to find ISRO's own picture of today's coastal water.

    Several days are offered, newest first, because the composite is published
    a day or two behind and a given day can be missing. The page tries them in
    order rather than the server spending part of the answer budget on HEAD
    requests for a picture.
    """
    from . import isro

    # The page asks us for the picture rather than MOSDAC directly. Their
    # server does not serve these images to another site's page, so a browser
    # that requests the published URL gets nothing and the panel disappears.
    # Fetching it here costs one request and keeps the source honest: it is
    # still their image, at their published path.
    return {"frames": [{"url": f"/isro/image?day={c.day.isoformat()}",
                        "source": c.url,
                        "days": c.age_days, "label": c.label}
                       for c in isro.candidates()]}


@app.get("/isro/image")
async def isro_image(day: str):
    from datetime import date as _date

    from . import isro

    try:
        when = _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad date")

    # only days this module would itself offer, so the endpoint cannot be
    # turned into a general fetcher for someone else's server
    if when not in {c.day for c in isro.candidates()}:
        raise HTTPException(status_code=404, detail="not an offered day")

    async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=4.0, read=12.0, write=4.0, pool=4.0),
            follow_redirects=True) as client:
        r = await client.get(isro.url_for(when))
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="not published")
    return Response(content=r.content, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/reset")
async def reset(session_id: str = "demo"):
    s = sess.get(session_id)
    s.turns.clear()
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
