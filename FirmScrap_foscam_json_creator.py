import json
import os
import time
import requests
from bs4 import BeautifulSoup
import os


BASE_URL = "https://www.foscam.com"
LIST_API = f"{BASE_URL}/downloads/firmwareajaxjson.html"
DETAIL_PAGE = f"{BASE_URL}/downloads/firmware_details.html?id="
OUTPUT_FILE = "foscam_firmware_links.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.foscam.com/downloads/index.html"
}

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

def get_model_list():
    models = []
    for page in range(1, 20):
        params = {
            "big_category": "",
            "count": 20,
            "pagename": "index",
            "q": "",
            "p": page
        }
        try:
            resp = requests.get(LIST_API, params=params, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            row = data.get("row")
            if not row:
                break
            for item in row:
                models.append({
                    "pid": item["pid"],
                    "Model": item["productname"]
                })
        except Exception as e:
            print(f"[!] Page {page} request failed: {e}")
            break
        time.sleep(1.5)
    return models

def extract_firmware_from_detail(pid):
    try:
        url = f"{DETAIL_PAGE}{pid}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        result = []

        model_tag = soup.select_one(".download_list_icon span")
        model = model_tag.text.strip() if model_tag else ""

        rows = soup.select(".down_table tr")[1:]  # skip header
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue
            version = cols[0].text.strip()
            release_note = cols[3].text.strip().lower()
            attention_note = cols[4].text.strip().lower()
            is_middle = "please upgrade to this version before upgrading" in release_note or \
                        "please upgrade to this version before upgrading" in attention_note
            download_tag = cols[5].find("a")
            if download_tag:
                link = download_tag.get("href", "")
                if link and "file.html" in link:
                    full_url = BASE_URL + link
                    result.append({
                        "Model": model,
                        "Version": version,
                        "Download": full_url,
                        "IsMiddle": is_middle
                    })
        return result
    except Exception as e:
        print(f"[!] Detail metadata extract error (pid: {pid}): {e}")
        return []


def main():
    results = load_json(OUTPUT_FILE)
    collected = {(r["Model"], r["Version"]) for r in results}

    models = get_model_list()
    print(f"[*] Total model number: {len(models)}")

    for idx, item in enumerate(models, 1):
        print(f"[{idx}/{len(models)}] {item['Model']} checking...")
        fw_list = extract_firmware_from_detail(item["pid"])
        new_items = [fw for fw in fw_list if (fw["Model"], fw["Version"]) not in collected]
        if new_items:
            results.extend(new_items)
            save_json(OUTPUT_FILE, results)
            print(f"[*] Saved: {len(new_items)} links")
        time.sleep(2.0)

    print(f"\n[+] Done! {len(results)} links are saved.")

if __name__ == "__main__":
    main()
