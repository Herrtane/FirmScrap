import asyncio
import aiohttp
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
CONCURRENT_REQUESTS = 20
SAVE_INTERVAL = 5
RESULT_FILE = "moxa_firmware_links.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moxa.com"
}

results = []
retry_psids = []
sem = asyncio.Semaphore(CONCURRENT_REQUESTS)

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

async def fetch_and_parse(session, psid):
    url = BASE_URL.format(psid)
    async with sem:
        try:
            async with session.get(url, headers=HEADERS, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")
                    found_firmware = False
                    for table in soup.find_all("table"):
                        for row in table.find_all("tr")[1:]:
                            cols = row.find_all("td")
                            if len(cols) >= 2 and "firmware" in cols[1].text.strip().lower():
                                a_tag = cols[0].find("a", href=True)
                                if a_tag:
                                    results.append({
                                        "Vendor": f"psid={psid}",
                                        "Download": urljoin("https://www.moxa.com", a_tag['href'])
                                    })
                                    found_firmware = True
                                    if len(results) % SAVE_INTERVAL == 0:
                                        save_results()
                    if found_firmware:
                        print(f"[aiohttp] psid={psid} firmware found!")
                    else:
                        retry_psids.append(psid)
                        print(f"[retry] psid={psid} firmware not found.. Scheduled to be attemped Selenium")
                else:
                    retry_psids.append(psid)
                    print(f"[retry] psid={psid} response code: {response.status}")
        except Exception as e:
            retry_psids.append(psid)
            print(f"[retry] psid={psid} request failed: {e}")

def selenium_retry(psid_list):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1920,1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    for psid in psid_list:
        if any(f"psid={psid}" in r["Vendor"] for r in results):
            print(f"[SKIP] selenium psid={psid} already processed")
            continue

        url = BASE_URL.format(psid)
        try:
            driver.get(url)
            time.sleep(3)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            found_firmware = False
            for table in soup.find_all("table"):
                for row in table.find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) >= 2 and "firmware" in cols[1].text.strip().lower():
                        a_tag = cols[0].find("a", href=True)
                        if a_tag:
                            results.append({
                                "Vendor": f"psid={psid}",
                                "Download": urljoin("https://www.moxa.com", a_tag['href'])
                            })
                            found_firmware = True
                            if len(results) % SAVE_INTERVAL == 0:
                                save_results()
            if found_firmware:
                print(f"[selenium] psid={psid} firmware found!")
            else:
                print(f"[-] selenium failed: psid={psid} firmware not found..")
        except Exception as e:
            print(f"[!] selenium error: psid={psid} → {e}")
    driver.quit()

async def main():
    psid_list = extract_psids_from_html_file(HTML_FILE)
    print(f"[+] Total {len(psid_list)} psid are extracted")

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_and_parse(session, psid) for psid in psid_list]
        await asyncio.gather(*tasks)

    if retry_psids:
        print(f"\n[*] Selenium reattempt target: {len(retry_psids)}개\n")
        selenium_retry(retry_psids)

    save_results()
    print(f"\n[+] Done! {len(results)} links are saved.")

if __name__ == "__main__":
    asyncio.run(main())
