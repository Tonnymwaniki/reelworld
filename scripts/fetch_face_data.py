"""Fetch the Haar face-detection data once (git-ignored).

Some OpenCV wheels ship no data files; face matching needs this one
XML (~1MB) next to the reference in data/face/. Pinned to this
repo's OpenCV major version, falling back to the default branch.
Run from the project root:  python scripts/fetch_face_data.py
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import cv2  # noqa: E402
import face_match as fm  # noqa: E402

NAME = fm.CASCADE_FILE
TAG = "5.x" if cv2.__version__.startswith("5.") else "4.x"
URLS = [f"https://raw.githubusercontent.com/opencv/opencv/{TAG}/data/haarcascades/{NAME}",
        f"https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/{NAME}"]

dest = fm.FACE_DIR / NAME
dest.parent.mkdir(parents=True, exist_ok=True)
last = None
for url in URLS:
    try:
        with urllib.request.urlopen(url, timeout=60) as res:
            data = res.read()
        if len(data) > 100_000 and data.lstrip().startswith(b"<?xml"):
            dest.write_bytes(data)
            print(f"saved {dest} ({len(data)} bytes) from {url}")
            break
        last = f"bad payload ({len(data)} bytes)"
    except Exception as e:  # noqa: BLE001 (try the next URL)
        last = f"{type(e).__name__}: {e}"
else:
    sys.exit(f"could not fetch {NAME}: {last}")

hit = cv2.CascadeClassifier(str(dest))
sys.exit(0 if not hit.empty() else "downloaded file is not a valid cascade.")
