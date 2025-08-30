import time
import json
import random
import os
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def get_all_models(driver):
    driver.get("https://support.dlink.com/AllPro.aspx")
    time.sleep(3)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    models = set(a["alt"].strip() for a in soup.select("a.aRedirect[alt]"))
    return sorted(models)

def get_rev_values(driver, model):
    url = f"https://support.dlink.com/ProductInfo.aspx?m={model}"
    driver.get(url)
    time.sleep(2)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    select_tag = soup.find("select", {"id": "ddlHardWare"})
    if not select_tag:
        return []
    return [opt["value"] for opt in select_tag.find_all("option") if opt.get("value") and "please select" not in opt.text.lower()]

def fetch_firmware_list(model, rev):
    timestamp = str(int(time.time() * 1000))
    url = f"https://support.dlink.com/ajax/ajax.ashx?d={timestamp}&action=productfile&lang=en-US&ver={rev}&ac_id=1"
    headers = {
        "Referer": f"https://support.dlink.com/ProductInfo.aspx?m={model}",
        "User-Agent": random.choice(USER_AGENTS),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }

    for attempt in range(3): # Retry 3 times
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            links = []
            for item in result.get("item", []):
                for file in item.get("file", []):
                    if file.get("filetypename", "").lower() == "firmware":
                        fw_url = file.get("url", "")
                        if fw_url.lower().endswith((".zip", ".bin", ".img", ".tar", ".gz")):
                            links.append({
                                "Model": model,
                                "Rev": rev,
                                "Version": file.get("name", ""),
                                "Download": fw_url,
                                "Date": file.get("date", ""),
                                "Note": file.get("Note", "")
                            })
            return links
        except Exception as e:
            print(f"[-] {model} Rev {rev} request failed ({attempt+1}/3): {e}")
            time.sleep(random.uniform(3, 6))
    return []

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def main():
    driver = setup_driver()
    output_path = "dlink_current_firmware_links.json"
    results = load_json(output_path)
    processed = set((r["Model"], r["Rev"]) for r in results)

    try:
        models = get_all_models(driver)
        print(f"[*] Total model number: {len(models)}")

        for idx, model in enumerate(models, 1):
            print(f"\n[{idx}/{len(models)}] Model: {model}")
            revs = get_rev_values(driver, model)
            if not revs:
                print("[-] - Rev no exist. Skipped")
                continue

            for rev in revs:
                if (model, rev) in processed:
                    continue

                fw_list = fetch_firmware_list(model, rev)
                if not fw_list:
                    print(f"[-] Rev {rev} can't be found")
                else:
                    for fw in fw_list:
                        print(f"[+] {fw['Download']}")
                        results.append(fw)

                processed.add((model, rev))
                save_json(output_path, results)
                time.sleep(random.uniform(2.0, 4.0))

            time.sleep(random.uniform(5.0, 8.0))

        print(f"\n[+] Done! {len(results)} links are saved.")

    finally:
        driver.quit()
        save_json(output_path, results)
        print(f"[+] Done! {output_path}")

if __name__ == "__main__":
    main()
