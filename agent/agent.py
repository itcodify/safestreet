import os, requests
from google.adk.agents import Agent
from google.cloud import firestore
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.risk_model import compute_risk, compute_report_boost, recent_reports, LOCATIONS

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(os.path.dirname(__file__), "..", "firebase-key.json"))
fs = firestore.Client()

OWM_KEY = os.environ.get("OWM_API_KEY", "")

import datetime

def resolve_location(user_input: str) -> str | None:
    """Matches a casual location name like 'Kurla' to the full key like 'Kurla (Nehru Nagar)'."""
    user_input_lower = user_input.lower().strip()
    for full_name in LOCATIONS:
        if user_input_lower in full_name.lower() or full_name.lower().startswith(user_input_lower):
            return full_name
    return None

def get_rain_duration(lat: float, lon: float) -> float | None:
    """Continuous rain duration in hours, from Open-Meteo's real hourly history.
    Returns None (not a fabricated number) if the data genuinely can't be read,
    so callers can be honest about "unknown" instead of silently showing 1hr
    everywhere something goes wrong.
    """
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation",
            "past_days": 2,
            "forecast_days": 1,
            "timezone": "UTC",
        }
        resp = requests.get(url, params=params, timeout=8).json()
        hourly = resp.get("hourly") or {}
        precip, times = hourly.get("precipitation"), hourly.get("time")
        if not precip or not times:
            return None

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        # Find the last hourly slot at or before "now" — robust to exact-string
        # matching quirks, unlike a strict times.index(now_str) lookup.
        idx = None
        for i, t in enumerate(times):
            try:
                slot = datetime.datetime.fromisoformat(t).replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
            if slot <= now_utc:
                idx = i
            else:
                break
        if idx is None:
            return None

        if (precip[idx] or 0) < 0.1:
            return 0.0  # genuinely not raining right now
        duration = 0.0
        for i in range(idx, -1, -1):
            if (precip[i] or 0) >= 0.1:
                duration += 1.0
            else:
                break
        return duration
    except Exception:
        return None

def get_current_rainfall(location: str) -> dict:
    """Returns current live rainfall for any location.
    Args:
        location: name of the location
    """
    resolved = resolve_location(location)
    if resolved:
        loc = LOCATIONS[resolved]
        lat, lon = loc["lat"], loc["lon"]
        location = resolved
        vulnerability, drainage_score = loc["vulnerability"], loc["drainage_score"]
    else:
        geo = geocode_location(location)
        if geo.get("status") != "success":
            return geo
        lat, lon = geo["lat"], geo["lon"]
        # No curated vulnerability data for this area — use a neutral default
        vulnerability, drainage_score = 0.5, 0.5

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"lat": lat, "lon": lon, "appid": OWM_KEY, "units": "metric"}
        resp = requests.get(url, params=params, timeout=8).json()

        # Dynamic duration from Open-Meteo. None means "couldn't determine it" —
        # treat as 0 for scoring rather than fabricating a fixed duration.
        duration = get_rain_duration(lat, lon)

        return {"status": "success", "location": location, "rainfall_mm_hr": resp.get("rain", {}).get("1h", 0.0),
                "duration_hrs": duration if duration is not None else 0.0,
                "duration_known": duration is not None,
                "vulnerability": vulnerability, "drainage_score": drainage_score,
                "is_curated": resolved is not None}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_community_reports(location: str) -> dict:
    """Fetches recent (last few hours) citizen-submitted flood reports for a
    location, from Firestore. Older reports are excluded so a single stale
    report can't keep inflating the risk score indefinitely.
    Args:
        location: name of the location to check
    """
    try:
        docs = fs.collection("community_reports").where("location", "==", location).limit(20).stream()
        all_reports = [d.to_dict() for d in docs]
        fresh = recent_reports(all_reports)
        return {"status": "success", "reports": fresh, "stale_excluded": len(all_reports) - len(fresh)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def compute_flood_risk(location: str) -> dict:
    """Computes current flood risk (0-100%) for any location.
    Args:
        location: name of the location to score
    """
    rain = get_current_rainfall(location)
    if rain.get("status") != "success":
        return rain
    resolved_name = rain["location"]
    reports = get_community_reports(resolved_name).get("reports", [])
    boost = compute_report_boost(reports)
    score = compute_risk(rain["rainfall_mm_hr"], rain["duration_hrs"], rain["vulnerability"], rain["drainage_score"], boost)
    tier = "low" if score < 0.35 else "watch" if score < 0.65 else "high"
    return {"status": "success", "location": resolved_name, "risk_score": round(score * 100, 1),
            "risk_tier": tier, "report_count": len(reports), "is_curated": rain["is_curated"]}

def recommend_action(location: str) -> dict:
    """Recommends whether to leave now, wait, or reroute for a location.
    Args:
        location: name of the location
    """
    result = compute_flood_risk(location)
    if result.get("status") != "success":
        return result
    tier = result["risk_tier"]
    if tier == "low":
        rec = f"Safe to head out — risk at {location} is {result['risk_score']}%."
    elif tier == "watch":
        rec = f"Risk at {location} is {result['risk_score']}% and rising. Consider waiting or an alternate route."
    else:
        rec = f"Avoid {location} — risk is {result['risk_score']}%, confirmed by {result['report_count']} community report(s)."
    return {"status": "success", "recommendation": rec}

def geocode_location(place_name: str) -> dict:
    """Converts any place name into global coordinates. Uses Open-Meteo's
    free geocoder (no API key, no quota) so global search works reliably
    regardless of OpenWeatherMap key/quota status.
    """
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": place_name, "count": 1, "language": "en", "format": "json"}
        resp = requests.get(url, params=params, timeout=8).json()
        results = resp.get("results") or []
        if not results:
            return {"status": "error", "message": f"Couldn't locate '{place_name}'."}
        r = results[0]
        return {"status": "success", "lat": r["latitude"], "lon": r["longitude"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

root_agent = Agent(
    model="gemini-2.5-flash",
    name="safestreet_agent",
    description="Answers questions about flood risk globally using live rainfall and community reports.",
    instruction=(
        "You are SafeStreet, a calm, direct flood-risk assistant. "
        "For location-specific questions, use compute_flood_risk and recommend_action. "
        "To find the riskiest area among known hotspots, call compute_flood_risk for each of these and compare: "
        + ", ".join(LOCATIONS.keys()) + ". "
        "If someone asks a general question unrelated to flood risk (small talk, questions about you, "
        "or anything outside flood risk), respond briefly and warmly, then gently steer back — "
        "for example: 'I'm mainly built to help with flood risk, but happy to chat — what would you like to know?' "
        "If someone asks whether you're sure about an answer, explain plainly what your answer is based on "
        "(live rainfall data and/or community reports) and its limits — don't just repeat the same answer flatly. "
        "Never respond with nothing — if you're not confident, say so honestly and explain what you'd need to know more. "
        "Be concise throughout."
    ),
    tools=[get_current_rainfall, get_community_reports, compute_flood_risk, recommend_action],
)