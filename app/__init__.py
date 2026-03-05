from flask import Flask

def create_app():
    # Initialize the core Flask application
    app = Flask(__name__, template_folder='../templates', static_folder='../static')

    # Import and register routes within the application context
    with app.app_context():
        from . import routes

    return app