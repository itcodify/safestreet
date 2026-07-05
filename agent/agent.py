import os, requests
from google.adk.agents import Agent
from google.cloud import firestore
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from shared.risk_model import compute_risk, SEVERITY_WEIGHT, LOCATIONS

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(os.path.dirname(__file__), "..", "firebase-key.json"))
fs = firestore.Client()

OWM_KEY = "d1bba422da8475763a01888a86aae6af"

def resolve_location(user_input: str) -> str | None:
    """Matches a casual location name like 'Kurla' to the full key like 'Kurla (Nehru Nagar)'."""
    user_input_lower = user_input.lower().strip()
    for full_name in LOCATIONS:
        if user_input_lower in full_name.lower() or full_name.lower().startswith(user_input_lower):
            return full_name
    return None

def get_current_rainfall(location: str) -> dict:
    """Returns current live rainfall for any Mumbai location.
    Args:
        location: name of the location, e.g. "Sion Circle" or any other Mumbai area
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
        resp = requests.get(url, params=params, timeout=5).json()
        return {"status": "success", "location": location, "rainfall_mm_hr": resp.get("rain", {}).get("1h", 0.0),
                "duration_hrs": 1.0, "vulnerability": vulnerability, "drainage_score": drainage_score,
                "is_curated": resolved is not None}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_community_reports(location: str) -> dict:
    """Fetches recent citizen-submitted flood reports for a location, from Firestore.
    Args:
        location: name of the location to check
    """
    try:
        docs = fs.collection("community_reports").where("location", "==", location).limit(10).stream()
        return {"status": "success", "reports": [d.to_dict() for d in docs]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def compute_flood_risk(location: str) -> dict:
    """Computes current flood risk (0-100%) for any Mumbai location.
    Args:
        location: name of the location to score
    """
    rain = get_current_rainfall(location)
    if rain.get("status") != "success":
        return rain
    resolved_name = rain["location"]
    reports = get_community_reports(resolved_name).get("reports", [])
    boost = sum(SEVERITY_WEIGHT.get(r.get("severity"), 0) for r in reports)
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
    """Converts any place name into coordinates, for locations not in our curated hotspot list."""
    try:
        url = "http://api.openweathermap.org/geo/1.0/direct"
        params = {"q": f"{place_name},Mumbai,IN", "limit": 1, "appid": OWM_KEY}
        resp = requests.get(url, params=params, timeout=5).json()
        if not resp:
            return {"status": "error", "message": f"Couldn't locate '{place_name}' in Mumbai."}
        return {"status": "success", "lat": resp[0]["lat"], "lon": resp[0]["lon"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

root_agent = Agent(
    model="gemini-2.5-flash",
    name="safestreet_agent",
    description="Answers questions about Mumbai monsoon flood risk using live rainfall and community reports.",
    instruction=(
        "You are SafeStreet, a calm, direct flood-risk assistant for Mumbai residents. "
        "For location-specific questions, use compute_flood_risk and recommend_action. "
        "To find the riskiest area among known hotspots, call compute_flood_risk for each of these and compare: "
        + ", ".join(LOCATIONS.keys()) + ". "
        "If someone asks a general question unrelated to flood risk (small talk, questions about you, "
        "or anything outside Mumbai flooding), respond briefly and warmly, then gently steer back — "
        "for example: 'I'm mainly built to help with Mumbai flood risk, but happy to chat — what would you like to know?' "
        "If someone asks whether you're sure about an answer, explain plainly what your answer is based on "
        "(live rainfall data and/or community reports) and its limits — don't just repeat the same answer flatly. "
        "Never respond with nothing — if you're not confident, say so honestly and explain what you'd need to know more. "
        "Be concise throughout."
    ),
    tools=[get_current_rainfall, get_community_reports, compute_flood_risk, recommend_action],
)