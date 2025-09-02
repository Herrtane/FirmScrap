import asyncio, aiohttp, json, os, re, sys, tempfile, time, random, html
from typing import Any, Dict, List, Set, Tuple

BASE = "https://www.zyxel.com"
API_AUTOCOMPLETE = BASE + "/global/en/search_api_autocomplete/product_list_by_model?display=block_1&&field=model_machine_name&filter=model&q={q}"
PAGE_DOWNLOAD = BASE + "/global/en/support/download?model={model}"

OUT_MODELS = "zyxel_all_models.json"
OUT_FW = "zyxel_firmware_links.json"
VENDOR = "Zyxel"

MIN_Q = 3
MAX_CONC_SEEDS = 10
MAX_CONC_FW = 8
SAVE_MODELS_EVERY = 200
SAVE_FW_EVERY = 10
MIN_HTML = 4000

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

FW_EXT_RE = re.compile(r"\.(zip|bin|img|chk|trx|tar|tar\.gz|tgz)$", re.I)

def save_json(path: str, data: Any, retries=8):
    d = os.path.dirname(os.path.abspath(path)) or "."
    delay = 0.05
    for _ in range(retries):
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                try: os.remove(tmp)
                except Exception: pass
                time.sleep(delay + random.uniform(0, 0.05))
                delay = min(delay * 2, 1.0)
        except Exception:
            try: os.remove(tmp)
            except Exception: pass
            raise
    raise PermissionError("save_json failed")

def load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def clean_html_label(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

async def http_get_json(session: aiohttp.ClientSession, url: str, max_retry=4):
    backoff = 1.6
    for attempt in range(1, max_retry+1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status in (204,404): return []
                if r.status >= 500 or r.status == 429:
                    await asyncio.sleep(min(6, backoff**attempt)); continue
                r.raise_for_status()
                return await r.json(content_type=None)
        except Exception:
            await asyncio.sleep(min(6, backoff**attempt))
    return []

async def http_get_text(session: aiohttp.ClientSession, url: str, max_retry=4) -> str:
    backoff = 1.6
    for attempt in range(1, max_retry+1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status in (204,404): return ""
                if r.status >= 500 or r.status == 429:
                    await asyncio.sleep(min(8, backoff**attempt)); continue
                r.raise_for_status()
                txt = await r.text(errors="ignore")
                return txt or ""
        except Exception:
            await asyncio.sleep(min(8, backoff**attempt))
    return ""

async def query_seed(session: aiohttp.ClientSession, q: str) -> List[Dict[str,str]]:
    if len(q) < MIN_Q:
        return []
    url = API_AUTOCOMPLETE.format(q=q)
    arr = await http_get_json(session, url)
    out = []
    for it in arr if isinstance(arr, list) else []:
        v = (it.get("value") or "").strip()
        if not v: continue
        lbl = clean_html_label(it.get("label") or "")
        out.append({"Vendor": VENDOR, "Model": v, "Label": lbl})
    return out

async def scan_models(seeds: List[str]) -> List[Dict[str,str]]:
    headers = {"Accept":"application/json","User-Agent":"Mozilla/5.0"}
    seen: Set[str] = set()
    rows: List[Dict[str,str]] = load_json(OUT_MODELS)
    if isinstance(rows, list):
        for r in rows:
            v = (r.get("Model") or "").strip()
            if v: seen.add(v.lower())
    total_seeds = len(seeds)
    print(f"[*] Total seeds: {total_seeds}")
    base = len(rows)
    sem = asyncio.Semaphore(MAX_CONC_SEEDS)
    async with aiohttp.ClientSession(headers=headers) as session:
        async def run_seed(idx: int, seed: str):
            q = seed.lower().strip()
            if len(q) < MIN_Q:
                return 0
            print(f"[*] [{idx}/{total_seeds}] seed '{seed}': scanning")
            async with sem:
                items = await query_seed(session, q)
            add = 0
            for it in items:
                key = (it["Model"] or "").lower()
                if key in seen: continue
                seen.add(key)
                rows.append(it)
                add += 1
                if len(rows) % SAVE_MODELS_EVERY == 0:
                    save_json(OUT_MODELS, rows)
                    print(f"[*] saved {len(rows)} models -> {OUT_MODELS}")
            print(f"[+] seed '{seed}': +{add} (cumulative {len(rows)})")
            return add
        for i, seed in enumerate(seeds, 1):
            await run_seed(i, seed)
            if i % 5 == 0:
                save_json(OUT_MODELS, rows)
                print(f"[*] checkpoint: processed {i}/{total_seeds}, total {len(rows)} -> {OUT_MODELS}")
    if len(rows) > base:
        save_json(OUT_MODELS, rows)
        print(f"[+] Done! {len(rows)} models saved -> {OUT_MODELS}")
    else:
        print(f"[*] No new models, total {len(rows)} -> {OUT_MODELS}")
    rows.sort(key=lambda x: (x.get("Model","").lower(), x.get("Label","").lower()))
    return rows

def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s

def _find_all_rows(html: str) -> List[str]:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I|re.S)
    return rows or []

def _text_in_cell(row_html: str, cls_fragment: str) -> str:
    pat = rf'class="[^"]*{re.escape(cls_fragment)}[^"]*"(?:[^>]*)>(.*?)</td>'
    m = re.search(pat, row_html, flags=re.I|re.S)
    if not m: return ""
    t = re.sub(r"<[^>]+>", " ", m.group(1), flags=re.S)
    return _clean(t)

def _find_modal_id_in_row(row_html: str, kind: str) -> str:
    if kind == "firmware":
        m = re.search(r'data-target="#(download-firmware-[A-Za-z0-9_-]+)"', row_html, flags=re.I)
        return m.group(1) if m else ""
    if kind == "releasenote":
        m = re.search(r'data-target="#(release-note-[A-Za-z0-9_-]+)"', row_html, flags=re.I)
        return m.group(1) if m else ""
    if kind == "checksum":
        m = re.search(r'data-target="#(checksum-modal[A-Za-z0-9]+)"', row_html, flags=re.I)
        return m.group(1) if m else ""
    return ""

def _find_href_for_modal(html_scope: str, modal_id: str) -> str:
    if not modal_id: return ""
    pat = rf'id="{re.escape(modal_id)}"[^>]*>(.*?)</div>\s*</div>\s*</div>'
    m = re.search(pat, html_scope, flags=re.I|re.S)
    if not m:
        return ""
    block = m.group(1)
    m2 = re.search(r'href="([^"]+)"', block, flags=re.I)
    return m2.group(1).strip() if m2 else ""

def _extract_checksums(row_html: str, modal_id: str) -> Tuple[str,str]:
    if not modal_id: return "",""
    pat = rf'id="{re.escape(modal_id)}"[^>]*>(.*?)</div>\s*</div>\s*</div>'
    m = re.search(pat, row_html, flags=re.I|re.S)
    if not m: return "",""
    block = m.group(1)
    md5 = ""
    sha256 = ""
    m1 = re.search(r'MD5:\s*([A-F0-9]{32})', block, flags=re.I)
    if m1: md5 = m1.group(1).upper()
    m2 = re.search(r'SHA-256:\s*([A-F0-9]{64})', block, flags=re.I)
    if m2: sha256 = m2.group(1).upper()
    return md5, sha256

def _is_firmware_link(url: str) -> bool:
    if not url: return False
    if "download.zyxel.com" not in url: return False
    if "/firmware/" not in url.lower(): return False
    if FW_EXT_RE.search(url) is None: return False
    return True

def extract_firmware_from_html(html: str, model: str) -> List[Dict[str, Any]]:
    out = []
    if not html or len(html) < MIN_HTML: return out
    rows = _find_all_rows(html)
    for row in rows:
        typ = _text_in_cell(row, "views-field-nothing-2")
        if typ.lower() != "firmware":
            continue
        version = _text_in_cell(row, "views-field-field-version")
        lang = _text_in_cell(row, "views-field-field-language")
        rel  = _text_in_cell(row, "views-field-field-release-date")
        fw_modal = _find_modal_id_in_row(row, "firmware")
        rn_modal = _find_modal_id_in_row(row, "releasenote")
        cs_modal = _find_modal_id_in_row(row, "checksum")
        fw_url = ""
        rn_url = ""
        if fw_modal:
            fw_url = _find_href_for_modal(row, fw_modal)
            if not fw_url:
                fw_url = _find_href_for_modal(html, fw_modal)
        if rn_modal:
            rn_url = _find_href_for_modal(row, rn_modal)
            if not rn_url:
                rn_url = _find_href_for_modal(html, rn_modal)
        md5, sha256 = _extract_checksums(row, cs_modal) if cs_modal else ("","")
        if fw_url and _is_firmware_link(fw_url):
            out.append({
                "Vendor": VENDOR,
                "Model": model.upper(),
                "Version": _clean(version),
                "Release": _clean(rel),
                "Download": fw_url,
                "ReleaseNotes": rn_url,
                "Type": "Firmware"
            })
    return out

async def fetch_firmware_for_model(session: aiohttp.ClientSession, model: str, idx: int, total: int) -> Tuple[str, List[Dict[str, Any]]]:
    url = PAGE_DOWNLOAD.format(model=model)
    print(f"[*] [{idx}/{total}] {model}: fetching product page")
    html = await http_get_text(session, url)
    if not html:
        print(f"[-] [{idx}/{total}] {model}: product page fetch failed")
        return model, []
    items = extract_firmware_from_html(html, model)
    if not items:
        print(f"[-] [{idx}/{total}] {model}: no firmware found")
    else:
        print(f"[+] [{idx}/{total}] {model}: {len(items)} firmware entries")
    return model, items

async def harvest_firmware(models: List[Dict[str,str]]):
    targets = []
    for m in models:
        if not isinstance(m, dict): continue
        v = (m.get("Model") or "").strip()
        if not v: continue
        targets.append(v)
    targets = sorted(set(targets), key=lambda x: x.lower())
    total = len(targets)
    print(f"[*] Total models: {total}")
    records: List[Dict[str, Any]] = []
    old = load_json(OUT_FW)
    if isinstance(old, list): records = old
    seen = {(r.get("Model",""), r.get("Download","")) for r in records}
    headers = {"User-Agent": random.choice(UA), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    sem = asyncio.Semaphore(MAX_CONC_FW)
    async with aiohttp.ClientSession(headers=headers) as session:
        async def task(i: int, model: str):
            async with sem:
                try:
                    return await fetch_firmware_for_model(session, model, i, total)
                except Exception:
                    print(f"[-] [{i}/{total}] {model}: exception")
                    return model, []
        coros = [task(i+1, m) for i, m in enumerate(targets)]
        base = len(records); done = 0
        for fut in asyncio.as_completed(coros):
            model, items = await fut
            added = 0
            for r in items:
                key = (r.get("Model",""), r.get("Download",""))
                if key in seen: continue
                seen.add(key)
                records.append(r)
                added += 1
                if (len(records) - base) % SAVE_FW_EVERY == 0:
                    try:
                        save_json(OUT_FW, records)
                        print(f"[*] progress: +{len(records)-base} saved -> {OUT_FW}")
                    except PermissionError:
                        time.sleep(0.2)
                        save_json(OUT_FW, records)
                        print(f"[*] progress(retry): +{len(records)-base} saved -> {OUT_FW}")
            done += 1
            if added:
                print(f"[+] {model}: +{added} (processed {done}/{total})")
            else:
                print(f"[*] {model}: +0 (processed {done}/{total})")
            if done % 25 == 0:
                try:
                    save_json(OUT_FW, records)
                    print(f"[*] checkpoint: processed {done}/{total}, total {len(records)} -> {OUT_FW}")
                except PermissionError:
                    time.sleep(0.2)
                    save_json(OUT_FW, records)
                    print(f"[*] checkpoint(retry): processed {done}/{total}, total {len(records)} -> {OUT_FW}")
        save_json(OUT_FW, records)
        print(f"[+] Firmware saved: total {len(records)} -> {OUT_FW}")

async def main_async():
    seeds = ["ant","armor","cx-","emg","es-","ex-","es1","fwa","gs-","gs1","gs2","lte","mg-","mg1","multy","nap","nas","nbg","nr-","nsg","nsw","nwa","nwd","nxc","pla","poe","rgs","rps","sur","stb","scr","usg","vmg","vpn","wac","wap","wre","wax","wbe","xs-","xgs","xmg","zywall"]
    models = load_json(OUT_MODELS)
    if not models:
        models = await scan_models(seeds)
    else:
        print(f"[*] Using existing models: {len(models)} from {OUT_MODELS}")
    await harvest_firmware(models)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
