"""
ReelWorld: add Nairobi CBD building photos (CBK Pension Towers, Times Tower,
Teleposta Towers, Anniversary Towers, Hilton, skyline views) to the world
collection, so personal photos of the city have real counterparts.

Run from the project root:
    python scripts\\add_cbd_photos.py

Saves to:   data/photos/world/cbd/cbd_NNN.jpg
Updates:    data/manifest.csv   (appends rows; skips photos already listed)

It takes at most PER_QUERY photos from each search, so one search cannot use
up the whole quota. All photos come from Wikimedia Commons with their license
recorded. Skim the folder afterwards and delete anything that doesn't fit.
"""
import csv
import re
import time
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "ReelWorldHackathon/0.1 (https://github.com/Tonnymwaniki)"}

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "data" / "photos" / "world" / "cbd"
MANIFEST = ROOT / "data" / "manifest.csv"
FIELDS = ["file", "theme", "title", "author", "license", "source_url"]

THEME = "cbd"
MAX_NEW = 20
PER_QUERY = 3
QUERIES = [
    "CBK Pension Towers",
    "Pension Towers Nairobi",
    "Times Tower Nairobi",
    "Teleposta Towers Nairobi",
    "Anniversary Towers Nairobi",
    "Hilton Hotel Nairobi",
    "Nairobi central business district",
    "Nairobi CBD buildings",
    "Nairobi skyline aerial",
    "Nairobi skyscrapers",
    "Nairobi railway station",
    "Nairobi city view from above",
]

KENYA_TERMS = [
    "kenya", "nairobi", "kicc", "kenyatta", "cbk", "pension towers",
    "times tower", "teleposta", "anniversary towers", "cbd",
]


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def is_kenyan(page, meta):
    text = " ".join([
        page.get("title", ""),
        strip_html(meta.get("ImageDescription", {}).get("value")),
        strip_html(meta.get("Categories", {}).get("value")),
        " ".join(c.get("title", "") for c in page.get("categories", [])),
    ]).lower()
    return any(term in text for term in KENYA_TERMS)


def search(query, limit=40):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo|categories",
        "cllimit": "max",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1280,
    }
    r = requests.get(API, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return list(r.json().get("query", {}).get("pages", {}).values())


def read_manifest():
    if not MANIFEST.exists():
        return []
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    PHOTOS.mkdir(parents=True, exist_ok=True)
    existing = read_manifest()
    seen = {row["title"] for row in existing}
    start = len([r for r in existing if r.get("theme") == THEME])
    new_rows = []
    print(f"Saving to: {PHOTOS}")

    for q in QUERIES:
        if len(new_rows) >= MAX_NEW:
            break
        got = 0
        try:
            results = search(q)
        except Exception as e:
            print(f"search failed for {q!r}: {e}")
            continue
        for page in results:
            if got >= PER_QUERY or len(new_rows) >= MAX_NEW:
                break
            info = (page.get("imageinfo") or [{}])[0]
            title = page.get("title", "")
            if title in seen or info.get("mime") != "image/jpeg":
                continue
            if info.get("width", 0) < 800:
                continue
            meta = info.get("extmetadata", {})
            license_name = strip_html(meta.get("LicenseShortName", {}).get("value"))
            if not license_name or not is_kenyan(page, meta):
                continue
            url = info.get("thumburl") or info.get("url")
            n = start + len(new_rows) + 1
            fname = f"{THEME}_{n:03d}.jpg"
            path = PHOTOS / fname
            try:
                img = requests.get(url, headers=HEADERS, timeout=60)
                img.raise_for_status()
                path.write_bytes(img.content)
            except Exception as e:
                print(f"download failed for {title}: {e}")
                continue
            seen.add(title)
            got += 1
            new_rows.append({
                "file": f"data/photos/world/{THEME}/{fname}",
                "theme": THEME,
                "title": title,
                "author": strip_html(meta.get("Artist", {}).get("value")),
                "license": license_name,
                "source_url": info.get("descriptionurl", ""),
            })
            print(f"[{len(new_rows)}/{MAX_NEW}] ({q}) {title}")
            time.sleep(1)

    if not new_rows:
        print("No new photos found.")
        return

    write_header = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    print(f"Done. Added {len(new_rows)} photos and updated {MANIFEST}")


if __name__ == "__main__":
    main()