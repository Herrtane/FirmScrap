import requests
from bs4 import BeautifulSoup
import json
import time
import os
from urllib.parse import urljoin, urlparse

BASE_URL = "https://legacyfiles.us.dlink.com/"
RESULT_FILE = "dlink_legacy_firmware_links.json"
SAVE_INTERVAL = 10

visited_dirs = set()
results = []

if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        try:
            results = json.load(f)
        except json.JSONDecodeError:
            results = []

def save_results():
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    print(f"[*] Saved: {len(results)} links")

def is_directory_link(href):
    return href.endswith("/") and not href.startswith("/?")

def is_firmware_file(href, text):
    href = href.lower()
    text = text.lower()
    if "firmware" in href or "firmware" in text:
        return not href.endswith(".pdf")
    return False

def crawl_directory(url, vendor_path=""):
    time.sleep(0.5)
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"[-] Access failed: {url}")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        pre_tag = soup.find("pre")
        if not pre_tag:
            return

        for a in pre_tag.find_all("a", href=True):
            href = a['href']
            full_url = urljoin(url, href)
            if is_directory_link(href) and "[To Parent Directory]" not in a.text:
                if full_url not in visited_dirs:
                    visited_dirs.add(full_url)
                    sub_vendor_path = urlparse(full_url).path.strip("/")
                    crawl_directory(full_url, sub_vendor_path)
            elif is_firmware_file(href, a.text):
                record = {
                    "Model": vendor_path,
                    "Download": urljoin(url, href)
                }
                if record not in results:
                    results.append(record)
                    print(f"[+] Firmware found: {record['Download']}")
                    if len(results) % SAVE_INTERVAL == 0:
                        save_results()
    except Exception as e:
        print(f"[!] Exception: {url} → {e}")

crawl_directory(BASE_URL)

save_results()
print(f"\n[+] Done! {len(results)} links are saved.")