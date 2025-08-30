import os
import re
import json
import time
import random
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

START_URL = "https://www.tp-link.com/us/support/download/"
BASE_DL   = "https://www.tp-link.com/us/support/download/"
OUT_MODELS_JSON   = "tplink_models.json"
OUT_FIRMWARE_JSON = "tplink_firmware_links.json"
SAVE_EVERY = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tp-link.com/",
}

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

def extract_product_tree_blob(html: str) -> str:
    m = re.search(r"var\s+productTree\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        m = re.search(r"var\s+productTree\s*=\s*(\{.*\})\s*;", html, re.DOTALL)
    if not m:
        with open("debug_tplink_download.html", "w", encoding="utf-8") as f:
            f.write(html)
    return m.group(1)

def parse_models_and_slugs(blob: str):
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        cleaned = re.sub(r"/\*.*?\*/", "", blob, flags=re.DOTALL)
        cleaned = re.sub(r"//.*?$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        data = json.loads(cleaned)

    models = []
    slug_map = {}
    seen = set()

    for _, arr in (data or {}).items():
        if not isinstance(arr, list):
            continue
        for item in arr:
            name = (item or {}).get("model_name") or (item or {}).get("product_title")
            url = (item or {}).get("url")
            if not name or not url:
                continue
            if name in seen:
                continue
            seen.add(name)

            path = urlparse(url).path.strip("/")
            slug = path.split("/")[-1] if path else None
            if not slug:
                continue

            models.append(name)
            slug_map[name] = slug

    models.sort(key=lambda x: x.lower())
    return models, slug_map

def get_models_and_slugs(session: requests.Session):
    html = fetch_html(START_URL, session)
    blob = extract_product_tree_blob(html)
    models, slug_map = parse_models_and_slugs(blob)
    atomic_write_json(OUT_MODELS_JSON, models)
    print(f"[+] {len(models)} models are saved: {OUT_MODELS_JSON}")
    return models, slug_map

def build_firmware_page(slug: str) -> str:
    return f"{BASE_DL}{slug}/#Firmware"

def parse_firmware_tables(html: str, fallback_model_label: str):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for tbl in soup.select("table.download-resource-table"):
        name_p = tbl.select_one("tr.basic-info th.download-resource-name p")
        a_dl   = tbl.select_one("tr.basic-info th.download-resource-btnbox a[href]")
        pub_td = tbl.select("tr.detail-info td")

        if not name_p or not a_dl or not pub_td:
            continue

        name_text = name_p.get_text(" ", strip=True)
        model_text, version_text = name_text, None
        if "_" in name_text:
            idx = name_text.find("_")
            model_text = name_text[:idx].strip()
            version_text = name_text[idx+1:].strip()

        release_date = None
        for td in pub_td:
            txt = td.get_text(" ", strip=True)
            if txt.lower().startswith("published date"):
                m = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
                release_date = m.group(1) if m else None
                break

        download_url = a_dl.get("href", "").strip()
        if not download_url:
            continue

        results.append({
            "Vendor": "TP-Link",
            "Model": model_text or fallback_model_label,
            "Version": version_text,
            "Release_Date": release_date,
            "Download": download_url
        })
    return results

def build_omada_download_page(slug: str) -> str:
    return f"https://support.omadanetworks.com/us/product/{slug}/?resourceType=download"

def parse_omada_downloads(html: str, slug: str):
    from bs4 import BeautifulSoup
    import re

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    soup = BeautifulSoup(html, "html.parser")
    results = []

    slug_norm = _norm(slug)

    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "")
        if not re.search(r"\bdownload\b", text, flags=re.I):
            continue

        href = a["href"].strip()
        if not href:
            continue

        block = a
        for _ in range(5):
            if block.parent:
                block = block.parent
            if len(block.get_text(strip=True)) > 50:
                break

        block_text = block.get_text("\n", strip=True)

        if not re.search(r"\bFirmware\b", block_text, flags=re.I):
            continue

        lines = [ln for ln in block_text.splitlines() if ln.strip()]
        title = lines[0] if lines else ""

        title_norm = _norm(title)
        if slug_norm not in title_norm:
            continue

        release_date = None
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", block_text)
        if m:
            release_date = m.group(1)
        else:
            m = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", block_text)
            if m:
                mm, dd, yyyy = m.groups()
                release_date = f"{yyyy}-{mm}-{dd}"

        model_text = title
        version_text = None
        if "_" in title:
            idx = title.find("_")
            model_text = title[:idx].strip()
            version_text = title[idx+1:].strip()

        results.append({
            "Vendor": "TP-Link",
            "Model": model_text,
            "Version": version_text,
            "Release_Date": release_date,
            "Download": href
        })

    return results

def crawl_all_tplink_firmware():
    s = requests.Session()

    results = []
    seen = set()
    if os.path.exists(OUT_FIRMWARE_JSON):
        try:
            with open(OUT_FIRMWARE_JSON, "r", encoding="utf-8") as f:
                results = json.load(f)
            for r in results:
                seen.add((r.get("Model"), r.get("Download")))
            print(f"[!] Previous {len(results)} results are loaded")
        except Exception:
            results = []
            seen = set()

    models, slug_map = get_models_and_slugs(s)

    total = len(results)
    for i, model_name in enumerate(models, 1):
        slug = slug_map.get(model_name)
        if not slug:
            continue

        std_url = build_firmware_page(slug)
        added_now = 0
        try:
            html = fetch_html(std_url, s)
            fw_entries = parse_firmware_tables(html, model_name)
        except Exception as ex:
            print(f"[-] Error {model_name} ({std_url}): {ex}")
            fw_entries = []

        if not fw_entries:
            omada_url = build_omada_download_page(slug)
            try:
                omada_html = fetch_html(omada_url, s)
                fw_entries = parse_omada_downloads(omada_html, slug)
                if fw_entries:
                    print(f"[+] {len(fw_entries)} models found in Omada!: {model_name}")
            except Exception as ex:
                print(f"[-] Error {model_name} ({omada_url}): {ex}")

        for e in fw_entries:
            key = (e["Model"], e["Download"])
            if key in seen:
                continue
            results.append(e)
            seen.add(key)
            total += 1
            added_now += 1

            if total % SAVE_EVERY == 0:
                atomic_write_json(OUT_FIRMWARE_JSON, results)
                print(f"[*] checkpoint: {total} entries -> {OUT_FIRMWARE_JSON}")

        print(f"[{i}/{len(models)}] {model_name} -> +{added_now} firmware")
        time.sleep(random.uniform(0.25, 0.7))

    atomic_write_json(OUT_FIRMWARE_JSON, results)
    print(f"\n[+] Done! {len(results)} links are saved.")

if __name__ == "__main__":
    crawl_all_tplink_firmware()
