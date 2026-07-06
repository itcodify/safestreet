import numpy as np

def compute_risk(rainfall_mm_hr: float, duration_hrs: float,
                  vulnerability: float, drainage_score: float,
                  report_boost: float = 0.0) -> float:
    intensity_factor = 1 - np.exp(-rainfall_mm_hr / 35.0)
    duration_factor = 1 - np.exp(-duration_hrs / 1.5)
    base = intensity_factor * duration_factor
    adjusted = base * (0.4 + 0.6 * vulnerability) * (1.3 - drainage_score)
    return float(np.clip(adjusted + report_boost, 0, 1))

SEVERITY_WEIGHT = {"ankle": 0.04, "knee": 0.09, "waist": 0.16}
MAX_REPORT_BOOST = 0.3

def compute_report_boost(reports: list[dict]) -> float:
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