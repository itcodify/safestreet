# SafeStreet: Real-Time Monsoon Flood Risk Platform

## SafeStreet Overview

SafeStreet is a real-time, hyper-local monsoon flood risk assessment and intelligent decision support system. It maps and translates live climate telemetry into actionable, plain-language guidance for commuters and disaster management cells.

By calculating localized risk using continuous physical variables, SafeStreet provides a transparent, explainable decision channel powered by **Google Cloud Agent Development Kit (ADK)** and **Gemini-2.5-Flash**.

## 🚀 Key Features
- **Continuous Rain Duration Tracking:** Reads historical weather streams chronologically backward to calculate exact consecutive hours of downpour to track ground saturation.
- **Context-Aware Ambiguity Filter:** Detects broad, overlapping text search queries (e.g., "Kurla") and surfaces an interactive sub-location dropdown menu to pin down precise micro-zones.
- **Interactive Leaflet Map Canvas:** Renders dynamic, real-time circle markers color-coded by continuous hazard tiers: **Green (Safe)**, **Yellow (Watch)**, and **Red (Critical Warning).**
- **Proximity Emergency Infrastructure Pipeline:** Automatically runs a spatial bounding-box query to map verified medical facilities and hospitals within a tight 1.5km radius of a selected hotspot.
- **Gemini ADK Agent Workspace:** A natural-language interface that breaks down raw telemetry values into immediate safety advice and routing suggestions.
- **Emergency Advisory Ticker:** A persistent top-ribbon alert feed replicating critical municipal emergency broadcasts across vulnerable transit corridors.

## 🛠️ Tech Stack
- **Language & Backend:** Python 3.11+, Flask / FastAPI
- **Large Language Model Engine:** Google Vertex AI / Gemini-2.5-Flash
- **Agent Toolbelt Framework:** Google Cloud Agent Development Kit (ADK)
- **Spatial Crowdsourced Database:** Google Firestore
- **Geospatial Mapping Interface:** Leaflet.js, OpenStreetMap Overpass API

## 📦 Project Directory Structure
```plaintext
safestreet/  
├── agent.py                 # Google Cloud ADK agent configuration and tool binds  
├── risk_model.py            # Mathematical risk equations and aggregation logic  
├── requirements.txt         # Project package dependencies  
├── firebase-key.json        # Google Cloud service account key for Firestore (Keep Local)  
├── index.html               # Main dashboard user interface canvas  
```

## 💻 Terminal Setup & Execution Guide
To run the application locally, open three separate terminal windows (or tabs) to handle the frontend server, the ADK build process, and the API backend server simultaneously.

### 1. Initial Setup & Credentials Configuration
Before spinning up the servers, ensure your local environment variables are configured in your terminal.
**On Windows (Command Prompt):**
```bash
dosset OPENWEATHER_API_KEY="your_openweather_api_key_here"  
echo GOOGLE_APPLICATION_CREDENTIALS="firebase-key.json"
```

### 2. Terminal Window 1: Spin Up the Frontend Host
Navigate directly to your frontend static files directory and launch a lightweight Python development server on port 5500:
```bash
cd frontend  
python -m http.server 5500
```

### 3. Terminal Window 2: Compile the ADK Web Agent
In your project workspace root folder, build the agent schema assets via the Google Cloud Agent Development Kit:
```bash
adk web agent
```

### 4. Terminal Window 3: Start the ADK API Backend Server
Launch the underlying agent logic gateway on port 8080, explicitly authorizing incoming data requests from your running frontend portal:
```bash
adk api_server agent --port 8080 --allow_origins http://localhost:5500
```

## 🌐 Accessing the App
Once all three terminal modules are actively running, open your web browser and navigate to:
> [http://localhost:5500](http://localhost:5500)
