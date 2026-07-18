"""
SafeStreet backend — single process, single port, Render-friendly.

Responsibilities:
1. Load the Firebase service-account credential from an env var (no key file
   in the image/repo) and point GOOGLE_APPLICATION_CREDENTIALS at it.
2. Mount the ADK agent's FastAPI app (session + /run_sse endpoints) under
   the same app, so the frontend can call it with a relative URL.
3. Proxy the two OpenWeatherMap calls the frontend needs, so the API key
   stays server-side and is never shipped to the browser.
4. Serve the static frontend.

Run locally with:  python server.py
Render runs it via the Dockerfile CMD.
"""
from dotenv import load_dotenv
load_dotenv("agent/.env", override=True)

import httpx

import json
import os
import tempfile

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# --- Firebase credentials: expect the *contents* of the service-account
# JSON in an env var, write it to a private temp file, and point ADC at it.
# This means the JSON key never has to live in the repo or the image.
_cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if _cred_json:
    _fd, _cred_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(_fd, "w") as f:
        f.write(_cred_json)
    os.chmod(_cred_path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _cred_path
else:
    # Local-dev fallback: if you keep a gitignored firebase-key.json next to
    # this file, it'll be picked up automatically. Never commit that file.
    _local_key = os.path.join(BASE_DIR, "firebase-key.json")
    if os.path.exists(_local_key):
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", _local_key)

OWM_KEY = os.environ.get("OWM_API_KEY", "")

from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402  (import after env setup)

app: FastAPI = get_fast_api_app(
    agents_dir=BASE_DIR,
    web=False,
    allow_origins=["*"],
)


@app.get("/api/weather-alerts")
def weather_alerts(lat: float = 19.076, lon: float = 72.8777):
    """Server-side proxy for OWM's One Call alerts — key never reaches the client."""
    if not OWM_KEY:
        return JSONResponse({"alerts": []})
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/3.0/onecall",
            params={
                "lat": lat,
                "lon": lon,
                "exclude": "current,minutely,hourly,daily",
                "appid": OWM_KEY,
            },
            timeout=5,
        )
        if not r.ok:
            return JSONResponse({"alerts": []})
        return JSONResponse({"alerts": r.json().get("alerts", [])})
    except Exception:
        return JSONResponse({"alerts": []})


@app.get("/api/geocode")
def geocode(q: str, limit: int = 5):
    """Global geocoding via Open-Meteo (free, no key, no quota) — reliable
    worldwide, unlike relying solely on OWM's geocoder + key/quota status."""
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": q, "count": limit, "language": "en", "format": "json"},
            timeout=8,
        )
        results = (r.json() or {}).get("results") or []
        return JSONResponse([
            {
                "name": item.get("name"),
                "state": item.get("admin1"),
                "country": item.get("country"),
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
            }
            for item in results
        ])
    except Exception:
        return JSONResponse([])


@app.get("/api/news")
def weather_news(q: str = "Mumbai flood monsoon"):
    """Proxies Google News RSS so the frontend can show live weather/flood
    headlines without needing a news-API key. Server-side to avoid browser
    CORS restrictions on the RSS feed."""
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone, timedelta
    from email.utils import parsedate_to_datetime

    # Trusted wire services / major outlets — shown ahead of other sources
    # when both are within the freshness window.
    TRUSTED_SOURCES = {
        "reuters", "the times of india", "hindustan times", "the indian express",
        "ndtv", "the hindu", "livemint", "moneycontrol", "ani", "press trust of india",
        "bbc news", "the economic times", "mid-day", "free press journal",
        "india today", "news18", "cnbc tv18",
    }
    MAX_AGE_DAYS = 3  # drop anything older than this — conditions change fast

    try:
        # "when:3d" restricts results to the last 3 days server-side, so we're
        # not just filtering a mostly-stale, relevance-ranked result set after
        # the fact (Google News RSS defaults to relevance, not recency).
        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": f"{q} when:{MAX_AGE_DAYS}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if not r.ok:
            return JSONResponse({"items": []})

        root = ET.fromstring(r.content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        parsed_items = []

        for item in root.findall("./channel/item"):
            pub_raw = (item.findtext("pubDate") or "").strip()
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue  # skip items with unparseable/missing dates

            if pub_dt < cutoff:
                continue  # belt-and-suspenders in case when:3d lets one through

            source = (item.findtext("source") or "").strip()
            parsed_items.append({
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "source": source,
                "pubDate": pub_raw,
                "_dt": pub_dt,
                "_trusted": source.lower() in TRUSTED_SOURCES,
            })

        # Trusted sources first, then most recent within each group.
        parsed_items.sort(key=lambda x: (not x["_trusted"], -x["_dt"].timestamp()))

        items = [{k: v for k, v in i.items() if not k.startswith("_")} for i in parsed_items[:10]]
        return JSONResponse({"items": items})
    except Exception:
        return JSONResponse({"items": []})


@app.get("/api/current-weather")
def current_weather(lat: float, lon: float):
    """OWM's current-conditions endpoint reflects real station/satellite
    observations, whereas Open-Meteo's 'current hour' value here is partly
    model-based. Blending the two (frontend does the blending) gives a more
    accurate mm/hr reading than either alone."""
    if not OWM_KEY:
        return JSONResponse({"rainfall_mm_hr": None, "description": None})
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": OWM_KEY, "units": "metric"},
            timeout=8,
        )
        if not r.ok:
            return JSONResponse({"rainfall_mm_hr": None, "description": None})
        data = r.json()
        return JSONResponse({
            "rainfall_mm_hr": (data.get("rain") or {}).get("1h"),
            "description": (data.get("weather") or [{}])[0].get("description"),
        })
    except Exception:
        return JSONResponse({"rainfall_mm_hr": None, "description": None})


# Static frontend last, so it never shadows the API routes registered above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)