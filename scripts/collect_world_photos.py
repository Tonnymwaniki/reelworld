"""
ReelWorld: collect openly licensed Nairobi photos from Wikimedia Commons.

Usage:
    pip install requests
    python collect_world_photos.py

Creates (inside your Documents folder):
    Documents/ReelWorld/world/<theme>/*.jpg
    Documents/ReelWorld/world/manifest.csv   (file, theme, title, author, license, source_url)

Review the images afterwards and delete any that don't fit. Keep manifest.csv:
it records where each photo came from and under what license.
"""
import csv
import re
import time
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "ReelWorldHackathon/0.1 (https://github.com/Tonnymwaniki)"}
PER_THEME = 25
OUT = Path.home() / "Documents" / "ReelWorld" / "world"

THEMES = {
    "market": ["Nairobi market", "Gikomba market", "Kenya market vegetables", "Marikiti market Nairobi",
               "Kisumu market", "Mombasa market", "Kenya food stall", "Maasai market Kenya"],
    "street": ["Nairobi street", "Nairobi city centre", "Nairobi CBD", "Nairobi matatu",
               "Mombasa street", "Kisumu street", "Nakuru town", "Kenya road"],
    "park": ["Uhuru Park Nairobi", "Nairobi National Park", "Karura Forest", "Central Park Nairobi",
             "Maasai Mara", "Lake Nakuru National Park", "Amboseli", "Kenya wildlife park"],
    "hills": ["Ngong Hills", "Nairobi skyline", "Kenya landscape Rift Valley", "Mount Kenya",
              "Aberdare Range", "Great Rift Valley Kenya", "Lake Naivasha", "Hell's Gate Kenya"],
}

# A photo is kept only if one of these appears in its title, description or
# Commons categories. This keeps the collection Kenyan.
KENYA_TERMS = [
    "kenya", "nairobi", "mombasa", "kisumu", "nakuru", "eldoret", "naivasha", "thika",
    "ngong", "maasai", "mara", "amboseli", "tsavo", "samburu", "lamu", "malindi",
    "aberdare", "karura", "gikomba", "kibera", "matatu", "rift valley",
]


def is_kenyan(page, meta):
    text = " ".join([
        page.get("title", ""),
        strip_html(meta.get("ImageDescription", {}).get("value")),
        strip_html(meta.get("Categories", {}).get("value")),
        " ".join(c.get("title", "") for c in page.get("categories", [])),
    ]).lower()
    return any(term in text for term in KENYA_TERMS)


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def search(query, limit=40):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,  # File: namespace
        "gsrlimit": limit,
        "prop": "imageinfo|categories",
        "cllimit": "max",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 1280,
    }
    r = requests.get(API, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    return list(pages.values())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Saving to: {OUT}")
    seen = set()
    rows = []

    for theme, queries in THEMES.items():
        (OUT / theme).mkdir(exist_ok=True)
        count = 0
        for q in queries:
            if count >= PER_THEME:
                break
            try:
                results = search(q)
            except Exception as e:
                print(f"search failed for {q!r}: {e}")
                continue
            for page in results:
                if count >= PER_THEME:
                    break
                info = (page.get("imageinfo") or [{}])[0]
                title = page.get("title", "")
                if title in seen or info.get("mime") != "image/jpeg":
                    continue
                if info.get("width", 0) < 800:
                    continue
                meta = info.get("extmetadata", {})
                license_name = strip_html(meta.get("LicenseShortName", {}).get("value"))
                if not license_name:
                    continue
                if not is_kenyan(page, meta):
                    continue
                url = info.get("thumburl") or info.get("url")
                fname = f"{theme}_{count + 1:03d}.jpg"
                path = OUT / theme / fname
                try:
                    img = requests.get(url, headers=HEADERS, timeout=60)
                    img.raise_for_status()
                    path.write_bytes(img.content)
                except Exception as e:
                    print(f"download failed for {title}: {e}")
                    continue
                seen.add(title)
                count += 1
                rows.append({
                    "file": str(path),
                    "theme": theme,
                    "title": title,
                    "author": strip_html(meta.get("Artist", {}).get("value")),
                    "license": license_name,
                    "source_url": info.get("descriptionurl", ""),
                })
                print(f"[{theme}] {count}/{PER_THEME} {title}")
                time.sleep(1)  # be polite to Wikimedia
        print(f"{theme}: {count} photos")

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["file", "theme", "title", "author", "license", "source_url"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Done. {len(rows)} photos, manifest at {OUT / 'manifest.csv'}")


if __name__ == "__main__":
    main()
