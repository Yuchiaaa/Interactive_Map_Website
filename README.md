# Interactive Environmental Map — Netherlands

A full-stack geospatial web application for visualising, analysing, and exporting environmental and administrative datasets across the Netherlands. Built with Python/Flask, PostGIS, and a Leaflet.js frontend.

---

## Features

- **Interactive Map** — Pan, zoom, and click any feature for a detailed info panel with buffer analysis.
- **13 Spatial Layers**:
  | Layer | Source |
  |---|---|
  | BRP Crop Parcels (2009–2025) | RVO / PDOK |
  | BAG Buildings | Kadaster / PDOK |
  | KRD Livestock Farms & Stallen | KRD / iGoView |
  | Natura 2000 Protected Sites | Ministerie van LNV / PDOK |
  | Nature Network NL (NNN) | Provincies / PDOK INSPIRE |
  | Kadastrale Kaart | Kadaster / PDOK BRK |
  | Bestuurlijke Grenzen | Kadaster / PDOK |
  | Pesticides Atlas (2009–2024) | Bestrijdingsmiddelenatlas |
  | Schools | DUO |
  | Health Facilities | HOTOSM / OpenStreetMap |
  | Water Hydrography | Waterschappen / PDOK INSPIRE |
  | WFD Surface Water | Rijkswaterstaat / PDOK |
  | Waterschappen | Unie van Waterschappen / PDOK |
- **Analytics Dashboard** — Live charts and KPIs powered by Chart.js, reading directly from the database.
- **Excel Export** — Export any active layer(s) for the current map view, including cross-dataset merge sheets (e.g. farms within 10 km of Natura 2000).
- **PDF / PNG Export** — Capture the current map view as a PDF report or image.
- **Buffer Analysis** — Click any feature to draw a configurable buffer and see what intersects within it.
- **ETL Pipeline** — Per-dataset Python scripts in `etl/` to load data from PDOK, Kadaster, DUO, and more.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask 3, SQLAlchemy 2, GeoAlchemy2 |
| Database | PostgreSQL 14+ with PostGIS 3 |
| Geospatial | GeoPandas, Shapely, Fiona, PyProj |
| Frontend | Leaflet.js, Turf.js, Chart.js, jsPDF, html2canvas, SheetJS |
| Export | Pandas, OpenPyXL |
| Production | Gunicorn |

---

## Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ with PostGIS 3 extension enabled
- `ogr2ogr` (GDAL) available in PATH — required by `etl/master_sync.py`

### 1. Clone

```bash
git clone https://github.com/Yuchiaaa/Interactive_Map_Website.git
cd Interactive_Map_Website
```

### 2. Virtual environment & dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Database

```sql
CREATE DATABASE aarde_db;
\c aarde_db
CREATE EXTENSION postgis;
```

### 4. Environment variables

Create a `.env` file in the project root:

```dotenv
DATABASE_URL=postgresql://your_user:your_password@localhost:5432/aarde_db
SECRET_KEY=change-me-in-production
```

### 5. Load data

Each ETL script downloads and loads one dataset. Update the file paths in the `if __name__ == "__main__"` block of each script before running.

```bash
python etl/load_brp.py            # BRP crop parcels (one file per year)
python etl/load_bag.py            # BAG buildings
python etl/load_grenzen.py        # Administrative boundaries
python etl/load_krd.py            # KRD livestock farms
python etl/load_pesticides.py     # Pesticides Atlas
python etl/load_schools.py        # Schools (DUO)
python etl/load_healthcare.py     # Health facilities (HOTOSM)
python etl/load_natura2000.py     # Natura 2000
python etl/load_nnn.py            # Nature Network NL
python etl/load_hydrography.py    # Water hydrography
python etl/load_wfd_surface_water.py
python etl/load_kadastralekaart.py
python etl/load_waterschappen.py
```

### 6. Create the BRP trend cache

The BRP Trend Analysis chart requires a materialized view. Run this once after loading BRP data, and refresh it whenever new BRP years are added:

```sql
CREATE MATERIALIZED VIEW brp_trend_cache AS
SELECT year, gewas,
    SUM(ST_Area(ST_Transform(geometry, 28992)) / 10000) AS area_ha
FROM brp_parcels
GROUP BY year, gewas
WITH DATA;

CREATE INDEX brp_trend_cache_year_idx ON brp_trend_cache (year);
```

### 7. Run

```bash
python run.py
```

| Page | URL |
|---|---|
| Home | http://localhost:5006 |
| Map | http://localhost:5006/index |
| Dashboard | http://localhost:5006/dashboard |

---

## Docker

See [Docker Setup](#docker-setup) below, or run directly:

```bash
docker build -t aarde-map .
docker run -p 8000:8000 --env-file .env aarde-map
```

The app will be available at **http://localhost:8000**.

> The Docker image runs the app only. The PostGIS database must be running separately (see `DATABASE_URL` in `.env`).

---

## Project Structure

```
Interactive_Map_Website/
├── app/
│   ├── __init__.py       # Flask app factory
│   ├── models.py         # SQLAlchemy ORM models
│   ├── routes.py         # All API endpoints and page routes
│   └── utils.py          # Shared helpers
├── etl/
│   ├── load_*.py         # Per-dataset ETL loaders
│   ├── truncate_*.py     # Per-dataset table truncators
│   └── master_sync.py    # Orchestrates automated layers
├── static/
│   ├── css/style.css
│   └── js/map.js
├── templates/
│   ├── home.html
│   ├── index.html        # Main map interface
│   └── dashboard.html
├── run.py                # Dev server entry point
├── Procfile              # Gunicorn config for PaaS deployment
├── requirements.txt
└── .env                  # Local config (create manually, never commit)
```

---

## API Reference

All endpoints return GeoJSON or JSON. Spatial queries require a `bbox` parameter in `west,south,east,north` format (WGS84).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/brp_parcels` | BRP crop parcels for a bbox and year |
| GET | `/api/brp_trend` | Year-over-year crop area totals (from cache) |
| GET | `/api/brp_pivot` | Crop area summary for a year |
| GET | `/api/brp_gemeenten` | List of gemeente names present in BRP data |
| GET | `/api/bag_buildings` | BAG building footprints |
| GET | `/api/natura2000_areas` | Natura 2000 polygons |
| GET | `/api/nnn` | Nature Network NL polygons |
| GET | `/api/grenzen` | Administrative boundaries |
| GET | `/api/krd_farms` | KRD livestock farms |
| GET | `/api/krd_stallen` | KRD individual stallen |
| GET | `/api/pesticides` | Pesticide measurement stations |
| GET | `/api/health_facilities` | Health facility points |
| GET | `/api/schools` | School points |
| GET | `/api/hydrography` | Water hydrography lines |
| GET | `/api/hydrography_main` | Primary water hydrography lines |
| GET | `/api/hydrography_other` | Secondary water hydrography lines |
| GET | `/api/wfd_surface_water` | WFD surface water bodies |
| GET | `/api/waterschappen` | Water authority boundaries |
| GET | `/api/kadastralekaart` | Cadastral parcels |
| GET | `/api/kad_gemeenten` | List of gemeente names present in Kadastrale Kaart data |
| GET | `/api/available_years` | Available years per temporal dataset |
| GET | `/api/dashboard_stats` | Aggregated stats for all dashboard charts |
| GET | `/api/buffer_context` | Gemeente, province, and nearest Natura 2000 context for a lat/lng + radius |
| GET | `/api/summary_regions` | All gemeenten and provincies available for region filtering |
| GET | `/api/summary/<dataset>` | Region-filtered summary for a dataset |
| GET | `/api/gemeente_boundary` | Polygon boundary of a single gemeente |
| POST | `/api/export_excel` | Download active layers as Excel workbook |
