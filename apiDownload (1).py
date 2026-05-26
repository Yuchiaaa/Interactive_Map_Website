import requests
import os
import re
import mimetypes
from urllib.parse import urlparse

def get_dynamic_filename(response, url):
    """
    Extracts the filename and extension from the HTTP response headers or URL.
    """
    # 1. Try to get the original filename from the 'Content-Disposition' header
    content_disposition = response.headers.get('content-disposition')
    if content_disposition:
        # Use regex to find 'filename="example.ext"' pattern
        matches = re.findall(r'filename=["\']?([^"\';]+)["\']?', content_disposition)
        if matches:
            return matches[0]

    # 2. Try to extract the filename directly from the URL path
    parsed_url = urlparse(url)
    filename_from_url = os.path.basename(parsed_url.path)
    if filename_from_url and '.' in filename_from_url:
        return filename_from_url

    # 3. Fallback: Guess the extension using the 'Content-Type' header
    content_type = response.headers.get('content-type')
    if content_type:
        # Clean up content type (e.g., 'text/html; charset=utf-8' -> 'text/html')
        clean_content_type = content_type.split(';')[0].strip()
        extension = mimetypes.guess_extension(clean_content_type)
        if extension:
            return f"downloaded_file{extension}"

    # 4. Ultimate fallback if no information is available
    return "downloaded_file.bin"


def download_file_from_api(api_url, save_dir=".", custom_filename=None, headers=None):
    """
    Downloads a file of any type from an API and saves it.
    """
    try:
        # Send GET request with stream=True for memory efficiency
        response = requests.get(api_url, headers=headers, stream=True)
        response.raise_for_status()
        
        # Determine the final filename
        final_filename = custom_filename if custom_filename else get_dynamic_filename(response, api_url)
        
        # Construct the full absolute path
        save_path = os.path.join(save_dir, final_filename)
        
        # Create the target directory if it does not exist
        os.makedirs(save_dir, exist_ok=True)
        
        # Write chunks to the disk
        with open(save_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
                    
        print(f"Success: File saved as '{final_filename}' at {save_path}")
        return save_path
        
    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to download. Details: {e}")
        return None

# ==========================================
# Execution Section
# ==========================================
if __name__ == "__main__":
    
    # IMPORTANT: Replace this with the actual URL you want to download from
    target_api_url = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1"
    
    # Your specific Mac Downloads folder path
    mac_downloads_path = "your path to store"
    
    # Optional headers (e.g., if you need to pass an API key or Token)
    # If your API doesn't need this, you can set headers=None below
    api_headers = {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
    }

    print("Starting download to your Mac Downloads folder...")
    
    # Execute the download
    download_file_from_api(
        api_url=target_api_url, 
        save_dir=mac_downloads_path, 
        headers=api_headers
    )