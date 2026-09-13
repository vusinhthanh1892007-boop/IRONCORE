"""
IronCore Tool: weather_fetch
============================
Fetch current weather for any city using the free wttr.in API.
No API key required.
"""

from __future__ import annotations

import logging

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="weather_fetch",
    version="1.0.0",
    description="Get current weather conditions for a city using wttr.in (free, no API key needed)",
    author="brain",
    tags=["weather", "api", "free", "realtime"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="city",
            type="string",
            description="City name or location (e.g. 'Hanoi', 'New York', 'Tokyo')",
            required=True,
        ),
        SkillParameterSchema(
            name="unit",
            type="string",
            description="Temperature unit: 'celsius' or 'fahrenheit'",
            required=False,
            default="celsius",
        ),
        SkillParameterSchema(
            name="lang",
            type="string",
            description="Language code for output (e.g. 'en', 'vi', 'ja', 'zh')",
            required=False,
            default="en",
        ),
    ],
)
async def weather_fetch(
    city: str,
    unit: str = "celsius",
    lang: str = "en",
) -> dict:
    """Fetch current weather for a city via wttr.in."""
    import httpx

    city_encoded = city.strip().replace(" ", "+")
    # wttr.in JSON API: ?format=j1 returns structured JSON
    url = f"https://wttr.in/{city_encoded}?format=j1&lang={lang}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "IronCore-Agent/1.0"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"error": f"City '{city}' not found"}
        return {"error": f"Weather service error: {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("weather_fetch failed: %s", exc)
        return {"error": str(exc)}

    try:
        current = data["current_condition"][0]
        area = data["nearest_area"][0]

        city_name = (
            area.get("areaName", [{}])[0].get("value", city)
            + ", "
            + area.get("country", [{}])[0].get("value", "")
        ).strip(", ")

        temp_c = int(current["temp_C"])
        temp_f = int(current["temp_F"])
        feels_c = int(current["FeelsLikeC"])
        feels_f = int(current["FeelsLikeF"])
        humidity = current["humidity"]
        wind_kmph = current["windspeedKmph"]
        wind_dir = current["winddir16Point"]
        desc = current["weatherDesc"][0]["value"] if current.get("weatherDesc") else "Unknown"
        visibility = current["visibility"]
        uv_index = current.get("uvIndex", "N/A")

        if unit == "fahrenheit":
            temp_display = f"{temp_f}°F (feels like {feels_f}°F)"
        else:
            temp_display = f"{temp_c}°C (feels like {feels_c}°C)"

        return {
            "city": city_name,
            "condition": desc,
            "temperature": temp_display,
            "temp_c": temp_c,
            "temp_f": temp_f,
            "feels_like_c": feels_c,
            "feels_like_f": feels_f,
            "humidity_pct": humidity,
            "wind": f"{wind_kmph} km/h {wind_dir}",
            "visibility_km": visibility,
            "uv_index": uv_index,
            "source": "wttr.in",
        }
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("weather_fetch parse error: %s", exc)
        return {"error": f"Failed to parse weather data: {exc}", "raw": data}
