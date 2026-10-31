"""Focused checks for face matching (backend/face_match.py).

Pure logic + OpenCV roundtrips on synthetic images: no photos, no
database, no model. Reference files go to a temp dir.
Run from the project root:  python backend/test_face_match.py
"""
import base64
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import face_match as fm  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def expect_value(fn, label):
    global fails, total
    total += 1
    try:
        fn()
    except ValueError:
        pass
    except Exception as e:  # noqa: BLE001 (any other error is a failure)
        fails += 1
        print(f"FAIL {label}: {type(e).__name__} {e}")
    else:
        fails += 1
        print(f"FAIL {label}: no error raised")


check(fm.band(None) is None, "band none")
check(fm.band(0) == "strong" and fm.band(94.9) == "strong", "band strong")
check(fm.band(95) == "likely" and fm.band(109.9) == "likely", "band likely")
check(fm.band(110) == "weak" and fm.band(500) == "weak", "band weak")

raw = base64.b64encode(b"abc").decode("ascii")
check(fm.b64_to_bytes(raw) == b"abc", "b64 raw")
check(fm.b64_to_bytes("data:image/jpeg;base64," + raw) == b"abc", "b64 data url")
expect_value(lambda: fm.b64_to_bytes("!!!not-b64!!!"), "b64 garbage 400")

expect_value(lambda: fm.decode_image(b"junk-bytes!!"), "decode garbage 400")
expect_value(lambda: fm.decode_image(b""), "decode empty 400")

blank = np.zeros((300, 300), dtype=np.uint8)
check(fm.detect_faces(blank) == [], "blank has no faces")
crop = fm.crop_face(blank, (10, 10, 100, 100))
check(crop.shape == (fm.FACE_SIZE, fm.FACE_SIZE), "crop resizes")

grad = np.tile(np.arange(128, dtype=np.uint8), (128, 1))
flip = 255 - grad
recog = fm.train(grad)
same = fm.distance(recog, grad)
other = fm.distance(recog, flip)
check(same < 1.0 and same < other, "lbph self closer than other")

tmp = tempfile.TemporaryDirectory()
fm.FACE_DIR = Path(tmp.name)
_, buf = cv2.imencode(".png", np.zeros((200, 200, 3), dtype=np.uint8))
expect_value(lambda: fm.save_reference(bytes(buf)), "blank photo saves nothing")
check(fm.reference_present() is False, "no reference yet")
check(fm.reference_preview_b64() is None, "no preview yet")
check(fm.clear_reference() is False, "clear empty false")
missing = fm.scan_photo(Path(tmp.name) / "nope.jpg", recog)
check(missing.get("unreadable") is True, "missing file skipped")

print(f"test_face_match.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
