import os
import re
import json
import time
import random
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString

ROOT = "https://download.trendnet.com/"
SAVE_PATH = "trendnet_legacy_firmware_links.json"
SAVE_EVERY = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.trendnet.com/",
}

FIRMWARE_EXTS = (".zip", ".bin", ".img", ".trx", ".tar", ".gz", ".bz2", ".7z")

def atomic_write_json(path: str, data) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def fetch_html(url: str, session: requests.Session) -> str:
    r = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    print(f"[DEBUG] GET {url} -> {r.status_code} / final={r.url} / len={len(r.text)}")
    r.raise_for_status()
    return r.text

def list_model_dirs(session: requests.Session):
    html = fetch_html(ROOT, session)
    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre")
    if not pre:
        return []

    models = []
    for a in pre.find_all("a", href=True):
        name = a.get_text(strip=True)
        href = a["href"]
        if not href.endswith("/") or "[To Parent Directory]" in name:
            continue
        model = href.strip("/").split("/")[0]
        if model:
            models.append(model)
    return sorted(set(models))

def parse_release_date(text_block: str) -> str | None:
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+\d{1,2}:\d{2}\s+[AP]M", text_block)
    if not m:
        return None
    raw = m.group(1)
    try:
        dt = datetime.strptime(raw, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return raw

def list_firmware_files_for_model(model: str, session: requests.Session):
    fw_url = urljoin(ROOT, f"{model}/Firmware/")
    try:
        html = fetch_html(fw_url, session)
    except Exception as e:
        print(f"[-] Firmware dir not available for {model}: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre")
    if not pre:
        return []

    entries = []
    for a in pre.find_all("a", href=True):
        name = a.get_text(strip=True)
        href = a["href"]
        if "[To Parent Directory]" in name or href.endswith("/"):
            continue

        abs_url = urljoin(ROOT, href)
        if not any(abs_url.lower().endswith(ext) for ext in FIRMWARE_EXTS):
            continue

        prev_txt = ""
        prev = a.previous_sibling
        if isinstance(prev, NavigableString):
            prev_txt = str(prev)
        release_date = parse_release_date(prev_txt)

        entries.append({
            "Model": model,
            "Download": abs_url,
            "Release_date": release_date
        })
    return entries

def main():
    session = requests.Session()

    results = []
    seen = set()
    if os.path.exists(SAVE_PATH):
        try:
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                results = json.load(f)
            for r in results:
                seen.add((r.get("Model"), r.get("Download")))
            print(f"[!] loaded existing {len(results)} entries")
        except Exception:
            results = []
            seen = set()

    models = list_model_dirs(session)
    print(f"[+] discovered {len(models)} top-level dirs (model candidates)")

    total = 0
    for i, model in enumerate(models, 1):
        try:
            fw_files = list_firmware_files_for_model(model, session)
            added_now = 0
            for e in fw_files:
                key = (e["Model"], e["Download"])
                if key in seen:
                    continue
                results.append({
                    "Vendor": "TRENDnet",
                    "Model": e["Model"],
                    "Download": e["Download"],
                    "Release_date": e["Release_date"]
                })
                seen.add(key)
                total += 1
                added_now += 1

                if total % SAVE_EVERY == 0:
                    atomic_write_json(SAVE_PATH, results)
                    print(f"[*] Checkpoint: {total} entries -> {SAVE_PATH}")

            print(f"[{i}/{len(models)}] {model}: +{added_now} firmware files")
            time.sleep(random.uniform(0.2, 0.6))
        except Exception as ex:
            print(f"[-] {model}: {ex}")

    atomic_write_json(SAVE_PATH, results)
    print(f"\n[+] Done! {len(results)} links are saved.")

if __name__ == "__main__":
    main()
