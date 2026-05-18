# ------------------------------------------------------------
# STEP 1: Clean all school CSV files and merge into one file
# ------------------------------------------------------------

import pandas as pd

# Columns to keep
columns_to_keep = [
    "PROVINCIE",
    "INSTELLINGSNAAM",
    "STRAATNAAM",
    "HUISNUMMER-TOEVOEGING",
    "POSTCODE",
    "PLAATSNAAM",
    "GEMEENTENUMMER",
    "GEMEENTENAAM",
    "TELEFOONNUMMER"
]

# Input file, output file, and school type
file_groups = [
    ("01.-hoofdvestigingen-basisonderwijs.csv", "filtered_primaryschools.csv", "primary"),
    ("01.-hoofdvestigingen-vo.csv", "filtered_secondaryschools.csv", "secondary"),
    ("01.-adressen-mbo-instellingen.csv", "filtered_vocationalschools.csv", "vocational"),
    ("01.-instellingen-hbo-en-wo.csv", "filtered_college_uni.csv", "university"),
]

# Clean each file
for input_file, output_file, school_type in file_groups:
    print(f"Processing {input_file}...")

    # Read CSV
    df = pd.read_csv(
        input_file,
        sep=";",
        encoding="cp1252",
        dtype=str
    )

    # Remove spaces from column names
    df.columns = df.columns.str.strip()

    # Keep only relevant columns
    filtered_df = df[columns_to_keep].copy()

    # Add school type column
    filtered_df["school_type"] = school_type

    # Save cleaned file
    filtered_df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"Saved {len(filtered_df)} rows to {output_file}")

# Merge all cleaned files
all_files = [
    "filtered_primaryschools.csv",
    "filtered_secondaryschools.csv",
    "filtered_vocationalschools.csv",
    "filtered_college_uni.csv"
]

df_list = [pd.read_csv(f, dtype=str) for f in all_files]
df_final = pd.concat(df_list, ignore_index=True)

# Save merged file
df_final.to_csv("final_schools.csv", index=False, encoding="utf-8-sig")

print(f"\nCreated final_schools.csv with {len(df_final)} rows.")

# ------------------------------------------------------------
# STEP 2: Convert addresses in final_schools.csv to coordinates
# using the Dutch PDOK Locatieserver API
# ------------------------------------------------------------

import pandas as pd
import requests
import time

# Load merged schools file
df = pd.read_csv("final_schools.csv", dtype=str)

# Normalize column names
df.columns = df.columns.str.lower()

# Replace missing values with empty strings
df = df.fillna("")

# ------------------------------------------------------------
# Function to get latitude and longitude from PDOK API
# ------------------------------------------------------------
def get_coordinates(row):
    # Build full address
    address = (
        f"{row['straatnaam']} "
        f"{row['huisnummer-toevoeging']} "
        f"{row['postcode']} "
        f"{row['plaatsnaam']}"
    ).strip()

    try:
        # Query PDOK API
        url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
        params = {"q": address}

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        docs = data["response"]["docs"]

        # If no result found
        if len(docs) == 0:
            return pd.Series([None, None])

        # Extract coordinates from "POINT(lon lat)"
        point = docs[0]["centroide_ll"]
        coords = point.replace("POINT(", "").replace(")", "").split()

        longitude = float(coords[0])
        latitude = float(coords[1])

        # Be polite to the API
        time.sleep(0.1)

        return pd.Series([latitude, longitude])

    except Exception:
        return pd.Series([None, None])

# ------------------------------------------------------------
# Apply function to every row
# ------------------------------------------------------------
print("Converting addresses to coordinates...")

df[["latitude", "longitude"]] = df.apply(get_coordinates, axis=1)

# Remove rows where coordinates were not found
df = df.dropna(subset=["latitude", "longitude"])

# Save final file
df.to_csv(
    "final_schools_with_coordinates.csv",
    index=False,
    encoding="utf-8-sig"
)

print(f"Finished! Saved {len(df)} rows to final_schools_with_coordinates.csv")

