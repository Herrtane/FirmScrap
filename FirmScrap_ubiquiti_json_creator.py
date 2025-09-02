import asyncio, aiohttp, json, os, re, sys, tempfile
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

BASE = "https://download.svc.ui.com/v1"
DOWNLOADS_TMPL = BASE + "/downloads?page={page}"
SLUG_API_TMPL  = BASE + "/downloads/products/slugs/{slug}"

OUT_SLUGS = "ubiquiti_all_slugs.json"
OUT_FW    = "ubiquiti_firmware_links.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UbiquitiCrawler/1.0)",
    "Accept": "application/json",
    "Origin": "https://ui.com",
    "Referer": "https://ui.com/",
}

VENDOR = "Ubiquiti"

FIRMWARE_EXT_RE = re.compile(r"\.(bin|img|tar|tar\.gz|tgz|trx|chk|signed|sigbin)$", re.I)

def save_json(path: str, data: Any):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise

def load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def normalize_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("+", "-plus")
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s

async def _http_get_json(session: aiohttp.ClientSession, url: str, *, method="GET", json_body=None, max_retry=5):
    backoff = 1.5
    for attempt in range(1, max_retry + 1):
        try:
            if method == "GET":
                async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status in (204, 404):
                        return None
                    if r.status >= 500 or r.status == 429:
                        await asyncio.sleep(min(10, backoff ** attempt))
                        continue
                    r.raise_for_status()
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if "json" in ct:
                        return await r.json(content_type=None)
                    txt = await r.text()
                    try:
                        return json.loads(txt)
                    except:
                        return None
            else:
                async with session.post(url, headers=HEADERS, json=json_body, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status in (204, 404):
                        return None
                    if r.status >= 500 or r.status == 429:
                        await asyncio.sleep(min(10, backoff ** attempt))
                        continue
                    r.raise_for_status()
                    ct = (r.headers.get("Content-Type") or "").lower()
                    if "json" in ct:
                        return await r.json(content_type=None)
                    txt = await r.text()
                    try:
                        return json.loads(txt)
                    except:
                        return None
        except Exception:
            await asyncio.sleep(min(10, backoff ** attempt))
    return None

def _extract_slugs_from_payload(payload: Any) -> Set[str]:
    out: Set[str] = set()
    def walk(x: Any):
        if isinstance(x, dict):
            if "products" in x and isinstance(x["products"], list):
                for p in x["products"]:
                    if isinstance(p, dict):
                        s = normalize_slug(p.get("slug", "") or p.get("name", ""))
                        if re.fullmatch(r"[a-z0-9-]{2,}", s):
                            out.add(s)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(payload)
    return out

def _pick_file_url(d: Dict[str, Any]) -> Optional[str]:
    for k in ("file_url", "filePath", "file_path", "path_name"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def _is_firmware_url(url: str) -> bool:
    try:
        u = urlparse(url)
        host = (u.netloc or "").lower()
        path = (u.path or "").lower()
        fname = os.path.basename(u.path or "")
    except Exception:
        return False

    if FIRMWARE_EXT_RE.search(fname):
        if ("fw-download.ubnt.com" in host and "/data/" in path) or \
           ("/unifi/firmware/" in path) or \
           ("/firmwares/" in path):
            return True
    return False

def _is_firmware_entry(d: Dict[str, Any]) -> bool:
    cat = d.get("category") or {}
    if isinstance(cat, dict):
        if (cat.get("slug") or "").lower() == "firmware":
            return True
    url = _pick_file_url(d) or ""
    return _is_firmware_url(url)

async def get_all_models(session: aiohttp.ClientSession) -> List[str]:
    page = 1
    all_slugs: Set[str] = set()
    while True:
        url = DOWNLOADS_TMPL.format(page=page)
        data = await _http_get_json(session, url)
        if not data or not isinstance(data, dict):
            break
        downloads = data.get("downloads")
        if not downloads or not isinstance(downloads, list):
            break
        new_slugs = _extract_slugs_from_payload(data)
        before = len(all_slugs)
        all_slugs |= new_slugs
        save_json(OUT_SLUGS, sorted(all_slugs))
        print(f"[*] Slug page {page}: +{len(all_slugs) - before} (total {len(all_slugs)})")
        page += 1
        if len(downloads) == 0:
            break
        if page > 2000:
            print("[!] page > 2000, stopping.")
            break
    slugs = sorted(all_slugs)
    print(f"[+] Slug harvested {len(slugs)} unique slugs -> {OUT_SLUGS}")
    return slugs

async def fetch_firmware_list(session: aiohttp.ClientSession, model: str) -> List[Dict[str, Any]]:
    url = SLUG_API_TMPL.format(slug=model)
    resp = await _http_get_json(session, url)
    items = []
    if isinstance(resp, list):
        items = resp
    elif isinstance(resp, dict):
        for key in ("downloads", "data", "items", "results"):
            v = resp.get(key)
            if isinstance(v, list):
                items = v
                break
        if not items:
            items = [resp]
    out = []
    for d in items:
        if not isinstance(d, dict):
            continue
        if not _is_firmware_entry(d):
            continue
        dl = _pick_file_url(d)
        if not dl:
            continue
        out.append({
            "Vendor": VENDOR,
            "Model": model,
            "Version": d.get("version"),
            "Release": d.get("date_published"),
            "Download": dl,
        })
    out.sort(key=lambda x: (x.get("Release") or "", x.get("Version") or ""), reverse=True)
    return out

async def _amain(mode: str = "all"):
    records: List[Dict[str, Any]] = []
    old = load_json(OUT_FW)
    if isinstance(old, list):
        records = old
    seen = {(r.get("Model"), r.get("Version"), r.get("Download")) for r in records}
    async with aiohttp.ClientSession() as session:
        if mode in ("slugs", "all"):
            slugs = await get_all_models(session)
        else:
            if not os.path.exists(OUT_SLUGS):
                print(f"[-] No exists {OUT_SLUGS}!")
                return
            slugs = [normalize_slug(s) for s in load_json(OUT_SLUGS) or []]
        if mode in ("fw", "all"):
            print(f"[*] Total model number: {len(slugs)}")
            sem = asyncio.Semaphore(8)
            async def task(model: str):
                async with sem:
                    try:
                        return model, await fetch_firmware_list(session, model)
                    except Exception:
                        return model, []
            tasks = [task(s) for s in slugs]
            base = len(records)
            done = 0
            for coro in asyncio.as_completed(tasks):
                model, items = await coro
                added = 0
                for r in items:
                    key = (r["Model"], r["Version"], r["Download"])
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append(r)
                    added += 1
                    if (len(records) - base) % 10 == 0:
                        save_json(OUT_FW, records)
                        print(f"[*] +{len(records) - base} firmware saved -> {OUT_FW}")
                done += 1
                if added:
                    print(f"[+] {model}: +{added} firmware")
            save_json(OUT_FW, records)
            print(f"\n[+] Done! {len(records)} links are saved -> {OUT_FW}")

def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    asyncio.run(_amain(mode))

if __name__ == "__main__":
    main()
