"""
SafeStreet backend — single process, single port, Render-friendly.

Responsibilities:
1. Load the Firebase service-account credential from an env var (no key file
   in the image/repo) and point GOOGLE_APPLICATION_CREDENTIALS at it.
2. Mount the ADK agent's FastAPI app (session + /run_sse endpoints) under
   the same app, so the frontend can call it with a relative URL.
3. Proxy the OpenWeatherMap & Open-Meteo calls the frontend needs, so the API key
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
import threading

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# --- Firebase credentials setup
_cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if _cred_json:
    _fd, _cred_path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(_fd, "w") as f:
        f.write(_cred_json)
    os.chmod(_cred_path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _cred_path
else:
    _local_key = os.path.join(BASE_DIR, "firebase-key.json")
    if os.path.exists(_local_key):
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", _local_key)

OWM_KEY = os.environ.get("OWM_API_KEY", "")
GNEWS_KEY = os.environ.get("GNEWS_API_KEY", "")

try:
    from google.cloud import firestore as _firestore_module
    _firestore_db = _firestore_module.Client()
except Exception:
    _firestore_db = None

from google.adk.cli.fast_api import get_fast_api_app  # noqa: E402

app: FastAPI = get_fast_api_app(
    agents_dir=BASE_DIR,
    web=False,
    allow_origins=["*"],
)

# ---------------------------------------------------------------------------
# Weather & News Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/weather-alerts")
def weather_alerts(lat: float = 19.076, lon: float = 72.8777):
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


_NEWS_CACHE = {}
_NEWS_CACHE_TTL_SECONDS = 600

@app.get("/api/news")
def weather_news(q: str = "Mumbai flood monsoon"):
    import logging
    from datetime import datetime, timezone, timedelta

    log = logging.getLogger("uvicorn.error")

    cache_key = q.strip().lower()
    cached = _NEWS_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _NEWS_CACHE_TTL_SECONDS:
        return JSONResponse(cached["payload"])

    TRUSTED_SOURCES = {
        "reuters", "the times of india", "hindustan times", "the indian express",
        "ndtv", "the hindu", "livemint", "moneycontrol", "ani", "press trust of india",
        "bbc news", "the economic times", "mid-day", "free press journal",
        "india today", "news18", "cnbc tv18",
    }
    MAX_AGE_DAYS = 3

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
            reason = "GNews daily quota likely exceeded" if r.status_code in (403, 429) else f"upstream HTTP {r.status_code}"
            return None, reason

        data = r.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        out = []
        for a in data.get("articles", []):
            pub_raw = (a.get("publishedAt") or "").strip()
            try:
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
            parsed_items, err = fetch_and_filter(14)
            if err:
                return JSONResponse({"items": [], "_debug": err})

        parsed_items.sort(key=lambda x: (not x["_trusted"], -x["_dt"].timestamp()))
        items = [{k: v for k, v in i.items() if not k.startswith("_")} for i in parsed_items[:10]]
        payload = {"items": items}
        _NEWS_CACHE[cache_key] = {"ts": time.time(), "payload": payload}
        return JSONResponse(payload)
    except Exception as e:
        log.error(f"[/api/news] Unexpected error for q={q!r}: {e!r}")
        return JSONResponse({"items": [], "_debug": str(e)})


@app.get("/api/current-weather")
def current_weather(lat: float, lon: float):
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
        obs_dt = data.get("dt")
        age_minutes = (time.time() - obs_dt) / 60 if obs_dt else None
        weather_main = ((data.get("weather") or [{}])[0].get("main") or "").lower()
        is_raining = weather_main in ("rain", "drizzle", "thunderstorm")
        rain_1h = (data.get("rain") or {}).get("1h")
        if is_raining:
            rainfall_value = rain_1h if rain_1h is not None else 0.5
        else:
            rainfall_value = 0.0
        _record_rain_sample(lat, lon, rainfall_value)
        return JSONResponse({
            "rainfall_mm_hr": rainfall_value,
            "description": (data.get("weather") or [{}])[0].get("description"),
            "age_minutes": age_minutes,
            "is_raining": is_raining,
        })
    except Exception:
        return JSONResponse({"rainfall_mm_hr": None, "description": None, "age_minutes": None, "is_raining": None})


# ---------------------------------------------------------------------------
# Rain Tracking & Batch Duration Logic
# ---------------------------------------------------------------------------

_rain_history_lock = threading.Lock()
_RAIN_HISTORY = {}
_RAIN_HISTORY_COLLECTION = "rain_history"
_FIRESTORE_PERSIST_INTERVAL_SECONDS = 600
_last_persisted = {}

_DURATION_COUNT_THRESHOLD_MM = 1.0
_MAX_DURATION_HOURS = 48.0
_RAINFALL_CACHE = {}
_RAINFALL_CACHE_TTL_SECONDS = 240


def _history_key(lat, lon):
    return f"{round(lat, 3)},{round(lon, 3)}"


def _load_history_from_firestore(key):
    import logging
    log = logging.getLogger("uvicorn.error")
    if _firestore_db is None:
        return []
    try:
        doc = _firestore_db.collection(_RAIN_HISTORY_COLLECTION).document(key).get()
        if doc.exists:
            return (doc.to_dict() or {}).get("samples", [])
        return []
    except Exception as e:
        log.error(f"[rain_history] Firestore read failed for {key}: {e!r}")
        return []


def _persist_history_to_firestore(key, samples):
    import logging
    log = logging.getLogger("uvicorn.error")
    if _firestore_db is None:
        return
    now = time.time()
    if now - _last_persisted.get(key, 0) < _FIRESTORE_PERSIST_INTERVAL_SECONDS:
        return
    try:
        _firestore_db.collection(_RAIN_HISTORY_COLLECTION).document(key).set({"samples": samples})
        _last_persisted[key] = now
    except Exception as e:
        log.error(f"[rain_history] Firestore write failed for {key}: {e!r}")


def _record_rain_sample(lat, lon, rainfall_mm_hr):
    key = _history_key(lat, lon)
    now = time.time()
    with _rain_history_lock:
        samples = _RAIN_HISTORY.get(key)
        if samples is None:
            samples = _load_history_from_firestore(key)
            _RAIN_HISTORY[key] = samples
        if samples and (now - samples[-1]["ts"]) < 120:
            return
        samples.append({"ts": now, "rain": rainfall_mm_hr})
        cutoff = now - 24 * 3600
        while samples and samples[0]["ts"] < cutoff:
            samples.pop(0)
        _persist_history_to_firestore(key, samples)


def _has_sufficient_history(key: str) -> bool:
    samples = _RAIN_HISTORY.get(key, [])
    if len(samples) < 2:
        return False
    return (samples[-1]["ts"] - samples[0]["ts"]) >= 600


def _duration_from_history(lat, lon, current_rain, threshold_mm, max_hours):
    if current_rain < threshold_mm:
        return 0.1
    key = _history_key(lat, lon)
    samples = _RAIN_HISTORY.get(key, [])
    if not samples:
        return 0.1
    now = time.time()
    hours = 0.0
    prev_ts = now
    for s in reversed(samples):
        if s["rain"] < threshold_mm:
            break
        gap_hours = (prev_ts - s["ts"]) / 3600.0
        if gap_hours > 1.5:
            break
        hours += gap_hours
        prev_ts = s["ts"]
        if hours >= max_hours:
            break
    MIN_MEANINGFUL_HOURS = 1 / 60
    return min(hours, max_hours) if hours >= MIN_MEANINGFUL_HOURS else 0.1


def _duration_for_series(times, precip):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    current_idx = 0
    for i, t in enumerate(times):
        try:
            t_dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if t_dt <= now:
            current_idx = i
        else:
            break

    current_rain = precip[current_idx] if current_idx < len(precip) and precip[current_idx] is not None else 0.0

    if current_rain < _DURATION_COUNT_THRESHOLD_MM:
        return current_rain, 0.1

    hours = 0
    i = current_idx
    while i >= 0 and hours < _MAX_DURATION_HOURS:
        v = precip[i] if precip[i] is not None else 0.0
        if v >= _DURATION_COUNT_THRESHOLD_MM:
            hours += 1
            i -= 1
        else:
            break

    return current_rain, float(hours if hours > 0 else 0.1)


def _openmeteo_batch_lookup(pairs, log):
    cache_key = ";".join(f"{lat},{lon}" for lat, lon in pairs)
    cached = _RAINFALL_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _RAINFALL_CACHE_TTL_SECONDS:
        return cached["payload"], False

    try:
        lat_param = ",".join(str(p[0]) for p in pairs)
        lon_param = ",".join(str(p[1]) for p in pairs)
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat_param, "longitude": lon_param,
                "hourly": "precipitation", "past_days": 2, "forecast_days": 1, "timezone": "UTC",
            },
            timeout=12,
        )
        if not r.ok:
            raise RuntimeError(f"Open-Meteo HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        raw_list = data if isinstance(data, list) else [data]
        if len(raw_list) != len(pairs):
            raise RuntimeError(f"Open-Meteo returned {len(raw_list)} results for {len(pairs)} requested points")

        results = []
        for item in raw_list:
            hourly = item.get("hourly") or {}
            times = hourly.get("time") or []
            precip = hourly.get("precipitation") or []
            rain, dur = _duration_for_series(times, precip)
            results.append({"rainfall_mm_hr": rain, "duration_hrs": dur})

        _RAINFALL_CACHE[cache_key] = {"ts": time.time(), "payload": results}
        return results, False

    except Exception as e:
        log.error(f"[/api/rainfall fallback] failed for {len(pairs)} points: {e!r}")
        if cached:
            return cached["payload"], True
        return [{"rainfall_mm_hr": 0, "duration_hrs": 0.1} for _ in pairs], True


@app.get("/api/rainfall")
def rainfall(locations: str):
    import logging
    log = logging.getLogger("uvicorn.error")

    pairs = []
    for chunk in locations.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            lat_s, lon_s = chunk.split(",")
            pairs.append((float(lat_s), float(lon_s)))
        except Exception:
            continue
    if not pairs:
        return JSONResponse({"results": [], "stale": False})

    results = [None] * len(pairs)
    needs_fallback_idx = []

    for i, (lat, lon) in enumerate(pairs):
        key = _history_key(lat, lon)
        sufficient_history = _has_sufficient_history(key)

        current_rain = None
        if OWM_KEY:
            try:
                r = requests.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"lat": lat, "lon": lon, "appid": OWM_KEY, "units": "metric"},
                    timeout=6,
                )
                if r.ok:
                    data = r.json()
                    weather_main = ((data.get("weather") or [{}])[0].get("main") or "").lower()
                    is_raining = weather_main in ("rain", "drizzle", "thunderstorm")
                    rain_1h = (data.get("rain") or {}).get("1h")
                    current_rain = (rain_1h if rain_1h is not None else 0.5) if is_raining else 0.0
                    _record_rain_sample(lat, lon, current_rain)
            except Exception:
                pass

        if current_rain is not None:
            if current_rain < _DURATION_COUNT_THRESHOLD_MM:
                results[i] = {"rainfall_mm_hr": 0.0, "duration_hrs": 0.1}
            else:
                # Always cross-check against the Open-Meteo model series too,
                # even when we have live in-memory history. Live history resets
                # to empty on every process restart, so on its own it
                # systematically *underestimates* how long it's actually been
                # raining (it can only ever report "time since this process
                # started"). The 48h Open-Meteo series doesn't have that
                # problem, so take whichever of the two durations is longer.
                results[i] = {"rainfall_mm_hr": current_rain, "duration_hrs": 0.1}
                needs_fallback_idx.append(i)
        else:
            needs_fallback_idx.append(i)

    stale = False
    if needs_fallback_idx:
        fallback_pairs = [pairs[i] for i in needs_fallback_idx]
        fallback_results, fallback_stale = _openmeteo_batch_lookup(fallback_pairs, log)
        stale = fallback_stale
        for idx, res in zip(needs_fallback_idx, fallback_results):
            model_dur = res.get("duration_hrs", 0.1)
            if results[idx] is not None:
                lat, lon = pairs[idx]
                current_rain = results[idx]["rainfall_mm_hr"]
                key = _history_key(lat, lon)
                if _has_sufficient_history(key):
                    hist_dur = _duration_from_history(lat, lon, current_rain, _DURATION_COUNT_THRESHOLD_MM, _MAX_DURATION_HOURS)
                    results[idx]["duration_hrs"] = max(hist_dur, model_dur)
                else:
                    results[idx]["duration_hrs"] = model_dur
            else:
                results[idx] = res

    return JSONResponse({"results": results, "stale": stale})


# Static frontend served last
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)