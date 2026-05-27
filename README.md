# Dublin Mobility Intelligence Platform

A real-time data engineering platform that monitors Dublin's public transit network using NTA GTFS feeds. Built as a portfolio project demonstrating modern cloud-native architecture, ETL pipelines, and live data visualization.

![Dublin Mobility Command Center](https://img.shields.io/badge/Status-Live-brightgreen) ![React](https://img.shields.io/badge/React-18-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)

## Live Demo

| Service | URL |
|---------|-----|
| **Frontend** | [dublin-mobility-platform.vercel.app](https://dublin-mobility-platform.vercel.app) |
| **API** | [dublin-mobility-api.onrender.com](https://dublin-mobility-api.onrender.com) |

> Note: API runs on Render free tier and may take ~30 seconds to wake up on first request.

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  GitHub Actions │────▶│ Neon PostgreSQL │────▶│  Render FastAPI │────▶│  Vercel React   │
│   (ETL Cron)    │     │   (Database)    │     │     (API)       │     │   (Frontend)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
        │                                                
        ▼                                                
┌─────────────────┐                                      
│   NTA GTFS-R    │                                      
│   (Data Source) │                                      
└─────────────────┘                                      
```

### Data Flow
1. **GitHub Actions** runs ETL every 5 minutes via cron
2. **NTA GTFS-Realtime API** provides vehicle positions and trip updates
3. **Bronze Layer** stores raw GTFS protobuf data as JSONB
4. **Silver Layer** transforms data into analytics-ready tables
5. **FastAPI** serves REST endpoints for frontend consumption
6. **React Dashboard** visualizes live fleet status on Leaflet maps

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Orchestration** | GitHub Actions (cron-based ETL) |
| **Data Source** | NTA GTFS-Realtime API (Protobuf) |
| **Database** | Neon PostgreSQL (512MB free tier) |
| **Backend** | FastAPI + SQLAlchemy + Psycopg2 |
| **Frontend** | React 18 + Vite + Leaflet.js |
| **Hosting** | Vercel (frontend) + Render (API) |
| **CI/CD** | GitHub Actions |

---

## Features

### Real-Time Fleet Tracking
- Live GPS positions for 1,300+ Dublin Bus vehicles
- Color-coded delay status (Early → On-time → Minor → Moderate → Severe → Critical)
- Click-to-zoom incident investigation

### Delay Analytics
- Categorized delay statistics with trend indicators
- Worsening (↑) / Improving (↓) / Stable (→) trend tracking
- 30-minute historical comparison

### Ghost Bus Detection
- Identifies trips with delay data but no live GPS signal
- Toggle to show/hide offline vehicles
- Last known position markers with dashed borders

### Route Intelligence
- 119 Dublin Bus routes with origin-destination descriptions
- Parsed from NTA VDV452 static GTFS data
- Route filtering with full descriptions

### Mobile Responsive
- Full-screen map-first design
- Collapsible sidebar via hamburger menu
- Touch-optimized controls

---

## Project Structure

```
dublin-mobility-platform/
├── .github/
│   └── workflows/
│       └── etl.yml              # GitHub Actions ETL pipeline
├── etl/
│   ├── run_etl.py               # Standalone ETL script
│   └── requirements.txt         # ETL dependencies
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Main React component
│   │   ├── App.css              # Styles (mobile responsive)
│   │   └── routeDescriptions.js # VDV452 route data
│   ├── package.json
│   └── vite.config.js
├── api.py                       # FastAPI backend
├── requirements.txt             # API dependencies
├── render.yaml                  # Render deployment config
├── runtime.txt                  # Python version spec
└── README.md
```

---

## Deployment Guide

### Prerequisites
- GitHub account
- Neon PostgreSQL database
- NTA GTFS API key ([register here](https://developer.nationaltransport.ie/))
- Render account
- Vercel account

### 1. Database Setup (Neon)
1. Create a new Neon project
2. Copy the connection string
3. Tables are auto-created by the ETL script

### 2. API Deployment (Render)
1. Connect your GitHub repo to Render
2. Set environment variables:
   - `DATABASE_URL`: Neon connection string
3. Deploy as Web Service with `render.yaml`

### 3. Frontend Deployment (Vercel)
1. Import GitHub repo to Vercel
2. Set root directory to `frontend`
3. Set environment variable:
   - `VITE_API_URL`: Your Render API URL
4. Deploy

### 4. ETL Pipeline (GitHub Actions)
1. Add repository secrets:
   - `NTA_API_KEY`: Your NTA developer key
   - `DATABASE_URL`: Neon connection string
2. The workflow runs automatically every 5 minutes

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /vehicles` | Latest GPS position per vehicle |
| `GET /delays` | Trips with delay data, supports `?category=` and `?limit=` |
| `GET /delays/summary` | Aggregated counts by delay category |
| `GET /routes` | Unique route codes |
| `GET /health` | Database connectivity check |

### Example Response
```json
GET /delays?category=critical&limit=5

[
  {
    "route_id": "1 27A c a",
    "avg_delay_minutes": 25.3,
    "delay_category": "critical",
    "trend": "worsening",
    "trend_change_minutes": 8.2,
    "last_lat": 53.3498,
    "last_lon": -6.2603
  }
]
```

---

## Database Schema

### Bronze Layer (Raw Data)
```sql
bronze_vehicle_positions (vehicle_id, trip_id, route_id, raw_data JSONB, ingestion_timestamp)
bronze_trip_updates (trip_id, route_id, raw_data JSONB, ingestion_timestamp)
```

### Silver Layer (Transformed)
```sql
silver_vehicle_positions (vehicle_id, trip_id, latitude, longitude, route_id, gps_timestamp, loaded_at)
silver_trip_delays (trip_id, route_id, avg_delay_minutes, delay_category, trend, loaded_at)
```

---

## Local Development

### Backend
```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Set environment variables
set DATABASE_URL=postgresql://...
set NTA_API_KEY=your_key

# Run API
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### ETL (Manual Run)
```bash
cd etl
pip install -r requirements.txt
python run_etl.py
```

---

## Data Sources

| Source | Description |
|--------|-------------|
| [NTA GTFS-Realtime](https://developer.nationaltransport.ie/) | Live vehicle positions and trip updates |
| [NTA GTFS Static](https://www.transportforireland.ie/transitData/PT_Data.html) | Route descriptions (VDV452 LINE.x10 format) |

---

## Future Enhancements

- [ ] Delay Prediction Model (XGBoost/LSTM)
- [ ] Anomaly Detection (Isolation Forest)
- [ ] Route Clustering Analysis (K-Means)
- [ ] Historical Performance Dashboard
- [ ] Push Notifications for Severe Delays
- [ ] Multi-city Support (Cork, Galway)

---

## License

This project is open source and available under the [MIT License](LICENSE).

---

## Acknowledgments

- National Transport Authority (NTA) Ireland for GTFS data access
- Dublin Bus for real-time transit data
- The open-source community for amazing tools

---

<p align="center">
  <strong>Built with and in Dublin</strong>
</p>
