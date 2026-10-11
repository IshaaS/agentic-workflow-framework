# agentctl-weather-agent

Agent `weather_provider`, capability `weather.forecast`: `city` → `weather`.

```python
{"weather": {"temperature_c": 22.0, "condition": "rainy",
             "precipitation_probability": 65, "wind_speed_kmh": 15.0}}
```

- Data comes from [Open-Meteo](https://open-meteo.com/en/docs): the
  [geocoding API](https://open-meteo.com/en/docs/geocoding-api) finds the city,
  then the forecast API returns hourly values for its coordinates with
  `timezone=auto`, Celsius and km/h.
- The agent returns the row for the current hour in the city's local time,
  using the response's `utc_offset_seconds`.
- `condition` is one of `clear`, `cloudy`, `rainy`, `snowy`, `stormy`,
  `unknown`, mapped from WMO weather codes. Fog is reported as `cloudy`.
- Requests use only the standard library, with a 10 second timeout.
- Errors:
  - A blank city raises `ValueError`.
  - An unknown city, an HTTP error, a timeout or a malformed response raises
    `WeatherAPIError`.
  - The agent never falls back to made-up weather.
- Open-Meteo's free API is for non-commercial use; see its terms.

## Live smoke check (optional, uses the network)

The automated tests never call the network. To try the real API:

```bash
python -c "from agentctl_core import RuntimeContext; from agentctl_agents.weather.agent import WeatherAgent; print(WeatherAgent().run({'city': 'Dallas'}, RuntimeContext('s', 'w', {})))"
```
