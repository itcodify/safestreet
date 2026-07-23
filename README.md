# SafeStreet 🌧️
### A real-time, street-level flood-risk advisor for Mumbai's monsoon commuters

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/itcodify/safestreet)

Built by **Aahana Gupta** for the Google Cloud Gen AI Academy — APAC Edition.

---

## The problem

Weather apps tell you "Heavy rain in Mumbai." They don't tell you whether the
specific stretch of road you're about to cross actually floods, whether the
drainage in that pocket of the city can handle it, or whether it's been
raining long enough for the ground to already be saturated. That
information exists — scattered across WhatsApp forwards and random tweets —
but there's no way to know if it's still true by the time it reaches you.

**SafeStreet closes that gap**: it turns "it's raining" into an actual
street-level risk percentage, and pairs it with the safety tools you need
once you know the risk — nearby hospitals, one-tap emergency numbers, and an
anonymous SOS system — all wrapped in a conversational agent so you can just
ask *"should I leave for Dadar right now?"* and get a straight answer.

## What it does

- **Live risk dashboard** — curated Mumbai / Navi Mumbai / Thane flood
  hotspots, refreshed every minute, plus global search for any location.
- **Risk score that's more than "how hard is it raining"** — it blends:
  - continuous rain *duration* (not just the current rate), calculated by
    walking backward through hourly rainfall history
  - a curated drainage/vulnerability baseline per ward, since live
    drainage-capacity data doesn't exist publicly
  - live news signals, so a confirmed flooding report pushes the score up
    in real time
  - community reports, which boost the score immediately and decay out
    after a few hours
- **Interactive hotspot map** (Leaflet.js) with color-coded risk pins.
- **A Gemini-powered conversational agent** (built on Google's Agent
  Development Kit) that reasons over real tools — get rainfall, get
  community reports, compute risk, recommend an action — instead of
  guessing an answer from one big prompt.
- **Safety layer**: geofencing for your immediate surroundings, a nearby
  hospital finder, one-tap emergency numbers, and an anonymous SOS system
  that never shares your phone number or personal details with anyone.
- **Honest about its own limits** — if a live-data source (Open-Meteo,
  GNews) is temporarily unavailable, usually because of a free-tier daily
  quota, the UI says so plainly instead of silently showing a number that
  might not reflect reality.

## Tech stack

| Piece | Used for |
|---|---|
| **Gemini 2.5 Flash** (via the Gemini API) | Powers the conversational agent |
| **Google Agent Development Kit (ADK)** | Gives the agent focused, callable tools instead of one large prompt |
| **Google Firestore** | Real-time sync for community reports and SOS |
| **Open-Meteo** | Free hourly precipitation history → real rain duration |
| **OpenWeatherMap** | Live station/satellite rainfall observations |
| **GNews API** | Live flooding-related news signal (cached server-side) |
| **OpenStreetMap Overpass API** | Nearby hospital/facility lookup |
| **FastAPI (Python)** | Single backend process — serves the frontend, proxies weather calls, and hosts the agent |
| **Leaflet.js** | Interactive hotspot map |
| **Docker + Render** | Deployment — one containerized service, one URL |

## Architecture

```
Browser (frontend/index.html)
   │
   ├── /api/weather-alerts, /api/geocode, /api/current-weather  → server.py → OpenWeatherMap
   ├── /run_sse (agent chat)                                     → server.py → ADK Agent → Gemini
   └── Firestore (client SDK)                                    → community reports, SOS

server.py (FastAPI, single process, single port)
   ├── mounts the ADK agent (agent/agent.py)
   ├── proxies all third-party weather/geocoding calls (keeps API keys server-side)
   └── serves the static frontend

shared/risk_model.py
   └── the actual risk-scoring math: rainfall + duration + drainage baseline
       + vulnerability + community-report boost (with time decay)
```

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example agent/.env   # then fill in your own keys — see below
python server.py
```

Open **http://localhost:8080** — the frontend, the agent chat, and all
weather data are served from that one URL.

### Environment variables

| Variable | Where to get it |
|---|---|
| `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) — powers the Gemini agent |
| `OWM_API_KEY` | [OpenWeatherMap → API keys](https://home.openweathermap.org/api_keys) |
| `GNEWS_API_KEY` | [gnews.io](https://gnews.io) — free tier, 100 requests/day, no card needed. Powers the news signal; without it you'll see "GNews API is not configured" |
| `FIREBASE_CREDENTIALS_JSON` | Firebase Console → Project Settings → Service Accounts → **Generate new private key** → paste the full JSON contents as the value. (Locally you can instead drop a `firebase-key.json` file next to `server.py` — gitignored.) |
| `GOOGLE_GENAI_USE_VERTEXAI` | Set to `FALSE` — the agent calls Gemini directly via the Gemini API, not through Vertex AI |

None of these keys should ever be committed — `agent/.env` and
`firebase-key.json` are gitignored.

## Deploying to Render

1. Push to GitHub.
2. Click the **Deploy to Render** button above — Render reads `render.yaml`
   and creates the service automatically (Docker environment).
3. Fill in the four environment variables from the table above when Render
   asks for them.
4. Click **Apply**. First build takes a few minutes; after that, the Render
   URL serves everything — frontend, agent, and weather data — from one
   place.

## A design note: honesty over polish

Open-Meteo and GNews are both excellent free services, but they have daily
quotas. The easy fix — silently fall back to a default when a call fails —
is the wrong one for a safety tool: showing "12% risk" because an API call
failed, instead of "we don't actually know right now," is actively
misleading when the stakes are real.

So every rainfall fetch falls back to the **last known good reading** for
that exact spot (never a fabricated zero), and a visible banner tells the
user plainly when live data is stale — rather than pretending everything is
fine. The agent follows the same rule: if it can't determine real rain
duration, it says so instead of presenting a confident number built on
missing data.

## What's next

- Expanding curated ward coverage beyond Mumbai/Navi Mumbai/Thane to other
  flood-prone Indian cities.
- Push notifications when a saved location crosses into "High Risk."
- Tighter agent-driven rerouting suggestions using live map data.

## Security note

The Firebase Web `apiKey` inside `frontend/index.html`'s `firebaseConfig`
is **not** a secret in the way the other keys are — Firebase web API keys
are meant to be public and are restricted by Firestore Security Rules, not
by hiding the key. Since community reports are currently writable directly
from the browser, adding Firestore rules (validating `severity` values,
rate-limiting, or App Check) is worth doing before this goes beyond a
hackathon demo.

---

*Built during the Google Cloud Gen AI Academy, APAC Edition — Meet the
Builders.*
