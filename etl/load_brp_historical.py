"""
BRP Historical Loader — reference file for bulk-loading all available years.

Nobody runs this file directly to batch-download. The actual files need to be
downloaded manually (they're large — multiple GB each). Once downloaded, point
load_brp_gdal() at each file and it handles the rest.

Download page (ATOM feed):
  https://service.pdok.nl/rvo/gewaspercelen/atom/basisregistratie_gewaspercelen_brp.xml

File URLs by year
-----------------
Format changes after 2019: 2009-2019 are ZIP (shapefile inside), 2020-2025 are GPKG.
All files use the Dutch national CRS (EPSG:28992); the loader reprojects to WGS84.

Year  Format  URL
2025  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2025.gpkg
2024  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2024.gpkg
2023  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2023.gpkg
2022  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2022.gpkg
2021  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2021.gpkg
2020  GPKG    https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2020.gpkg
2019  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2019.zip
2018  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2018.zip
2017  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2017.zip
2016  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2016.zip
2015  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2015.zip
2014  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2014.zip
2013  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2013.zip
2012  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2012.zip
2011  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2011.zip
2010  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2010.zip
2009  ZIP     https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2009.zip

How to load a single year
--------------------------
1. Download the file from the URL above.
2. Edit the DOWNLOADS dict below with the path to the file.
3. Run this script, or call load_brp_gdal() directly from a Python shell.

   python etl/load_brp_historical.py

How to load all downloaded years at once
-----------------------------------------
Edit DOWNLOADS so every entry points to the file on disk, then run the script.
Files that are None are skipped automatically.

How to clear the table and start fresh
---------------------------------------
   python etl/truncate_brp.py

After truncating, re-run this script (or load_brp.py) to reload.

Column mapping
--------------
The loader writes three columns into brp_parcels:
  gewas     — Dutch crop name  (e.g. "Mais, snij-")
  gewascode — numeric crop code (e.g. 259)
  year      — harvest year     (e.g. 2021)

These names match what routes.py queries. Do not rename them.
"""

import os
from load_brp import load_brp_gdal

# ---------------------------------------------------------
# Edit these paths to match where you saved the files.
# Set to None for years you haven't downloaded yet.
# ---------------------------------------------------------
DOWNLOADS = {
    2025: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2025.gpkg"
    2024: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2024.gpkg"
    2023: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2023.gpkg"
    2022: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2022.gpkg"
    2021: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2021.gpkg"
    2020: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2020.gpkg"
    2019: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2019.zip"
    2018: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2018.zip"
    2017: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2017.zip"
    2016: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2016.zip"
    2015: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2015.zip"
    2014: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2014.zip"
    2013: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2013.zip"
    2012: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2012.zip"
    2011: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2011.zip"
    2010: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2010.zip"
    2009: None,  # r"C:\Downloads\brpgewaspercelen_definitief_2009.zip"
}


def load_all():
    """Load every year that has a file path configured in DOWNLOADS."""
    pending = {year: path for year, path in DOWNLOADS.items() if path is not None}

    if not pending:
        print("Nothing to load. Edit the DOWNLOADS dict with your local file paths.")
        return

    print(f"Loading {len(pending)} year(s): {sorted(pending.keys())}")
    print("=" * 60)

    for year in sorted(pending.keys()):
        path = pending[year]
        if not os.path.exists(path):
            print(f"[{year}] Skipped — file not found: {path}")
            continue
        print(f"\n[{year}] Loading {os.path.basename(path)}...")
        # Year is already in the filename, so manual_year is only needed if the
        # filename doesn't contain a 4-digit year (unlikely for official PDOK files).
        load_brp_gdal(path, manual_year=year)
        print(f"[{year}] Done.")

    print("\n" + "=" * 60)
    print("All configured years loaded.")


if __name__ == "__main__":
    load_all()
