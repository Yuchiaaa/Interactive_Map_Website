# app/models.py
from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry

# Initialize the SQLAlchemy extension
db = SQLAlchemy()

# ---------------------------------------------------------
# 1. BRP Crop Parcels
# ---------------------------------------------------------
class BRPParcel(db.Model):
    __tablename__ = 'brp_parcels'

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True, nullable=False) 
    crop_code = db.Column(db.String(50))
    crop_name = db.Column(db.String(150))
    area_ha = db.Column(db.Float)
    
    # spatial_index=True ensures fast bounding box queries
    geom = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 2. Kadaster (Cadastral Parcels)
# ---------------------------------------------------------
class KadasterParcel(db.Model):
    __tablename__ = 'kadaster_parcels'

    id = db.Column(db.Integer, primary_key=True)
    municipality_code = db.Column(db.String(50), index=True)
    section = db.Column(db.String(10))
    parcel_number = db.Column(db.String(50), index=True)
    registered_area = db.Column(db.Float)
    
    geom = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 3. Natura 2000 (Protected Environmental Areas) - NEW
# ---------------------------------------------------------
class Natura2000Area(db.Model):
    __tablename__ = 'natura2000_areas'

    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(255))
    protection_type = db.Column(db.String(100))
    
    # Environmental zones are typically complex MultiPolygons
    geom = db.Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326, spatial_index=True))

# ---------------------------------------------------------
# 4. BAG (Addresses and Buildings) - NEW
# ---------------------------------------------------------
class BAGBuilding(db.Model):
    __tablename__ = 'bag_buildings'

    id = db.Column(db.Integer, primary_key=True)
    # The official Dutch building identification number (Pandidentificatie)
    building_id = db.Column(db.String(50), unique=True, index=True)
    construction_year = db.Column(db.Integer)
    status = db.Column(db.String(100))
    
    # Building footprints can be simple Polygons or complex MultiPolygons, 
    # so we use the generic GEOMETRY type to accommodate both safely.
    geom = db.Column(Geometry(geometry_type='GEOMETRY', srid=4326, spatial_index=True))