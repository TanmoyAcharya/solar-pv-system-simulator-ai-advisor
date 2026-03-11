# Solar PV System Simulator + AI Advisor

A local Streamlit application for modeling rooftop PV output, hourly storage dispatch, time-of-use economics, and design guidance.

## What it does

- Integrates optional Open-Meteo geocoding plus historical hourly solar weather by location and year.
- Simulates hourly PV generation, self-consumption, exports, battery charging and discharging, grid charging, and time-of-use import costs.
- Estimates annual savings, simple payback, lifetime generation, carbon offset, peak-period coverage, and battery cycling.
- Produces either a heuristic advisor report or a live API-backed LLM advisor report with design recommendations for panel count, orientation, storage, and economic fit.
- Compares multiple scenarios so you can evaluate demand-match, self-use, and roof-max strategies side by side.

## Project structure

- `app.py`: Streamlit UI.
- `solar_simulator/simulator.py`: PV and energy flow model.
- `solar_simulator/advisor.py`: Recommendation engine and scenario builder.
- `solar_simulator/weather.py`: Location search and Open-Meteo weather integration.
- `solar_simulator/llm_advisor.py`: OpenAI-compatible API client for live advisor output.
- `solar_simulator/models.py`: Shared data models.

## Run locally

1. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Start the app:

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run app.py
   ```

3. Open the local Streamlit URL shown in the terminal.

## Optional LLM advisor configuration

The live advisor uses an OpenAI-compatible `chat/completions` API.

- `OPENAI_API_KEY`: API key.
- `OPENAI_BASE_URL`: Optional, defaults to `https://api.openai.com/v1`.
- `OPENAI_MODEL`: Optional, defaults to `gpt-4.1-mini`.

If the API key or endpoint is missing, the app falls back to the built-in heuristic advisor.

## Notes

- All financial fields use generic local currency units so you can adapt the model to any market.
- The weather integration relies on Open-Meteo public APIs and falls back to a synthetic irradiance profile if the API is unavailable.
- The LLM advisor is optional and falls back automatically if the API call fails or returns invalid data.
- This is a screening tool, not a replacement for detailed engineering, shading analysis, or utility interconnection studies.