import os, time, random, json, re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

START_URL = "https://www.trendnet.com/support/"
BASE_URL  = "https://www.trendnet.com/support/"
MODELS_JSON = "trendnet_models.json"
FIRMWARE_JSON = "trendnet_firmware_links.json"
SAVE_EVERY = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.trendnet.com/support/",
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

def parse_models_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="subtype_id")
    if not select:
        form = soup.find("form", attrs={"name": "DownloadForm"})
        if form:
            select = form.find("select", attrs={"name": "subtype_id"}) or form.find("select")
    if not select:
        with open("debug_trendnet.html", "w", encoding="utf-8") as f:
            f.write(html)

    models = []
    for opt in select.find_all("option"):
        value = (opt.get("value") or "").strip()
        label = (opt.text or "").strip()
        if not value:
            continue
        full_url = urljoin(BASE_URL, value)
        prod = parse_qs(urlparse(full_url).query).get("prod", [""])[0]
        if not prod:
            continue
        models.append({"model": label, "prod": prod, "url": full_url})

    return list({m["prod"]: m for m in models}.values())

def get_models_live(start_url=START_URL):
    s = requests.Session()
    html = fetch_html(start_url, s)

    lowered = html.lower()
    if any(x in lowered for x in ["access denied", "verify you are human", "robot", "temporarily unavailable"]):
        with open("debug_trendnet.html", "w", encoding="utf-8") as f:
            f.write(html)

    models = parse_models_from_html(html)
    models.sort(key=lambda x: x["model"].lower())
    atomic_write_json(MODELS_JSON, models)
    print(f"[*] Total model number: {len(models)}")
    return models

def resolve_final_download_url(manager_url: str, session: requests.Session) -> str | None:
    try:
        r = session.get(manager_url, headers=HEADERS, timeout=30, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        exts = (".zip", ".bin", ".img", ".trx", ".tar", ".gz", ".bz2", ".7z")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            abs_url = urljoin(BASE_URL, href)
            if any(abs_url.lower().endswith(ext) for ext in exts):
                return abs_url
        return None
    except Exception:
        return None

def parse_firmware_minimal(html: str, page_url: str, session: requests.Session):
    soup = BeautifulSoup(html, "html.parser")

    prod = parse_qs(urlparse(page_url).query).get("prod", [""])[0]
    model_tok = prod.split("_", 1)[1] if "_" in prod else prod or "UNKNOWN"

    results = []
    for card in soup.find_all(class_="card"):
        head = card.find(["h2", "h3", "h4"])
        if not head:
            continue
        if "firmware" not in head.get_text(" ", strip=True).lower():
            continue

        text = card.get_text("\n", strip=True)

        version = None
        m = re.search(r"Firmware\s*Version\s*:\s*([0-9]+(?:\.[0-9]+){1,2})", text, re.I)
        if m:
            version = m.group(1)

        release_date = None
        m = re.search(r"Release\s*Date\s*:\s*([0-9]{1,2}/[0-9]{4})", text, re.I)
        if m:
            release_date = m.group(1)

        manager_url = None
        a_btn = card.find("a", attrs={"data-src": True})
        if a_btn and "inc_downloading.asp" in a_btn["data-src"]:
            manager_url = urljoin(BASE_URL, a_btn["data-src"])
        else:
            a_js = card.find("a", onclick=True)
            if a_js:
                oc = a_js.get("onclick") or a_js.get("onClick")
                if oc:
                    m2 = re.search(r"inc_downloading\.asp\?iFile=(\d+)", oc, re.I)
                    if m2:
                        manager_url = urljoin(BASE_URL, f"/asp/download_manager/inc_downloading.asp?iFile={m2.group(1)}")

        if not manager_url:
            continue

        final_url = resolve_final_download_url(manager_url, session) or manager_url

        results.append({
            "Vendor": "TRENDnet",
            "Model": model_tok,
            "Prod": prod,
            "Version": version,
            "Release": release_date,
            "Download": final_url
        })

    return results

def crawl_all_trendnet_firmware():
    s = requests.Session()
    models = get_models_live()

    all_fw = []
    if os.path.exists(FIRMWARE_JSON):
        try:
            with open(FIRMWARE_JSON, "r", encoding="utf-8") as f:
                all_fw = json.load(f)
                print(f"[!] Previous {len(all_fw)} results are loaded")
        except Exception:
            all_fw = []

    for i, m in enumerate(models, 1):
        try:
            html = fetch_html(m["url"], s)
            fw_list = parse_firmware_minimal(html, m["url"], s)
            if fw_list:
                all_fw.extend(fw_list)

                if len(all_fw) % SAVE_EVERY == 0:
                    atomic_write_json(FIRMWARE_JSON, all_fw)
                    print(f"[*] Saved: {len(all_fw)} entries -> {FIRMWARE_JSON}")

            print(f"[{i}/{len(models)}] {m['model']} -> firmware {len(fw_list)} entries")
            time.sleep(random.uniform(0.3, 0.9))
        except Exception as ex:
            print(f"[-] {m['model']} ({m['url']}): {ex}")

    atomic_write_json(FIRMWARE_JSON, all_fw)
    print(f"\n[+] Done! {len(all_fw)} links are saved.")

if __name__ == "__main__":
    crawl_all_trendnet_firmware()
