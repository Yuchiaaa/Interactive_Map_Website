from flask import render_template, jsonify
from flask import current_app as app

@app.route('/')
def index():
    # Render the main mapping interface
    return render_template('index.html')

@app.route('/api/proxy/pdok_example')
def pdok_proxy():
    # Placeholder for future WFS data processing
    data = {
        "status": "success",
        "message": "Backend is ready to process complex spatial queries."
    }
    return jsonify(data)