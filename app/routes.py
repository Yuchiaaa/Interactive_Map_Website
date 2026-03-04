from flask import render_template, jsonify
from flask import current_app as app
import requests

@app.route('/')
def index():
    # Render the main mapping interface
    return render_template('index.html')

@app.route('/api/proxy/pdok_example')
def pdok_proxy():
    # Example of a backend proxy route. 
    # Useful if you run into CORS issues with certain external APIs or 
    # need to process/filter geospatial data before sending it to the frontend.
    
    # This is a placeholder for future WFS (Web Feature Service) data processing
    data = {
        "status": "success",
        "message": "Backend is ready to process complex spatial queries."
    }
    return jsonify(data)