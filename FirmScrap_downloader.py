import json
import requests
import os
import ftplib
import logging
import time
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(filename='download_errors.log', 
                    level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def load_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def is_pdf(url):
    file_name = os.path.basename(url)
    _, file_extension = os.path.splitext(file_name)
    return file_extension.lower() == '.pdf'

def download_file_ftp(url, output_dir, model=None, version=None):
    from ftplib import FTP
    from urllib.parse import urlparse
    import posixpath

    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    path = parsed_url.path
    file_name = os.path.basename(path)
    dir_path = posixpath.dirname(path)

    file_path = os.path.join(output_dir, file_name)

    try:
        with FTP(hostname, timeout=10) as ftp:
            ftp.set_pasv(True)
            ftp.login()
            
            ftp.cwd("/")
            for part in dir_path.strip("/").split("/"):
                if part:
                    ftp.cwd(part)
                    print(f" → cd {part}")

            with open(file_path, "wb") as file:
                ftp.retrbinary(f"RETR {file_name}", file.write)

            print(f"[+] FTP download success!: {file_path}")

    except Exception as e:
        print(f"[-] FTP download failed..: {url} - : {e}")
        logging.error(f"FTP download failed..: {url} - : {e}")

def sanitize_filename(name):
    return name.replace("/", "_").replace("\\", "_").replace("?", "_").replace("&", "_").replace("=", "_")

def download_file_http(url, output_dir, model=None, version=None):
    if model and version:
        safe_model = sanitize_filename(model)
        safe_version = sanitize_filename(version)
        file_name = f"{safe_model}_{safe_version}.zip"
    else:
        parsed = urlparse(url)
        file_name = os.path.basename(parsed.path)

    file_path = os.path.join(output_dir, file_name)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        #"Referer": "https://www.moxa.com/",
        "Referer": "https://support.dlink.com/",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        try:
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"[+] HTTP/HTTPS download success!: {file_path}")
        except Exception as e:
            error_message = f"[-] HTTP/HTTPS download failed..: {url} - : {e}"
            print(error_message)
    except requests.exceptions.RequestException as e:
        error_message = f"[-] HTTP/HTTPS download failed..: {url} - : {e}"
        print(error_message)
        logging.error(error_message)


def download_file(url, output_dir, model=None, version=None):

    parsed_url = urlparse(url)
    if parsed_url.scheme in ['http', 'https']:
        download_file_http(url, output_dir, model, version)
    elif parsed_url.scheme == 'ftp':
        download_file_ftp(url, output_dir, model, version)
    else:
        error_message = f"[!] Error: {url}"
        print(error_message)
        logging.error(error_message)

def wait_for_any_download(directory, timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        for file in os.listdir(directory):
            if not file.endswith('.crdownload'):
                return os.path.join(directory, file)
        time.sleep(1)
    return None

def clean_crdownload_files(directory):
    for file in os.listdir(directory):
        if file.endswith('.crdownload'):
            try:
                os.remove(os.path.join(directory, file))
            except Exception:
                pass

def download_with_selenium(url, output_dir):

    os.makedirs(output_dir, exist_ok=True)

    parsed_url = urlparse(url)
    if parsed_url.scheme == 'ftp':
        download_file_ftp(url, output_dir)
        return

    chrome_options = Options()
    prefs = {
        "download.default_directory": os.path.abspath(output_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.get(url)
        
        print(f"[*] Selenium attempting: {url}")

        #############################################
        time.sleep(30)
        #############################################

    except Exception as e:
        logging.error(f"[!] Selenium error: {url} - {e}")
        print(f"[!] Selenium error: {url} - {e}")
    finally:
        driver.quit()

def download_from_json(json_data):
    for item in json_data:
        download_url = item.get("Download") or item.get("ReleaseNotePDF")
        download_model = item.get("Model")
        download_version = item.get("Version")
        if download_url:
            output_dir = os.path.join('.', vendor_name)
            os.makedirs(output_dir, exist_ok=True)
            
            if select == '1':
                download_file(download_url, output_dir, download_model, download_version)
            elif select == '2':
                download_with_selenium(download_url, output_dir)


if __name__ == "__main__":
    input_file = input("Enter JSON file path: ").strip()
    vendor_name = input("Enter vendor name: ").strip()
    json_data = load_json(input_file)
    select = input("1. request 2. selenium: ")
    download_from_json(json_data)
