"""ORCA API. Run: uvicorn app.main:app --reload"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
        "languages": [
            {"code": c, "name": n, "tag": lang.SPEECH_TAG.get(c, "en-IN")}
            for c, n in lang.LANG_NAMES.items() if c != "en"
        ],
    }


@app.get("/nearest")
async def nearest(lat: float, lon: float, lang_code: str = "bn"):
    """Closest harbour to a GPS fix, so the app can open where the user is."""
    p = ports.nearest(lat, lon)
    return {"id": p.id, "name": p.name(lang_code), "lat": p.lat, "lon": p.lon,
            "state": p.state}


@app.post("/reset")
async def reset(session_id: str = "demo"):
    s = sess.get(session_id)
    s.turns.clear()
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
