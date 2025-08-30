from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin
import json
import time
import os

HTML_FILE = "moxa_psid.html"
BASE_URL = "https://www.moxa.com/en/support/product-support/software-and-documentation/search?psid={}"
RESULT_FILE = "moxa_release_notes_only.json"
SAVE_INTERVAL = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moxa.com"
}

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

def extract_psids_from_html_file(html_file_path):
    with open(html_file_path, "r", encoding="utf-8") as file:
        html_content = file.read()
    soup = BeautifulSoup(html_content, "html.parser")
    psid_set = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "psid=" in href:
            try:
                psid = int(href.split("psid=")[1].split("&")[0])
                psid_set.add(psid)
            except ValueError:
                continue
    return sorted(psid_set)

def selenium_release_note_scraper(psid_list):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1920,1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    for psid in psid_list:
        if any(f"psid={psid}" in r["Vendor"] for r in results):
            continue

        url = BASE_URL.format(psid)
        try:
            driver.get(url)
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            found = False

            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                if "release note" in text and href.lower().endswith(".pdf") and "firmware" in href.lower():
                    full_url = urljoin("https://www.moxa.com", href)
                    results.append({
                        "Vendor": f"psid={psid}",
                        "ReleaseNotePDF": full_url
                    })
                    found = True
                    print(f"[+] psid={psid} Release Note collected!")
                    if len(results) % SAVE_INTERVAL == 0:
                        save_results()

            if not found:
                print(f"[-] psid={psid} Release Note not found..")

        except Exception as e:
            print(f"[!] psid={psid} error: {e}")

    driver.quit()
    save_results()

def main():
    psid_list = extract_psids_from_html_file(HTML_FILE)
    selenium_release_note_scraper(psid_list)
    print(f"\n[+] Done! {len(results)} Release Notes are saved.")

if __name__ == "__main__":
    main()
