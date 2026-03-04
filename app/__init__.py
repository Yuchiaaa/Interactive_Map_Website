# Entry point for the Flask application
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Run the application in debug mode for development
    app.run(debug=True, port=5000)