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

LOCATIONS = {
    "Hindmata (Dadar/Parel)":   {"lat": 19.0033, "lon": 72.8397, "vulnerability": 0.95, "drainage_score": 0.15},
    "Sion Circle":              {"lat": 19.0448, "lon": 72.8619, "vulnerability": 0.88, "drainage_score": 0.20},
    "Kurla (Nehru Nagar)":      {"lat": 19.0728, "lon": 72.8826, "vulnerability": 0.85, "drainage_score": 0.25},
    "Milan Subway (Santacruz)": {"lat": 19.0805, "lon": 72.8420, "vulnerability": 0.90, "drainage_score": 0.18},
    "Andheri Subway":           {"lat": 19.1197, "lon": 72.8464, "vulnerability": 0.80, "drainage_score": 0.30},
    "Gandhi Market (Sion)":     {"lat": 19.0430, "lon": 72.8580, "vulnerability": 0.75, "drainage_score": 0.35},
    "King's Circle":            {"lat": 19.0270, "lon": 72.8560, "vulnerability": 0.65, "drainage_score": 0.45},
    "Lower Parel":              {"lat": 18.9960, "lon": 72.8300, "vulnerability": 0.55, "drainage_score": 0.55},
    "Bandra (Kala Nagar)":      {"lat": 19.0550, "lon": 72.8400, "vulnerability": 0.40, "drainage_score": 0.65},
    "Powai":                    {"lat": 19.1176, "lon": 72.9060, "vulnerability": 0.20, "drainage_score": 0.85},
}