# app/__init__.py
from flask import Flask
from .models import db
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv() 

def create_app():
    # Initialize the core Flask application
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # Configure PostgreSQL database connection
    # This will now successfully retrieve the URL from your .env file
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args': {'connect_timeout': 5}}

    # Bind the database instance to this specific Flask app
    db.init_app(app)

    # Import and register routes within the application context
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"Warning: DB unavailable at startup: {e}")
    
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app