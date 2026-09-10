"""Open-Meteo forecast at kickoff for outdoor stadiums."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..cache import HOUR, cached_json

# team -> (lat, lon, dome). Retractable roofs treated as dome (usually closed in bad weather).
STADIUMS = {
    "ARI": (33.5276, -112.2626, True), "ATL": (33.7554, -84.4010, True), "BAL": (39.2780, -76.6227, False),
    "BUF": (42.7738, -78.7870, False), "CAR": (35.2258, -80.8528, False), "CHI": (41.8623, -87.6167, False),
    "CIN": (39.0955, -84.5161, False), "CLE": (41.5061, -81.6995, False), "DAL": (32.7473, -97.0945, True),
    "DEN": (39.7439, -105.0201, False), "DET": (42.3400, -83.0456, True), "GB": (44.5013, -88.0622, False),
    "HOU": (29.6847, -95.4107, True), "IND": (39.7601, -86.1639, True), "JAX": (30.3240, -81.6373, False),
    "KC": (39.0489, -94.4839, False), "LV": (36.0909, -115.1833, True), "LAC": (33.9535, -118.3392, True),
    "LAR": (33.9535, -118.3392, True), "MIA": (25.9580, -80.2389, False), "MIN": (44.9737, -93.2577, True),
    "NE": (42.0909, -71.2643, False), "NO": (29.9511, -90.0812, True), "NYG": (40.8135, -74.0745, False),
    "NYJ": (40.8135, -74.0745, False), "PHI": (39.9008, -75.1675, False), "PIT": (40.4468, -80.0158, False),
    "SF": (37.4032, -121.9698, False), "SEA": (47.5952, -122.3316, False), "TB": (27.9759, -82.5033, False),
    "TEN": (36.1665, -86.7713, False), "WSH": (38.9077, -76.8645, False), "WAS": (38.9077, -76.8645, False),
}


def forecast(home_team: str, kickoff_iso: str, force: bool = False) -> dict | None:
    st = STADIUMS.get(home_team)
    if not st:
        return None
    lat, lon, dome = st
    if dome:
        return {"dome": True}
    kick = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    day = kick.date().isoformat()

    def fetch():
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": "temperature_2m,wind_speed_10m,precipitation_probability,precipitation",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC", "start_date": day, "end_date": day,
        }, timeout=30)
        r.raise_for_status()
        return r.json()

    try:
        data = cached_json(f"wx_{home_team}_{day}", 3 * HOUR, fetch, force)
    except Exception:
        return None
    hours = data.get("hourly", {})
    times = hours.get("time", [])
    target = kick.strftime("%Y-%m-%dT%H:00")
    if target not in times:
        return {"dome": False, "unavailable": True}
    i = times.index(target)
    return {
        "dome": False,
        "temp_f": hours["temperature_2m"][i], "wind_mph": hours["wind_speed_10m"][i],
        "precip_pct": hours["precipitation_probability"][i], "precip_in": hours["precipitation"][i],
    }
