import asyncio, aiohttp, json, os, re, sys, tempfile, time, random
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse
from html import unescape

BASE = "https://iptime.com"
LIST_TMPL = BASE + "/iptime/?pageid={pid}&page_id=126&dffid=1"

OUT_FW = "iptime_firmware_links.json"
VENDOR = "ipTIME"

MAX_CONC = 10
SAVE_EVERY = 25
MAX_EMPTY_PAGES = 5
MAX_PAGES = 50
MIN_HTML = 2000

UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

FW_EXT_RE = re.compile(r"\.(pkg|bin|img|trx|chk|zip|tar|tar\.gz|tgz)$", re.I)

def save_json(path: str, data: Any, retries: int = 12):
    path = os.path.abspath(path)
    d = os.path.dirname(path) or "."
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
                delay = min(delay * 2, 1.5)
        except Exception:
            try: os.remove(tmp)
            except Exception: pass
            raise
    raise PermissionError(f"save_json failed for {path}")

def load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s

async def fetch_html(session: aiohttp.ClientSession, url: str, max_retry=4) -> str:
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

def parse_list_page(html: str) -> List[Dict[str,str]]:
    if not html or len(html) < MIN_HTML:
        return []
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I|re.S)
    out = []
    for row in rows:
        if 'kboard-list-notice' in row:
            continue
        if '[펌웨어' not in row and '펌웨어' not in row:
            continue
        m_href = re.search(r'<a[^>]+href="([^"]+uid=\d+[^"]*?)"[^>]*>', row, flags=re.I)
        m_title = re.search(r'<a[^>]*>(.*?)</a>', row, flags=re.I|re.S)
        m_date  = re.search(r'class="kboard-list-date"[^>]*>(.*?)</td>', row, flags=re.I|re.S)
        if not m_href or not m_title:
            continue
        href = urljoin(BASE, unescape(m_href.group(1)))
        title = _clean(re.sub(r"<[^>]+>", " ", unescape(m_title.group(1))))
        date_txt = _clean(re.sub(r"<[^>]+>", " ", m_date.group(1))) if m_date else ""
        out.append({"url": href, "title": title, "date": date_txt})
    return out

def _is_fw_url(u: str) -> bool:
    if not u: return False
    if "download.iptime.co.kr" not in u.lower():
        return False
    if FW_EXT_RE.search(u) is None:
        return False
    return True

def _basename(u: str) -> str:
    try:
        p = urlparse(u).path
        return os.path.basename(p)
    except Exception:
        return ""

def _guess_model_from_url(u: str) -> str:
    base = _basename(u)
    if not base:
        return ""
    name, _ext = os.path.splitext(base)
    name = name.replace("%20", "_")
    name = name.replace("-", "_")
    parts = name.split("_")
    if len(parts) >= 2:
        return parts[0].upper()
    return parts[0].upper() if parts else ""

def _guess_version_from_url(u: str) -> str:
    base = _basename(u)
    m = re.search(r'[_-]v?(\d+(?:\.\d+)*(?:\([A-Za-z0-9_.-]+\))?)', base, flags=re.I)
    return m.group(1) if m else ""

def parse_post_page(html: str, fallback_title: str, fallback_date: str) -> List[Dict[str,Any]]:
    if not html or len(html) < MIN_HTML:
        return []
    content_match = re.search(r'<div[^>]+class="kboard-document[^"]*"[^>]*>(.*?)</div>\s*</div>', html, flags=re.I|re.S)
    scope = content_match.group(1) if content_match else html
    urls = re.findall(r'href="(https?://[^"]+)"', scope, flags=re.I)
    urls = [unescape(u) for u in urls]
    rows = []
    for u in urls:
        if not _is_fw_url(u):
            continue
        model = _guess_model_from_url(u)
        version = _guess_version_from_url(u)
        rows.append({
            "Vendor": VENDOR,
            "Model": model,
            "Version": version,
            "Release": _clean(fallback_date),
            "Download": u,
            "ReleaseNotes": "",
            "Type": "Firmware",
            "Title": fallback_title
        })
    if not rows:
        mver = re.search(r'펌웨어\s*버전\s*[:：]\s*([0-9A-Za-z.\-_\(\)]+)', scope)
        ver_txt = mver.group(1) if mver else ""
        anchors = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', scope, flags=re.I|re.S)
        for href, label in anchors:
            if not _is_fw_url(href):
                continue
            model = _guess_model_from_url(href) or _clean(re.sub(r"<[^>]+>"," ",label)).upper()
            rows.append({
                "Vendor": VENDOR,
                "Model": model,
                "Version": ver_txt or _guess_version_from_url(href),
                "Release": _clean(fallback_date),
                "Download": href,
                "ReleaseNotes": "",
                "Type": "Firmware",
                "Title": fallback_title
            })
    return rows

async def fetch_post_and_extract(session: aiohttp.ClientSession, item: Dict[str,str], idx: int, total: int) -> Tuple[str, List[Dict[str,Any]]]:
    url = item["url"]; title = item.get("title",""); date = item.get("date","")
    print(f"[*] [{idx}/{total}] post: fetching {url}")
    html = await fetch_html(session, url)
    if not html:
        print(f"[-] [{idx}/{total}] post: fetch failed {url}")
        return url, []
    rows = parse_post_page(html, title, date)
    if rows:
        print(f"[+] [{idx}/{total}] post: {len(rows)} firmware links")
    else:
        print(f"[-] [{idx}/{total}] post: no firmware links")
    return url, rows

async def harvest_all():
    headers = {"User-Agent": random.choice(UA), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    sem = asyncio.Semaphore(MAX_CONC)
    records: List[Dict[str,Any]] = []
    old = load_json(OUT_FW)
    if isinstance(old, list):
        records = old
    seen: Set[Tuple[str,str]] = {(r.get("Model",""), r.get("Download","")) for r in records}

    async with aiohttp.ClientSession(headers=headers) as session:
        page = 1
        empty_streak = 0
        all_posts: List[Dict[str,str]] = []
        while page <= MAX_PAGES:
            list_url = LIST_TMPL.format(pid=page)
            print(f"[*] list page {page}: fetching")
            html = await fetch_html(session, list_url)
            items = parse_list_page(html)
            if not items:
                empty_streak += 1
                print(f"[-] list page {page}: no items (empty_streak={empty_streak})")
                if empty_streak >= MAX_EMPTY_PAGES:
                    break
                page += 1
                continue
            empty_streak = 0
            all_posts.extend(items)
            print(f"[+] list page {page}: +{len(items)} posts (total posts {len(all_posts)})")
            page += 1
        if page > MAX_PAGES:
            print(f"[*] reached MAX_PAGES={MAX_PAGES}, stopping list scan")

        if not all_posts:
            print("[-] no posts discovered, exiting")
            save_json(OUT_FW, records)
            print(f"[+] Firmware saved: total {len(records)} -> {OUT_FW}")
            return

        total = len(all_posts)
        print(f"[*] Total posts to parse: {total}")
        async def task(i: int, it: Dict[str,str]):
            async with sem:
                try:
                    return await fetch_post_and_extract(session, it, i, total)
                except Exception:
                    print(f"[-] [{i}/{total}] post: exception {it.get('url')}")
                    return it.get("url",""), []
        coros = [task(i+1, it) for i, it in enumerate(all_posts)]
        base = len(records); done = 0
        for fut in asyncio.as_completed(coros):
            _, rows = await fut
            added = 0
            for r in rows:
                key = (r.get("Model",""), r.get("Download",""))
                if key in seen:
                    continue
                seen.add(key)
                records.append(r)
                added += 1
                if (len(records) - base) % SAVE_EVERY == 0:
                    try:
                        save_json(OUT_FW, records)
                        print(f"[*] progress: +{len(records)-base} saved -> {OUT_FW}")
                    except PermissionError:
                        time.sleep(0.2)
                        save_json(OUT_FW, records)
                        print(f"[*] progress(retry): +{len(records)-base} saved -> {OUT_FW}")
            done += 1
            if added:
                print(f"[+] post added: +{added} (processed {done}/{total})")
            else:
                print(f"[*] post added: +0 (processed {done}/{total})")
            if done % 50 == 0:
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
    asyncio.run(harvest_all())

if __name__ == "__main__":
    main()
