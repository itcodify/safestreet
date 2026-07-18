# SafeStreet — Mumbai Monsoon Flood Risk Advisor

Live rainfall + community reports + an ADK/Gemini agent, all served from a single
FastAPI process so it deploys cleanly as one Render web service.

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/itcodify/safestreet)

1. **Push these changes to GitHub** (they replace your existing files — see
   "What changed" below).
2. Click the button above. Render reads `render.yaml` and creates the service
   automatically (Docker environment, free plan).
3. When Render asks for environment variables, fill in:
   | Variable | Where to get it |
   |---|---|
   | `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) — create a **new** key, don't reuse the old one |
   | `OWM_API_KEY` | [OpenWeatherMap → API keys](https://home.openweathermap.org/api_keys) — create a **new** key |
   | `FIREBASE_CREDENTIALS_JSON` | Firebase Console → Project Settings → Service Accounts → **Generate new private key** → open the downloaded file → paste its entire contents as the value |

   `GOOGLE_GENAI_USE_VERTEXAI` is already set to `FALSE` in `render.yaml`.
4. Click **Apply** / **Create Web Service**. First build takes a few minutes.
5. Once live, open the Render URL — frontend, agent chat, and weather data
   all come from that one URL.

No manual "clickable steps to deploy" beyond that — the blueprint does the
rest.

## Why you need new keys (important)

Rotate all three credentials above before deploying, even if you deploy
somewhere other than Render:

- `agent/.env` in the uploaded project contained a live Google API key and
  the path to a Firebase service-account key.
- `firebase-key.json` contained a live Firebase service-account private key.
- Both `agent/agent.py` and `frontend/index.html` had an OpenWeatherMap key
  hardcoded — the frontend one was shipped to every browser that loaded the
  page, fully visible in page source.

None of these were found in your git history, so they were never pushed
publicly. But since they've now been shared outside your machine, treat them
as burned:
- Google AI Studio → delete the old key, create a new one.
- OpenWeatherMap → regenerate the key.
- Firebase Console → Service Accounts → delete the old key, generate a new
  one (old private keys can't be "changed", only revoked and replaced).

## What changed and why

| File | Problem | Fix |
|---|---|---|
| `server.py` (new) | Frontend and agent ran as two separate processes on two ports (5500 + 8080) — Render only exposes one port | Single FastAPI process: mounts the ADK agent, proxies weather calls, and serves the frontend, all on `$PORT` |
| `Dockerfile` | `RUN adk web agent` at build time is a long-running server command — it hangs the Docker build forever | Removed. Container just installs deps and runs `python server.py` at start |
| `agent/agent.py` | OpenWeatherMap key hardcoded in source | Reads `OWM_API_KEY` from the environment |
| `frontend/index.html` | OpenWeatherMap key hardcoded and shipped to every browser; agent URLs pointed at `localhost:8080` | Weather/geocoding calls now go through `/api/weather-alerts` and `/api/geocode` (key stays server-side); agent calls use relative URLs (`/run_sse`, etc.) that work wherever the app is hosted |
| `firebase-key.json` | Private key file, easy to accidentally commit | Not needed on Render — paste its contents into the `FIREBASE_CREDENTIALS_JSON` env var instead; `server.py` writes it to a temp file at startup. Still gitignored for local dev if you'd rather use a file there |
| `.env.example` (new) | — | Placeholder template so you know what variables to set without any real secret in the repo |

## Local development

```bash
pip install -r requirements.txt
cp .env.example agent/.env   # then fill in your own keys
# either drop a local firebase-key.json next to server.py (gitignored),
# or set FIREBASE_CREDENTIALS_JSON in your shell
python server.py
```

Open http://localhost:8080 — frontend and agent are both served from there.

## One more thing worth knowing

The Firebase Web `apiKey` inside `frontend/index.html`'s `firebaseConfig` is
**not** a secret in the way the others are — Firebase web API keys are
designed to be public and are meant to be restricted by your Firestore
Security Rules, not by hiding the key. Since anyone can currently call
`addDoc` on `community_reports` from the browser, it's worth adding
Firestore rules (e.g. requiring a plausible `severity` value, rate-limiting,
or App Check) before this goes beyond a hackathon demo — just flagging it
for a future pass, not something I've changed here.
