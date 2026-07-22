import datetime
import numpy as np

# Hard cap on how much rain "duration" can count for. The old formula had no
# cap and, combined with a noisy upstream duration read, could receive
# absurd values (60+ hours) that blew the risk score up regardless of actual
# current conditions. This mirrors the same cap now enforced in the frontend
# (frontend/index.html, fetchOpenMeteoRain).
MAX_DURATION_HOURS = 24.0

def compute_risk(rainfall_mm_hr: float, duration_hrs: float,
                  vulnerability: float, drainage_score: float,
                  report_boost: float = 0.0, news_boost: float = 0.0) -> float:
    """Mirrors frontend/index.html's riskScore() — keep the two in sync.

    Mumbai monsoon flooding happens two different ways: sewers overwhelmed by
    hours of moderate rain, or a short, heavy downpour outrunning drainage
    capacity in minutes. cumulative_factor captures the first (rain x
    duration, i.e. total mm fallen), burst_factor captures the second (a
    genuinely heavy rain *rate* matters even in its first 15-20 minutes,
    before it's accumulated much). The final intensity used is whichever
    signal is higher, so neither a slow multi-hour drizzle nor a short
    violent burst gets under-scored.
    """
    duration_hrs = min(max(duration_hrs, 0.0), MAX_DURATION_HOURS)
    rainfall_mm_hr = max(rainfall_mm_hr, 0.0)

    cumulative = rainfall_mm_hr * duration_hrs
    cumulative_factor = 1 - np.exp(-cumulative / 18.0)
    burst_factor = 1 - np.exp(-rainfall_mm_hr / 20.0)
    intensity_factor = max(cumulative_factor, burst_factor)

    sustained_factor = 1 - np.exp(-duration_hrs / 5.0)
    vulnerability_factor = 0.4 + 0.6 * vulnerability   # range 0.4-1.0
    drainage_factor = 1.3 - 0.6 * drainage_score        # range 0.7-1.3

    base = intensity_factor * (0.6 + 0.4 * sustained_factor) * vulnerability_factor * drainage_factor
    return float(np.clip(base + report_boost + news_boost, 0, 1))

def rain_intensity_label(rainfall_mm_hr: float) -> str:
    """Matches frontend/index.html's rainIntensityLabel() bands."""
    if rainfall_mm_hr < 0.5:
        return "drizzle"
    if rainfall_mm_hr < 4:
        return "light rain"
    if rainfall_mm_hr < 15:
        return "moderate rain"
    if rainfall_mm_hr < 50:
        return "heavy rain"
    return "violent rain"

SEVERITY_WEIGHT = {"ankle": 0.04, "knee": 0.09, "waist": 0.16}
MAX_REPORT_BOOST = 0.3
# A community report stops influencing the risk score once it's this old —
# otherwise a single report from days ago keeps inflating the % forever.
REPORT_EXPIRY_HOURS = 6

def _report_age_hours(report: dict, now: "datetime.datetime | None" = None) -> float:
    """Age of a report in hours. Reports with no usable timestamp are treated
    as expired (age = infinity) rather than counted forever by default."""
    ts = report.get("reported_at")
    if ts is None:
        return float("inf")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        # Firestore's Python client returns tz-aware datetimes for Timestamp fields.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        return (now - ts).total_seconds() / 3600.0
    except (AttributeError, TypeError):
        return float("inf")

def recent_reports(reports: list[dict], max_age_hours: float = REPORT_EXPIRY_HOURS,
                    now: "datetime.datetime | None" = None) -> list[dict]:
    """Filters out reports older than max_age_hours."""
    return [r for r in reports if _report_age_hours(r, now) <= max_age_hours]

def compute_report_boost(reports: list[dict]) -> float:
    """NOTE: expects already-filtered (recent) reports. Use recent_reports()
    first if the input may contain stale reports."""
    raw = sum(SEVERITY_WEIGHT.get(r.get("severity"), 0) for r in reports)
    return min(raw, MAX_REPORT_BOOST)

LOCATIONS = {
    "Dadar East (Hindmata)":          {"lat": 19.0033, "lon": 72.8397, "vulnerability": 0.95, "drainage_score": 0.15},
    "Sion Circle":                    {"lat": 19.0448, "lon": 72.8619, "vulnerability": 0.88, "drainage_score": 0.20},
    "Sion (Gandhi Market)":           {"lat": 19.0430, "lon": 72.8580, "vulnerability": 0.75, "drainage_score": 0.35},
    "Kurla West (Station Area)":      {"lat": 19.0706, "lon": 72.8796, "vulnerability": 0.85, "drainage_score": 0.25},
    "Kurla East (Nehru Nagar)":       {"lat": 19.0760, "lon": 72.8890, "vulnerability": 0.80, "drainage_score": 0.30},
    "Kurla East (Chunabhatti)":       {"lat": 19.0558, "lon": 72.8845, "vulnerability": 0.78, "drainage_score": 0.28},
    "Milan Subway (Santacruz)":       {"lat": 19.0805, "lon": 72.8420, "vulnerability": 0.90, "drainage_score": 0.18},
    "Andheri Subway":                 {"lat": 19.1197, "lon": 72.8464, "vulnerability": 0.80, "drainage_score": 0.30},
    "Andheri West (Lokhandwala)":     {"lat": 19.1360, "lon": 72.8280, "vulnerability": 0.60, "drainage_score": 0.50},
    "Andheri East (Marol)":           {"lat": 19.1190, "lon": 72.8820, "vulnerability": 0.55, "drainage_score": 0.55},
    "Andheri East (Saki Naka)":       {"lat": 19.1020, "lon": 72.8870, "vulnerability": 0.70, "drainage_score": 0.40},
    "Bandra East (Kalanagar)":        {"lat": 19.0550, "lon": 72.8400, "vulnerability": 0.40, "drainage_score": 0.65},
    "Bandra West (Linking Road)":     {"lat": 19.0600, "lon": 72.8300, "vulnerability": 0.35, "drainage_score": 0.70},
    "Dadar West (Station Road)":      {"lat": 19.0180, "lon": 72.8430, "vulnerability": 0.72, "drainage_score": 0.38},
    "Lower Parel":                    {"lat": 18.9960, "lon": 72.8300, "vulnerability": 0.55, "drainage_score": 0.55},
    "Chembur (Postal Colony)":        {"lat": 19.0525, "lon": 72.8998, "vulnerability": 0.65, "drainage_score": 0.45},
    "Ghatkopar West (LBS Marg)":      {"lat": 19.0868, "lon": 72.9082, "vulnerability": 0.70, "drainage_score": 0.40},
    "Vikhroli (Kannamwar Nagar)":     {"lat": 19.1080, "lon": 72.9258, "vulnerability": 0.62, "drainage_score": 0.48},
    "Malad West (SV Road)":           {"lat": 19.1886, "lon": 72.8452, "vulnerability": 0.75, "drainage_score": 0.35},
    "Dharavi (Koliwada)":             {"lat": 19.0395, "lon": 72.8524, "vulnerability": 0.85, "drainage_score": 0.30},
    "Powai (Hiranandani)":            {"lat": 19.1176, "lon": 72.9060, "vulnerability": 0.20, "drainage_score": 0.85},
}