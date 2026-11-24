"""Step 6: the web API.

Run:   cd src && ../.venv/bin/uvicorn api:app --port 8000
Docs:  http://localhost:8000/docs   (interactive, generated automatically)
Map:   http://localhost:8000/

Endpoints
  GET /journeys?from=...&to=...&depart=2026-10-27T08:30&options=3
        from/to: a stop or place name ("Kashmere Gate") or "lat,lon"
        depart:  ISO date-time, local Delhi time. Defaults to now.
  GET /stops/search?q=nehru          stop-name autocomplete
  GET /traffic?day_type=weekday&hour=18   modelled bus speed on every stretch (for the map)
"""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
from planner import Planner

MODEL_DIR = Path(os.environ.get("MODEL_DIR", config.MODEL))
WEB = config.ROOT / "web"
IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(
    title="Delhi Bus Journey Planner",
    description="Bus journey options for Delhi with travel times learned from DTC bus GPS "
                "(October 2026), varying by hour of day and day of week.",
    version="1.0",
)
planner = Planner(MODEL_DIR)


@app.get("/journeys", summary="Plan a bus journey")
def journeys(
    from_: str = Query(..., alias="from", description="Origin: stop/place name or 'lat,lon'", examples=["Kashmere Gate ISBT"]),
    to: str = Query(..., description="Destination: stop/place name or 'lat,lon'", examples=["Nehru Place"]),
    depart: str | None = Query(None, description="Departure, ISO local time e.g. 2026-10-27T08:30. Default: now"),
    options: int = Query(3, ge=1, le=6, description="How many options to return"),
):
    try:
        when = datetime.fromisoformat(depart) if depart else datetime.now(IST).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(400, "depart must be ISO format, e.g. 2026-10-27T08:30")
    try:
        return planner.plan(from_, to, when, n_options=options)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/places", summary="All places (groups of nearby stops with the same name) for dropdowns")
def places():
    return planner.list_places()


@app.get("/stops/search", summary="Find stops by name")
def stops_search(q: str = Query(..., min_length=2), limit: int = 10):
    return planner.search_stops(q, limit)


_traffic_cache = {}


@app.get("/traffic", summary="Modelled bus speed on every stretch of road")
def traffic(day_type: str = Query("weekday", pattern="^(weekday|saturday|sunday)$"), hour: int = Query(8, ge=0, le=23)):
    key = (day_type, hour)
    if key not in _traffic_cache:
        d = ["weekday", "saturday", "sunday"].index(day_type)
        p = planner
        m = np.load(MODEL_DIR / "segment_model.npz")
        dist, level = m["dist"], p.level[:, d, hour]
        est = p.est[:, d, hour]
        geom = p.seg_geometry()
        feats = [{"kmh": round(float(dist[i] / est[i] * 3.6), 1), "path": geom[i]}
                 for i in np.where(level <= 2)[0] if i in geom]     # only stretches with real measurements
        _traffic_cache[key] = {"day_type": day_type, "hour": hour, "segments": feats}
    return _traffic_cache[key]


@app.get("/health")
def health():
    return {"ok": True, "model": str(MODEL_DIR)}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
