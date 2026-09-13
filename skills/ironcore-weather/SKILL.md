---
name: ironcore-weather
description: Get current weather and 3-day forecast for any city worldwide. Free, no API key needed — uses wttr.in.
metadata: {"openclaw": {"emoji": "🌤️", "requires": {"bins": ["python3"]}}}
---

# IronCore Weather

Get real-time weather for any city. No API key required — uses the free wttr.in service.

## When to use
Trigger when the user asks about weather, temperature, forecast, rain, humidity, or conditions for any location.

## How to run

Extract the city name, then run this Python command via exec:

```python
python3 -c "
import urllib.request, json, sys
city = 'CITY_NAME'.replace(' ', '+')
url = f'https://wttr.in/{city}?format=j1'
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.load(r)
    cur = d['current_condition'][0]
    area = d['nearest_area'][0]
    name = area['areaName'][0]['value']
    country = area['country'][0]['value']
    print(f'=== Weather: {name}, {country} ===')
    print(f'Temperature : {cur[\"temp_C\"]}°C (feels {cur[\"FeelsLikeC\"]}°C)')
    print(f'Condition   : {cur[\"weatherDesc\"][0][\"value\"]}')
    print(f'Humidity    : {cur[\"humidity\"]}%')
    print(f'Wind        : {cur[\"windspeedKmph\"]} km/h {cur[\"winddir16Point\"]}')
    print(f'Visibility  : {cur[\"visibility\"]} km')
    print('')
    print('3-Day Forecast:')
    for day in d.get('weather', []):
        desc = day['hourly'][4]['weatherDesc'][0]['value']
        print(f'  {day[\"date\"]}: {day[\"mintempC\"]}–{day[\"maxtempC\"]}°C, {desc}')
except Exception as e:
    print(f'Error: {e}')
"
```

Replace `CITY_NAME` with the actual city (e.g. `Hanoi`, `Ho Chi Minh`, `New York`, `Tokyo`).

## Output format
Report the weather in a clean, readable message. Include temperature in both Celsius and a friendly description. 
If the user mentions a Vietnamese city, add a note in Vietnamese.

## Error handling
If the city is not found, ask the user to clarify the city name or try the English name.
