import json
import re
import time
import html as html_lib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET

RSS_URL = "https://www.fl.ru/rss/all.xml"
OUT = Path("feed.json")
MAX_KEEP = 180
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"


def fetch_bytes(url, timeout=20):
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    })
    with urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get_content_charset()


def decode_bytes(data, charset=None):
    for enc in [charset, "utf-8", "cp1251"]:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def clean(s):
    s = html_lib.unescape(s or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_old():
    if not OUT.exists():
        return {}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return {str(x["id"]): x for x in data.get("projects", []) if x.get("id")}
    except Exception:
        return {}


def extract_description(page):
    patterns = [
        r'class=["\'][^"\']*fl-project-content__description-text[^"\']*["\'][^>]*>([\s\S]*?)</div>',
        r'itemprop=["\']description["\'][^>]*>([\s\S]*?)</div>',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, page, flags=re.I)
        if m:
            text = clean(m.group(1))
            if len(text) >= 30:
                return text
    return ""


def fetch_full_description(url, fallback):
    try:
        raw, cs = fetch_bytes(url, timeout=15)
        text = decode_bytes(raw, cs)
        full = extract_description(text)
        if full:
            return full, True
    except (HTTPError, URLError, TimeoutError, OSError):
        pass
    return fallback, False


def parse_budget(title):
    m = re.search(r"\(Бюджет:\s*([\d\s]+)\s*(₽|руб|\$|USD)?", title, flags=re.I)
    if not m:
        return ""
    amount = re.sub(r"\s+", "", m.group(1))
    currency = m.group(2) or "₽"
    return f"{amount} {currency}".strip()


def strip_budget(title):
    return re.sub(r"\s*\(Бюджет:[\s\S]*?\)\s*$", "", title, flags=re.I).strip()


def main():
    raw, charset = fetch_bytes(RSS_URL)
    xml_text = decode_bytes(raw, charset)
    root = ET.fromstring(xml_text)
    old = load_old()
    projects = []

    for item in root.findall("./channel/item"):
        title_raw = clean(item.findtext("title") or "")
        url = clean(item.findtext("link") or "")
        fallback = clean(item.findtext("description") or "")
        m = re.search(r"/projects/(\d+)/", url)
        if not m:
            continue
        pid = m.group(1)
        published = clean(item.findtext("pubDate") or "")
        categories = [clean(x.text or "") for x in item.findall("category")]

        if pid in old and old[pid].get("description_complete"):
            description = old[pid].get("description", fallback)
            complete = True
        else:
            description, complete = fetch_full_description(url, fallback)
            time.sleep(0.35)

        projects.append({
            "id": pid,
            "source": "FL.ru",
            "url": url,
            "title": strip_budget(title_raw),
            "description": description,
            "description_complete": complete,
            "budget": parse_budget(title_raw),
            "published_at": published,
            "categories": categories,
        })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(projects),
        "projects": projects[:MAX_KEEP],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FL feed: {len(projects)} projects; full descriptions: {sum(1 for x in projects if x['description_complete'])}")


if __name__ == "__main__":
    main()
