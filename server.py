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

import time
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
GNEWS_KEY = os.environ.get("GNEWS_API_KEY", "")

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
    """Fetches weather/flood headlines via GNews.io.

    Previously scraped Google News RSS directly, but Google frequently serves
    a CAPTCHA/consent page instead of the real feed to requests coming from
    cloud/datacenter IP ranges (Render, AWS, GCP, etc.) — it worked in local
    testing from a home connection and then silently returned nothing once
    deployed. GNews is a proper API meant for server-to-server access, so it
    doesn't have that problem. Get a free key (100 requests/day, no card
    required) at https://gnews.io and set GNEWS_API_KEY."""
    import logging
    from datetime import datetime, timezone, timedelta

    log = logging.getLogger("uvicorn.error")

    # Trusted wire services / major outlets — shown ahead of other sources
    # when both are within the freshness window.
    TRUSTED_SOURCES = {
        "reuters", "the times of india", "hindustan times", "the indian express",
        "ndtv", "the hindu", "livemint", "moneycontrol", "ani", "press trust of india",
        "bbc news", "the economic times", "mid-day", "free press journal",
        "india today", "news18", "cnbc tv18",
    }
    MAX_AGE_DAYS = 3  # drop anything older than this — conditions change fast

    if not GNEWS_KEY:
        log.error("[/api/news] GNEWS_API_KEY is not set")
        return JSONResponse({"items": [], "_debug": "GNEWS_API_KEY not configured on the server"})

    def fetch_and_filter(max_age_days):
        r = requests.get(
            "https://gnews.io/api/v4/search",
            params={
                "q": q,
                "lang": "en",
                "country": "in",
                "max": 10,
                "sortby": "publishedAt",
                "apikey": GNEWS_KEY,
            },
            timeout=8,
        )
        if not r.ok:
            log.error(f"[/api/news] GNews returned HTTP {r.status_code} for q={q!r}. Body: {r.text[:300]!r}")
            return None, f"upstream HTTP {r.status_code}"

        data = r.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        out = []
        for a in data.get("articles", []):
            pub_raw = (a.get("publishedAt") or "").strip()
            try:
                # GNews returns ISO-8601 with a trailing "Z"
                pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            if pub_dt < cutoff:
                continue
            source = ((a.get("source") or {}).get("name") or "").strip()
            out.append({
                "title": (a.get("title") or "").strip(),
                "link": (a.get("url") or "").strip(),
                "source": source,
                "pubDate": pub_raw,
                "_dt": pub_dt,
                "_trusted": source.lower() in TRUSTED_SOURCES,
            })
        return out, None

    try:
        parsed_items, err = fetch_and_filter(MAX_AGE_DAYS)
        if err:
            return JSONResponse({"items": [], "_debug": err})
        if not parsed_items:
            # Strict 3-day window came up empty (common for smaller/niche
            # locations) — widen rather than show nothing.
            parsed_items, err = fetch_and_filter(14)
            if err:
                return JSONResponse({"items": [], "_debug": err})

        parsed_items.sort(key=lambda x: (not x["_trusted"], -x["_dt"].timestamp()))
        items = [{k: v for k, v in i.items() if not k.startswith("_")} for i in parsed_items[:10]]
        return JSONResponse({"items": items})
    except Exception as e:
        log.error(f"[/api/news] Unexpected error for q={q!r}: {e!r}")
        return JSONResponse({"items": [], "_debug": str(e)})


@app.get("/api/current-weather")
def current_weather(lat: float, lon: float):
    """OWM's current-conditions endpoint reflects real station/satellite
    observations, whereas Open-Meteo's 'current hour' value here is partly
    model-based. Blending the two (frontend does the blending) gives a more
    accurate mm/hr reading than either alone.

    OWM's free-tier snapshot isn't always live-to-the-second — it can lag
    behind by anywhere from a few minutes to over an hour depending on
    station/satellite update cadence. We surface the data's own timestamp
    (`dt`) so the frontend can discard it as stale rather than silently
    presenting an old reading as the current condition.

    Critically, we also surface `is_raining` explicitly. OWM only includes a
    `rain` key in the response when it's actually raining — its *absence*
    is itself a confident "not raining right now" signal from a real
    station/satellite, which is more trustworthy than Open-Meteo's modeled
    guess for the current hour. Previously that absence was indistinguishable
    from "OWM data unavailable," so the frontend fell back to the model
    estimate even when OWM was confidently saying "clear" — this is what
    was causing inflated risk % in places with no actual rain."""
    if not OWM_KEY:
        return JSONResponse({"rainfall_mm_hr": None, "description": None, "age_minutes": None, "is_raining": None})
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": OWM_KEY, "units": "metric"},
            timeout=8,
        )
        if not r.ok:
            return JSONResponse({"rainfall_mm_hr": None, "description": None, "age_minutes": None, "is_raining": None})
        data = r.json()
        obs_dt = data.get("dt")  # unix seconds — when this reading was actually taken
        age_minutes = (time.time() - obs_dt) / 60 if obs_dt else None
        weather_main = ((data.get("weather") or [{}])[0].get("main") or "").lower()
        is_raining = weather_main in ("rain", "drizzle", "thunderstorm")
        rain_1h = (data.get("rain") or {}).get("1h")
        if is_raining:
            # Raining per OWM's own classification; use the reported amount,
            # or a small default if that specific field is missing (rare).
            rainfall_value = rain_1h if rain_1h is not None else 0.5
        else:
            # Confident "not raining" from a real station/satellite reading —
            # trust this over any modeled estimate, don't leave it as null.
            rainfall_value = 0.0
        return JSONResponse({
            "rainfall_mm_hr": rainfall_value,
            "description": (data.get("weather") or [{}])[0].get("description"),
            "age_minutes": age_minutes,
            "is_raining": is_raining,
        })
    except Exception:
        return JSONResponse({"rainfall_mm_hr": None, "description": None, "age_minutes": None, "is_raining": None})


# Static frontend last, so it never shadows the API routes registered above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)