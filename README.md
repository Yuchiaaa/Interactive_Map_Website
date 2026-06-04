# Interactive Environmental Map of the Netherlands

This web application provides a powerful, interactive map interface for visualizing, analyzing, and exporting a wide range of environmental and administrative datasets for the Netherlands. It is built with a Python/Flask backend, a PostGIS database, and a dynamic Leaflet.js frontend.

## Key Features

- **Interactive Map Interface**: Pan and zoom across the Netherlands with a fast, responsive map.
- **Multiple Data Layers**: Visualize over a dozen distinct spatial datasets, including:
  - **Agriculture**: BRP Crop Parcels (`brp_parcels`) with a time-slider for years 2020-2025.
  - **Buildings**: BAG building footprints (`bag_buildings`) with a time-slider for construction year.
  - **Livestock**: KRD livestock farms (`krd_farms`) and individual stables (`krd_stallen`).
  - **Nature**: Natura 2000 protected sites, Nature Network Netherlands (NNN), and more.
  - **Cadastral**: Cadastral parcels from `kadastralekaart`.
  - **Infrastructure**: Schools, health facilities, and administrative boundaries (`grenzen`).
  - **Water**: Hydrography networks, Water Framework Directive (WFD) bodies, and Water Authority regions (`waterschappen`).
- **Dynamic Dashboard**: An analytics dashboard with live charts and KPIs summarizing the loaded datasets, powered by Chart.js.
- **Advanced Data Export**: Export data from the current map view or a selected area to an Excel file. Includes options for cross-dataset analysis (e.g., farms near Natura 2000 sites).
- **Robust ETL Pipeline**: A suite of Python scripts in the `etl/` directory to download, process, and load data from various sources (PDOK, Kadaster, etc.) into the database.

## Tech Stack

- **Backend**: Python, Flask, SQLAlchemy
- **Geospatial**: PostGIS, GeoAlchemy2, GeoPandas, Pyogrio, Shapely
- **Frontend**: HTML, JavaScript, Leaflet.js, Chart.js
- **Database**: PostgreSQL

---

## Setup and Installation

Follow these steps to get the application running locally.

### 1. Prerequisites

- **Python 3.8+**
- **PostgreSQL 12+** with the **PostGIS 3+** extension.
- **GDAL**: The `ogr2ogr` command-line tool must be available in your system's PATH. This is a dependency for the `etl/master_sync.py` script.

### 2. Clone the Repository

```bash
git clone https://github.com/your-username/Interactive_Map_Website.git
cd Interactive_Map_Website
```

### 3. Set Up a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
```

### 4. Install Dependencies

Create a `requirements.txt` file if one does not exist and install the packages.

```bash
pip install Flask Flask-SQLAlchemy psycopg2-binary GeoAlchemy2 pandas geopandas pyogrio python-dotenv openpyxl
```

### 5. Set Up the Database

1.  Create a new PostgreSQL database.
    ```sql
    CREATE DATABASE aarde_db;
    ```
2.  Connect to your new database and enable the PostGIS extension.
    ```sql
    \c aarde_db
    CREATE EXTENSION postgis;
    ```

### 6. Configure Environment Variables

Create a file named `.env` in the project root and add your database connection string.

```dotenv
# .env
DATABASE_URL=postgresql://your_user:your_password@localhost:5432/aarde_db
```

### 7. Load the Data

The application is data-driven and requires the datasets to be loaded into your PostGIS database.

1.  **Download Source Files**: Many ETL scripts (like `etl/load_brp.py`) require you to download the source `.gpkg` or `.csv` files first. Check the `if __name__ == "__main__"` block in each script for source URLs and required file paths.

2.  **Update Paths**: Edit the file paths in the ETL scripts (e.g., `etl/load_brp.py`, `etl/master_sync.py`) to point to your downloaded files.

3.  **Run the ETL Scripts**: Execute the scripts to populate your database. The `master_sync.py` script handles many layers automatically, while others must be run manually.

    ```bash
    # Run the master script for automated layers
    python etl/master_sync.py

    # Run manual loaders for key datasets
    python etl/load_brp.py
    python etl/load_bag.py
    python etl/load_grenzen.py
    # ... and any other loaders you need.
    ```

---

## Running the Application

Once the database is populated, start the Flask development server:

```bash
python run.py
```

The application will be available at **http://localhost:5000**.

- **Main Map**: http://localhost:5000/map
- **Dashboard**: http://localhost:5000/dashboard

## Project Structure

- `/app`: Contains the core Flask application, including models, routes, and templates.
- `/etl`: Contains all Python scripts for data extraction, transformation, and loading.
- `/static`: (Not present, but for CSS/JS if separated from templates).
- `run.py`: The entry point to start the Flask application.
- `.env`: Local environment configuration (must be created manually).