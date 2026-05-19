# app/models.py
from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry

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