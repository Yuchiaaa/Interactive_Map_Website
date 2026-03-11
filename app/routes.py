# app/routes.py
import io
import requests
import pandas as pd
from flask import request, send_file, jsonify, render_template
from flask import current_app as app

@app.route('/')
def index():
    # Render the main mapping interface
    return render_template('index.html')

@app.route('/api/export_excel', methods=['POST'])
def export_excel():
    data = request.json
    layers = data.get('layers', [])

    if not layers:
        return jsonify({"error": "No layers provided for export."}), 400

    output = io.BytesIO()
    
    # Masquerade as a standard web browser to prevent PDOK from blocking the Python request (HTTP 403)
    headers = {
        'Accept': 'application/geo+json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        has_data = False
        
        for layer in layers:
            sheet_name = layer.get('sheet_name', 'Unknown')[:31] 
            url = layer.get('url')
            columns_mapping = layer.get('columns', {}) 

            print(f"\n--- Processing Export for: {sheet_name} ---")
            print(f"Target URL: {url}")

            try:
                # Fetch data with a 30-second timeout to handle large spatial queries
                response = requests.get(url, headers=headers, timeout=30)
                
                # If the API returns an error code (e.g., 400 or 403), this will intentionally trigger an exception
                response.raise_for_status() 
                
                features = response.json().get('features', [])
                print(f"Success: Retrieved {len(features)} features from PDOK.")
                
                if features:
                    records = [feat.get('properties', {}) for feat in features]
                    df = pd.DataFrame(records)
                    
                    if columns_mapping and not df.empty:
                        valid_cols = {k: v for k, v in columns_mapping.items() if k in df.columns}
                        df = df[list(valid_cols.keys())].rename(columns=valid_cols)
                    
                    df['Data Source'] = f"PDOK - {sheet_name}"
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    has_data = True
                else:
                    print(f"Warning: The API request was successful, but 0 features were found in this area.")

            except requests.exceptions.RequestException as e:
                # Catch network errors, timeouts, and HTTP status code errors
                print(f"❌ Network Error for {sheet_name}: {e}")
            except Exception as e:
                # Catch pandas processing or JSON parsing errors
                print(f"❌ Data Processing Error for {sheet_name}: {e}")

        if not has_data:
            pd.DataFrame({"Message": ["No data found in the selected area."]}).to_excel(writer, sheet_name="No Data", index=False)

    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="Comprehensive_Evidence_Data.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )