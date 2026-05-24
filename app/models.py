# app/models.py
from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from datetime import datetime

# Initialize the SQLAlchemy extension
db = SQLAlchemy()

# ---------------------------------------------------------
# 1. BRP Crop Parcels (Time Machine)
# ---------------------------------------------------------
class BRPParcel(db.Model):
    __tablename__ = 'brp_parcels'

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True, nullable=False) 
    crop_code = db.Column(db.String(50))
    crop_name = db.Column(db.String(150))
    area_ha = db.Column(db.Float)
    
    # spatial_index=True ensures fast bounding box queries
    geometry = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 2. BAG (Addresses and Buildings)
# ---------------------------------------------------------
class BAGBuilding(db.Model):
    __tablename__ = 'bag_buildings'

    id = db.Column(db.Integer, primary_key=True)
    # The official Dutch building identification number (Pandidentificatie)
    identificatie = db.Column(db.String(50), unique=True, index=True)
    oorspronkelijkbouwjaar = db.Column(db.Integer)
    status = db.Column(db.String(100))
    
    # Building footprints can be simple Polygons or complex MultiPolygons
    geometry = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 3. Natura 2000 (Protected Environmental Areas)
# ---------------------------------------------------------
class Natura2000Area(db.Model):
    __tablename__ = 'natura2000_areas'

    # Note: We omit strict property columns here because the Dutch government 
    # changes column names often. We rely on row_to_json() in routes.py instead.
    id = db.Column(db.Integer, primary_key=True)
    
    # FIX: Based on our deep debugging, this specific table uses 'geometry' as the column name
    # and uses the Dutch National CRS (EPSG:28992) which we transform on the fly in routes.py
    geometry = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=28992, spatial_index=True))

# ---------------------------------------------------------
# 4. Regionale Woondeals (Housing Agreements) - NEW
# ---------------------------------------------------------
class Woondeals(db.Model):
    __tablename__ = 'woondeals'

    # Note: Like Natura 2000, we rely on row_to_json() dynamically in the backend.
    id = db.Column(db.Integer, primary_key=True)
    # The official Dutch building identification number (Pandidentificatie)
    building_id = db.Column(db.String(50), unique=True, index=True)
    construction_year = db.Column(db.Integer)
    status = db.Column(db.String(100))
    
    # Building footprints can be simple Polygons or complex MultiPolygons, 
    # so we use the generic GEOMETRY type to accommodate both safely.
    geom = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 5. Health Facilities (HOTOSM Netherlands)
# ---------------------------------------------------------
class HealthFacility(db.Model):
    __tablename__ = 'health_facilities'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    facility_type = db.Column(db.String(100), index=True)
    healthcare = db.Column(db.String(100))
    amenity = db.Column(db.String(100))
    operator_type = db.Column(db.String(100))
    addr_city = db.Column(db.String(100))
    addr_full = db.Column(db.String(255))

    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 6. Pesticides Measurements (Bestrijdingsmiddelenatlas)
# ---------------------------------------------------------
class PesticidesMeasurement(db.Model):
    __tablename__ = 'pesticides_measurements'

    id = db.Column(db.Integer, primary_key=True)
    jaar = db.Column(db.Integer, index=True)
    meetpunt_code = db.Column(db.Integer, index=True)
    wbhcode = db.Column(db.Integer)
    stof_nr_sam = db.Column(db.Integer)
    normklas = db.Column(db.Integer)
    klasse = db.Column(db.Integer)
    mate_normov = db.Column(db.Float)
    stofnaam = db.Column(db.String(255))
    cas_nr = db.Column(db.String(50))
    meetpunt_naam = db.Column(db.String(255))

    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# Schools (Education Facilities)
# ---------------------------------------------------------
class School(db.Model):
    __tablename__ = 'schools'

    id = db.Column(db.Integer, primary_key=True)

    # Core info
    instellingsnaam = db.Column(db.String(255), index=True)

    # Address fields (only if available in your dataset)
    straatnaam = db.Column(db.String(255))
    plaatsnaam = db.Column(db.String(100), index=True)
    provincie = db.Column(db.String(100), index=True)

    # Optional enrichment fields (if present in CSV later)
    school_type = db.Column(db.String(100))

    # ---------------------------------------------------------
    # PostGIS geometry (WGS84)
    # ---------------------------------------------------------
    geometry = db.Column(
        Geometry(
            geometry_type='POINT',
            srid=4326
        ),
        index=True
    )

# ---------------------------------------------------------
# 7. Bestuurlijke Grenzen (Administrative Boundaries)
# ---------------------------------------------------------
class Grenzen(db.Model):
    __tablename__ = 'grenzen'

    ogc_fid = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(50))
    gemeentenaam = db.Column(db.String(255))
    layer_type = db.Column(db.String(50))
    geom = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 8. Water Authorities Hydrography (INSPIRE)
# ---------------------------------------------------------
class HydrographyWatercourse(db.Model):
    __tablename__ = 'hydrography_watercourse'

    id = db.Column(db.Integer, primary_key=True)
    gml_id      = db.Column(db.String(255))
    localid     = db.Column(db.String(255))
    name        = db.Column(db.String(255))
    localtype   = db.Column(db.String(100))
    streamorder = db.Column(db.String(50))
    length      = db.Column(db.Float)
    level       = db.Column(db.String(50))
    tidal       = db.Column(db.Boolean)
    origin      = db.Column(db.String(100))
    condition   = db.Column(db.String(100))
    geometry    = db.Column(Geometry(geometry_type='MULTILINESTRING', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# ML Result Tables
# ---------------------------------------------------------

class MLRiskScore(db.Model):
    __tablename__ = 'ml_risk_scores'

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, index=True)
    adres = db.Column(db.String(255))
    gemeente = db.Column(db.String(100))
    provincie = db.Column(db.String(100))
    risk_score = db.Column(db.Float)
    nh3_component = db.Column(db.Float)
    natura_component = db.Column(db.Float)
    pesticide_component = db.Column(db.Float)
    sensitivity_component = db.Column(db.Float)
    nh3_value = db.Column(db.Float)
    dist_natura_km = db.Column(db.Float)
    nearest_exceedance = db.Column(db.Float)
    schools_within_5km = db.Column(db.Integer)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)
    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))


class MLPesticideTrend(db.Model):
    __tablename__ = 'ml_pesticide_trends'

    id = db.Column(db.Integer, primary_key=True)
    station_code = db.Column(db.Integer, index=True)
    station_name = db.Column(db.String(255))
    trend = db.Column(db.String(20))   # 'increasing' | 'decreasing' | 'stable'
    p_value = db.Column(db.Float)
    tau = db.Column(db.Float)
    slope = db.Column(db.Float)        # Theil-Sen slope (exceedance per year)
    year_start = db.Column(db.Integer)
    year_end = db.Column(db.Integer)
    n_years = db.Column(db.Integer)
    mean_exceedance = db.Column(db.Float)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)
    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))


class MLFarmAnomaly(db.Model):
    __tablename__ = 'ml_farm_anomalies'

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, index=True)
    adres = db.Column(db.String(255))
    gemeente = db.Column(db.String(100))
    provincie = db.Column(db.String(100))
    anomaly_score = db.Column(db.Float)   # Isolation Forest: higher = more normal
    is_anomaly = db.Column(db.Boolean)
    nh3 = db.Column(db.Float)
    geur = db.Column(db.Float)
    fijnstof = db.Column(db.Float)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)
    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))