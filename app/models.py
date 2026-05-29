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
    # Column names match the PDOK source files and what routes.py queries.
    # 'gewasnaam' in older GPKG files is aliased to 'gewas' by the ETL.
    gewas     = db.Column(db.String(150))
    gewascode = db.Column(db.String(50))
    # area_ha is not stored — it is computed on the fly from geometry in routes.py

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

    # Address fields
    straatnaam = db.Column(db.String(255))
    huisnummer_toevoeging = db.Column('huisnummer-toevoeging', db.String(50))
    postcode = db.Column(db.String(20))
    plaatsnaam = db.Column(db.String(100), index=True)
    provincie = db.Column(db.String(100), index=True)
    gemeentenummer = db.Column(db.String(20))
    gemeentenaam = db.Column(db.String(100))
    telefoonnummer = db.Column(db.String(50))

    # Optional enrichment fields (if present in CSV later)
    onderwijstype = db.Column(db.String(100))

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
# 9. Nature Network Netherlands / Natuurnetwerk Nederland (INSPIRE)
# WMS: https://service.pdok.nl/provincies/natuurnetwerk-nederland/wms/v1_0
# Layers: PS.ProtectedSite | PS.ProtectedSitesSpecialAreaOfConservation
# ---------------------------------------------------------
class NNNArea(db.Model):
    __tablename__ = 'nnn_areas'

    # Flexible schema — INSPIRE field names vary per province release.
    # Properties are read dynamically via row_to_json() in routes.py.
    id = db.Column(db.Integer, primary_key=True)
    geometry = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

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
# 9. WFD Surface Water Bodies (INSPIRE harmonised)
# ---------------------------------------------------------
class WFDSurfaceWaterBody(db.Model):
    __tablename__ = 'wfd_surface_water'

    id = db.Column(db.Integer, primary_key=True)
    # Mixed geometry: MultiLineString for rivers, MultiPolygon for lakes/coastal waters
    geometry = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# Waterschappen (Water Authority Borders)
# ---------------------------------------------------------
class Waterschappen(db.Model):
    __tablename__ = 'waterschappen'

    id   = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50))
    naam = db.Column(db.String(255))
    geom = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))
    
# ---------------------------------------------------------
# Kadastrale Kaart (Cadastral Parcels)
# Source: Kadaster / PDOK — BRK Kadastrale Kaart
# OGC API: https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1
# ---------------------------------------------------------
class KadastraalPerceel(db.Model):
    __tablename__ = 'kadastralekaart_perceel'

    id                = db.Column(db.Integer, primary_key=True)
    identificatie     = db.Column(db.String(100), index=True)
    gemeente_code     = db.Column(db.Integer, index=True)
    gemeente          = db.Column(db.String(100))
    sectie            = db.Column(db.String(10))
    perceelnummer     = db.Column(db.Integer)
    kadastralegrootte = db.Column(db.Float)
    soortgrootte      = db.Column(db.String(100))
    status            = db.Column(db.String(50))
    geometry          = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# KRD Stallen — individual animal housing units (one row per stal, not per farm)
#
# A single farm (krd_farms) can have many stallen. This table holds the
# per-unit NH3/odour/dust figures as permitted. Useful for fine-grained
# emission analysis and for the ML pipeline.
#
# Note: there is no animal type (bedrijfstype) column here — that information
# only exists at the farm level in krd_farms. The 'omschrijving' field contains
# a free-text description like "Stal 1" or "bedrijf".
#
# 'beendigd' stores the Dutch 'beëndigd' value (Ja/Nee). The original column
# name in the KRD CSV has an encoding quirk: the ë is Latin-1 \xeb and the 'i'
# in 'beëindigd' is dropped, so Python sees 'beëndigd'. We normalise to ASCII.
#
# Source: https://krd.igoview.nl/ → Stallen tab → Totaaloverzicht stallen
# ETL:    etl/load_stallen.py (load) | etl/truncate_stallen.py (reset)
# ---------------------------------------------------------
class KRDStall(db.Model):
    __tablename__ = 'krd_stallen'

    id            = db.Column(db.Integer, primary_key=True)
    provincie     = db.Column(db.String(100), index=True)
    bronhouder    = db.Column(db.String(100))
    vthobject_id  = db.Column(db.String(100), index=True)
    stal_id       = db.Column(db.String(100))
    omschrijving  = db.Column(db.String(255))
    beendigd      = db.Column(db.String(10))
    adres         = db.Column(db.String(255))
    gemeente      = db.Column(db.String(100))
    nh3_emissie   = db.Column(db.String(50))
    geur_emissie  = db.Column(db.String(50))
    fijnstof_emissie = db.Column(db.String(50))
    zaaknummer    = db.Column(db.String(100))
    besluitdatum  = db.Column(db.String(30))
    zaaktype      = db.Column(db.String(255))
    geometry = db.Column(Geometry(geometry_type='POINT', srid=4326, spatial_index=True))

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

