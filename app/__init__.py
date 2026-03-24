# app/__init__.py
from flask import Flask
# Import the database instance from our models
from .models import db

def create_app():
    # Initialize the core Flask application
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # Configure PostgreSQL database connection
    # Format: postgresql://username:password@host:port/database_name
    app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Bind the database instance to this specific Flask app
    db.init_app(app)

    # Import and register routes within the application context
    with app.app_context():
        # This is the magic line that reads models.py and creates the physical tables in Postgres
        db.create_all()
        # 找到 create_app() 函数的末尾，把旧的 import routes 删掉，换成这下面两行：
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app