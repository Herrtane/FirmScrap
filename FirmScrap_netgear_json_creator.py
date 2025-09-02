import asyncio, aiohttp, json, os, re, sys, tempfile, random, time
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urlparse

BASE = "https://www.netgear.com"
API_SEARCH = BASE + "/api/v2/getsearchjson/?componentId={cid}&publicationId={pub}"
API_DETAILS = BASE + "/api/v2/product/getproductdetails/?componentId={cid}&publicationId={pub}"
OUT_MODELS = "netgear_all_models.json"
OUT_FW = "netgear_firmware_links.json"

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

HOST_ALLOW_RE = re.compile(r"(?:^|\.)downloads\.netgear\.com$", re.I)
EXT_ALLOW_RE = re.compile(r"\.(zip|bin|img|chk|trx|tar|tar\.gz|tgz)$", re.I)
TITLE_DENY_RE = re.compile(r"\b(app|nighthawk app|genie|insight|raidiator|readynas|readycloud)\b", re.I)
URL_DENY_RE = re.compile(r"(play\.google\.com|itunes\.apple\.com|apps\.apple\.com|microsoft\.com|windowsstore\.com)", re.I)

def save_json(path: str, data: Any, retries: int = 12):
    path = os.path.abspath(path)
    d = os.path.dirname(path) or "."
    delay = 0.05
    for attempt in range(1, retries + 1):
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
                delay = min(delay * 2, 2.0)
                continue
        except Exception:
            try: os.remove(tmp)
            except Exception: pass
            raise
    raise PermissionError(f"save_json failed after {retries} retries for {path}")

def load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("/"):
        return BASE + u
    return u

async def _fetch_json(session: aiohttp.ClientSession, url: str, max_retry=4):
    backoff = 1.6
    for attempt in range(1, max_retry+1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status in (204, 404): return None
                if r.status >= 500 or r.status == 429:
                    await asyncio.sleep(min(10, backoff**attempt)); continue
                r.raise_for_status()
                return await r.json(content_type=None)
        except Exception:
            await asyncio.sleep(min(10, backoff**attempt))
    return None

def _extract_items_from_content_string(s: str):
    s = (s or "").strip()
    items = []
    if not s:
        return items
    try:
        obj = json.loads(s)
        if isinstance(obj, list): return obj
        if isinstance(obj, dict): return [obj]
    except Exception:
        pass
    try:
        i = s.find('['); j = s.rfind(']')
        if i != -1 and j != -1 and j > i:
            obj2 = json.loads(s[i:j+1])
            if isinstance(obj2, list): return obj2
            if isinstance(obj2, dict): return [obj2]
    except Exception:
        pass
    dec = json.JSONDecoder(); idx = 0; n = len(s)
    while idx < n:
        while idx < n and s[idx].isspace(): idx += 1
        if idx >= n: break
        try:
            obj, next_idx = dec.raw_decode(s, idx)
            if isinstance(obj, list): items.extend(obj)
            elif isinstance(obj, dict): items.append(obj)
            idx = next_idx
        except Exception:
            break
    return items

def _iter_candidate_json_strings(x: Any):
    stack = [x]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for v in cur.values(): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
        elif isinstance(cur, str):
            t = cur.strip()
            if '[' in t and ']' in t and ('"model"' in t or '"url"' in t or '"title"' in t or '"tcm"' in t):
                yield t

def _parse_component_id(tcm: str) -> int:
    if not tcm: return 0
    m = re.search(r'tcm:\d+-(\d+)', tcm)
    return int(m.group(1)) if m else 0

async def get_all_models(session: aiohttp.ClientSession, component_ids: List[int], publication_id: int = 11) -> List[Dict[str, str]]:
    seen: Set[str] = set()
    rows: List[Dict[str, str]] = []
    for cid in component_ids:
        url = API_SEARCH.format(cid=cid, pub=publication_id)
        data = await _fetch_json(session, url)
        if not data:
            print(f"[-] componentId={cid} no data")
            continue
        candidates = list(_iter_candidate_json_strings(data))
        if not candidates:
            print(f"[-] componentId={cid} no candidate JSON strings found")
            continue
        added_total = 0
        for s in candidates:
            arr = _extract_items_from_content_string(s)
            added = 0
            for item in arr if isinstance(arr, list) else []:
                if not isinstance(item, dict): continue
                model = (item.get("model") or "").strip()
                title = (item.get("title") or "").strip()
                url2  = _normalize_url(item.get("url") or "")
                tcm   = (item.get("tcm") or "").strip()
                comp  = _parse_component_id(tcm)
                if not model: continue
                key = model.upper()
                if key in seen: continue
                seen.add(key)
                rows.append({
                    "Vendor": "NETGEAR",
                    "Model": model,
                    "Title": title,
                    "ProductURL": url2,
                    "ComponentId": comp
                })
                added += 1
            added_total += added
        print(f"[+] componentId={cid}: +{added_total} (total {len(rows)})")
    rows.sort(key=lambda x: (x["Model"].upper(), x["Title"].upper()))
    return rows

def _is_allowed_firmware_url(u: str) -> bool:
    try:
        p = urlparse(u)
        host_ok = HOST_ALLOW_RE.search(p.netloc or "") is not None
        ext_ok = EXT_ALLOW_RE.search((p.path or "")) is not None
        deny = URL_DENY_RE.search(u) is not None
        return host_ok and ext_ok and not deny
    except Exception:
        return False

def _looks_like_nonfw_title(title: str) -> bool:
    if not title: return False
    return TITLE_DENY_RE.search(title) is not None

def _extract_fw_from_downloadmap(download_map: dict, model: str) -> List[Dict]:
    out = []
    skipped = 0
    def pull(section: str):
        nonlocal skipped
        for entry in (download_map.get(section) or []):
            d = (((entry or {}).get("content") or {}).get("data") or {})
            if not d: 
                continue
            t = (((d.get("type") or {})).get("title") or "").strip().lower()
            if t != "firmware":
                continue
            url = (d.get("url") or "").strip()
            title = (d.get("title") or "").strip()
            if not url:
                continue
            if _looks_like_nonfw_title(title) or not _is_allowed_firmware_url(url):
                skipped += 1
                continue
            size = (d.get("size") or "").strip()
            rel  = (d.get("optional_url") or "").strip()
            ver = ""
            m = re.search(r'(?i)\b(v?\d+(?:\.\d+)+)\b', title) or re.search(r'(?i)\b(v?\d+(?:\.\d+)+)\b', os.path.basename(url))
            if m: ver = m.group(1).lstrip('vV')
            out.append({
                "Vendor": "NETGEAR",
                "Model": model.upper(),
                "Version": ver,
                "Download": url,
                "Section": section,
                "Title": title,
                "Size": size,
                "ReleaseNotes": rel
            })
    pull("latest"); pull("older")
    return out

async def fetch_firmware_by_component(session: aiohttp.ClientSession, model: str, component_id: int, idx: int, total: int) -> Tuple[str, List[Dict]]:
    if not component_id:
        print(f"[-] [{idx}/{total}] {model}: missing component id")
        return model, []
    pubs = [11, 122, 1]
    for pub in pubs:
        url = API_DETAILS.format(cid=component_id, pub=pub)
        print(f"[*] [{idx}/{total}] {model}: getproductdetails cid={component_id} pub={pub}")
        data = await _fetch_json(session, url, max_retry=4)
        if not data:
            print(f"[-] [{idx}/{total}] {model}: fetch failed for pub={pub}")
            continue
        download_map = ((((data.get("data") or {}).get("typedComponent") or {}).get("downloadMap") or {}))
        items = _extract_fw_from_downloadmap(download_map, model)
        if items:
            versions_vals = (((((data.get("data") or {}).get("typedComponent") or {}).get("content") or {}).get("data") or {}).get("versions") or {}).get("$values") or []
            versions = [ (v or {}).get("mversion","").strip() for v in versions_vals if isinstance(v, dict) ]
            if versions:
                for it in items: it["HWRevisions"] = versions
            print(f"[+] [{idx}/{total}] {model}: {len(items)} firmware entries (pub={pub})")
            return model, items
        else:
            print(f"[*] [{idx}/{total}] {model}: no allowed firmware in pub={pub}")
    return model, []

async def _amain():
    component_ids = [52117]
    records: List[Dict[str, Any]] = []
    old_fw = load_json(OUT_FW)
    if isinstance(old_fw, list): records = old_fw
    seen = {(r.get("Model"), r.get("Download")) for r in records}
    headers = {
        "Accept": "application/json",
        "User-Agent": random.choice(UA),
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        models = load_json(OUT_MODELS)
        if not models:
            models = await get_all_models(session, component_ids)
            save_json(OUT_MODELS, models)
            print(f"[+] Saved model list -> {OUT_MODELS}")
        print(f"[*] Total models: {len(models)}")
        targets = [(i, m["Model"], int(m.get("ComponentId") or 0)) for i, m in enumerate(models, 1) if isinstance(m, dict) and m.get("Model")]
        total = len(targets)
        sem = asyncio.Semaphore(8)
        async def task(i: int, model: str, cid: int):
            async with sem:
                try:
                    return await fetch_firmware_by_component(session, model, cid, i, total)
                except Exception:
                    print(f"[-] [{i}/{total}] {model}: exception")
                    return model, []
        coros = [task(i, m, cid) for (i, m, cid) in targets]
        base = len(records); done = 0
        for fut in asyncio.as_completed(coros):
            model, items = await fut
            added = 0
            for r in items:
                key = (r["Model"], r["Download"])
                if key in seen: continue
                seen.add(key); records.append(r); added += 1
                if (len(records) - base) % 10 == 0:
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

def main():
    asyncio.run(_amain())

if __name__ == "__main__":
    main()
