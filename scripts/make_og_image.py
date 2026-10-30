"""Build the landing share-preview image (1200x630) with Honest data only.

Approximates frontend/design/stitch_export_final/
reelworld_social_share_preview_image_1200x630/, but every photo, credit
and count is real: tiles use world photos + manifest credits, and the
footer counts come from data/manifest.csv + data/places.json.
Dropped from the design: fake cluster latency, invented photographer
names, invented "verified %" badges, invented domain.

Run from the project root:  python scripts/make_og_image.py
Writes: frontend/og-image.png (served at /og-image.png)
"""
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 630

CANVAS = (254, 248, 244)
INK = (27, 30, 35)
INK_2 = (85, 91, 99)
INK_MUT = (128, 135, 145)
TERRA = (200, 90, 50)
TERRA_LT = (249, 238, 232)
SAGE = (45, 106, 79)
SAGE_LT = (237, 246, 241)
WHITE = (255, 255, 255)
CARD_BG = (248, 243, 239)
HAIR = (27, 30, 35, 26)

FONTS = Path("C:/Windows/Fonts")


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


F_SANS = "arial.ttf"
F_SANS_B = "arialbd.ttf"
F_MONO = "cour.ttf"
F_MONO_B = "courbd.ttf"


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def text(d, xy, s, f, fill):
    d.text(xy, s, font=f, fill=fill)


def main():
    rows = list(csv.DictReader(open(ROOT / "data/manifest.csv", encoding="utf-8-sig")))
    by_base = {}
    for r in rows:
        base = (r.get("file") or "").replace("\\", "/").split("/")[-1].lower()
        by_base[base] = r
    places = json.loads((ROOT / "data/places.json").read_text(encoding="utf-8"))
    n_photos = len(rows)
    n_photogs = len({r["author"] for r in rows if (r.get("author") or "").strip()})
    n_places = len(places)

    tiles = []
    for base in ("market_001.jpg", "cbd_001.jpg", "street_002.jpg"):
        p = next((ROOT / "data/photos/world").rglob(base), None)
        if p is None:
            raise SystemExit(f"tile photo missing: {base}")
        meta = by_base.get(base, {})
        tiles.append({"img": Image.open(p).convert("RGB"),
                      "pid": base.rsplit(".", 1)[0],
                      "author": (meta.get("author") or "Unknown").strip(),
                      "license": (meta.get("license") or "").strip()})

    img = Image.new("RGB", (W, H), CANVAS)
    d = ImageDraw.Draw(img, "RGBA")

    # Faint grid.
    for x in range(0, W, 32):
        d.line([(x, 0), (x, H)], fill=(27, 30, 35, 9))
    for y in range(0, H, 32):
        d.line([(0, y), (W, y)], fill=(27, 30, 35, 9))

    # Frame + corner tags.
    rrect(d, [16, 16, W - 16, H - 16], 16, outline=(27, 30, 35, 26), width=1)
    tag_f = font(F_MONO, 15)
    text(d, (48, 8), "REELWORLD  ·  1200x630", tag_f, INK_MUT)
    tag2 = "OPEN PHOTOGRAPHIC CADASTRE"
    text(d, (W - 48 - d.textlength(tag2, font=tag_f), H - 26), tag2, tag_f, INK_MUT)

    # Header: aperture mark + brand.
    rrect(d, [48, 48, 96, 96], 10, fill=INK)
    cx, cy, rr = 72, 72, 17
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=CANVAS, width=3)
    for i in range(6):
        import math
        a = math.pi * i / 3
        d.line([(cx, cy), (cx + rr * math.cos(a), cy + rr * math.sin(a))],
               fill=CANVAS, width=2)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=CANVAS)
    text(d, (110, 46), "REELWORLD", font(F_SANS_B, 34), INK)
    text(d, (110, 84), "Conversational visual knowledge network for photos",
         font(F_SANS, 17), INK_MUT)

    # Built pill (right).
    pill_t = "Built with Muse Spark Open"
    pill_f = font(F_SANS_B, 17)
    pw = d.textlength(pill_t, font=pill_f) + 52
    px0 = W - 48 - pw
    rrect(d, [px0, 52, W - 48, 92], 20, fill=WHITE, outline=(200, 90, 50, 90), width=2)
    d.ellipse([px0 + 16, 66, px0 + 28, 78], fill=TERRA)
    text(d, (px0 + 36, 62), pill_t, pill_f, INK)

    # Middle left: tag, headline, sub, query box.
    lx = 48
    tag = "SIGHTLINE CORRELATION ENGINE"
    tagf = font(F_MONO_B, 14)
    tw = d.textlength(tag, font=tagf) + 24
    rrect(d, [lx, 150, lx + tw, 178], 6, fill=TERRA_LT, outline=(232, 191, 176), width=1)
    text(d, (lx + 12, 155), tag, tagf, TERRA)
    y = 196
    for line, terra_word in (("Describe a photo.", None), ("Reel will find it,", "Reel"),
                             ("and show its evidence.", None)):
        if terra_word:
            w0 = d.textlength(terra_word + " ", font=font(F_SANS_B, 40))
            text(d, (lx, y), terra_word, font(F_SANS_B, 40), TERRA)
            rest = line.replace(terra_word + " ", "")
            text(d, (lx + w0, y), rest, font(F_SANS_B, 40), INK)
        else:
            text(d, (lx, y), line, font(F_SANS_B, 40), INK)
        y += 48
    sub = ("Grounded retrieval across verified Kenyan",
           "photos. No guesses, no faces stored.")
    y += 6
    for line in sub:
        text(d, (lx, y), line, font(F_SANS, 19), INK_2)
        y += 27

    # Query box.
    qy = y + 12
    rrect(d, [lx, qy, lx + 430, qy + 96], 12, fill=WHITE, outline=(27, 30, 35, 26))
    text(d, (lx + 16, qy + 10), "EXAMPLE QUERY", font(F_MONO, 13), INK_MUT)
    q = '"a busy street market with vegetables"'
    text(d, (lx + 16, qy + 34), q, font(F_MONO, 14), INK)
    text(d, (lx + 16, qy + 60), "answered only from stored records", font(F_SANS, 14), SAGE)

    # Middle right: 3 honest photo tiles.
    tx, tile_w, gap = 510, 200, 16
    for i, t in enumerate(tiles):
        x0 = tx + i * (tile_w + gap)
        x1 = x0 + tile_w
        rrect(d, [x0, 150, x1, 470], 12, fill=WHITE, outline=(27, 30, 35, 26))
        ph = cover(t["img"], tile_w - 8, 190)
        mask = Image.new("L", ph.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, *ph.size], radius=8, fill=255)
        img.paste(ph, (x0 + 4, 186), mask)
        text(d, (x0 + 12, 158), "#" + t["pid"], font(F_MONO_B, 14), INK_2)
        text(d, (x0 + 12, 384), t["pid"].replace("_", " ").title(),
             font(F_SANS_B, 16), INK)
        au = t["author"][:26]
        text(d, (x0 + 12, 408), au, font(F_SANS, 14), INK_MUT)
        if t["license"]:
            text(d, (x0 + 12, 430), t["license"], font(F_SANS_B, 14), TERRA)

    # Footer.
    fy = H - 78
    d.line([(48, fy), (W - 48, fy)], fill=(27, 30, 35, 26))
    foot = (f"Zero Biometric Storage | Auditable Citations | "
            f"{n_photos} Plates · {n_photogs} Photographers · {n_places} Places")
    text(d, (48, fy + 14), foot, font(F_MONO, 15), INK_2)
    tag3 = "Kenya Architectural Cadastre"
    tag3f = font(F_MONO, 15)
    bx1 = W - 48
    bx0 = bx1 - d.textlength(tag3, font=tag3f) - 28
    rrect(d, [bx0, fy + 6, bx1, fy + 40], 6, fill=(27, 30, 35, 12),
          outline=(27, 30, 35, 26))
    text(d, (bx0 + 14, fy + 12), tag3, tag3f, INK)

    out = ROOT / "frontend/og-image.png"
    img.save(out)
    print(f"wrote {out} ({n_photos} plates, {n_photogs} photographers, {n_places} places)")

if __name__ == "__main__":
    main()
