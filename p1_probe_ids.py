import re
from pathlib import Path

for f in ["home.html", "credits.html", "about.html", "_frag_progress.html",
          "_frag_states.html", "_frag_addphoto.html", "_frag_tour.html"]:
    t = (Path("frontend/views") / f).read_text(encoding="utf-8")
    ids = re.findall(r'id="([^"]+)"', t)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    print(f, len(ids), "ids", ("DUPES: " + " ".join(dupes)) if dupes else "ok")
    if f != "home.html":
        print("   ", " ".join(ids[:40]))
