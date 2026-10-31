"""Face matching for owner self-tagging suggestions (backend/face_match.py).

Suggest-confirm ONLY: the owner uploads one reference face, the scan
ranks their OWN photos by similarity, and the owner confirms each
suggestion ("I'm in this" / "Not me"). Nothing here ever writes a
tag, identifies anyone else, or names a person. Reference data lives
in git-ignored data/face/ and is served back only as the owner's own
preview. Standard OpenCV only: Haar detection + LBPH matching.
"""

import base64
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FACE_DIR = ROOT / "data" / "face"
FACE_SIZE = 128
PREVIEW_MAX = 640

# LBPH distance: lower means closer. Bands tuned on the owner's first
# scan: previously tagged self-photos scored 94-101 (reference itself 0),
# a known not-me photo 111.
BANDS = ((95, "strong"), (110, "likely"))  # anything else is "weak"

_cascade = None


def band(distance):
    """Human band for an LBPH distance (or None when no face to score)."""
    if distance is None:
        return None
    for edge, name in BANDS:
        if distance < edge:
            return name
    return "weak"


CASCADE_FILE = "haarcascade_frontalface_default.xml"


def cascade():
    """Shared Haar face detector: the copy bundled with OpenCV, else
    the copy fetched by scripts/fetch_face_data.py. Honest error when
    neither exists."""
    global _cascade
    if _cascade is None:
        for path in (Path(cv2.data.haarcascades) / CASCADE_FILE,
                     FACE_DIR / CASCADE_FILE):
            hit = cv2.CascadeClassifier(str(path))
            if not hit.empty():
                _cascade = hit
                break
        else:
            _cascade = cv2.CascadeClassifier()
    if _cascade.empty():
        raise RuntimeError("face detection data is missing;"
                           " run python scripts/fetch_face_data.py")
    return _cascade


def b64_to_bytes(s):
    """Raw or data-URL base64 to bytes; ValueError when unreadable."""
    s = (s or "").strip()
    if "," in s and ";base64," in s:
        s = s.split(";base64,", 1)[1]
    try:
        return base64.b64decode(s, validate=True)
    except Exception:
        raise ValueError("that is not a readable image.")


def decode_image(data):
    """Image bytes to BGR array; ValueError when undecodable."""
    if not data:
        raise ValueError("that is not a readable image.")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise ValueError("that is not a readable image.")
    return img


def to_gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def detect_faces(gray):
    """Face boxes as (x, y, w, h), largest first; [] when none."""
    found = cascade().detectMultiScale(gray, scaleFactor=1.08, minNeighbors=3,
                                       minSize=(24, 24))
    if found is None or len(found) == 0:
        return []
    return sorted((tuple(int(v) for v in b) for b in found),
                  key=lambda b: b[2] * b[3], reverse=True)


def crop_face(gray, box):
    """One face box to an equalized FACE_SIZE matching crop."""
    x, y, w, h = box
    x, y = max(0, x), max(0, y)
    crop = gray[y:y + h, x:x + w]
    if crop.size == 0:
        raise ValueError("that face box is empty.")
    small = cv2.resize(crop, (FACE_SIZE, FACE_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(small)


def _ref_paths():
    return FACE_DIR / "reference_orig.jpg", FACE_DIR / "reference.png"


def save_reference(image_bytes):
    """Keep the largest face as the matching reference. Returns the
    face count seen; ValueError when no face (or no image) is found."""
    img = decode_image(image_bytes)
    gray = to_gray(img)
    boxes = detect_faces(gray)
    if not boxes:
        raise ValueError("no face found in that photo; try a clear front-facing one.")
    FACE_DIR.mkdir(parents=True, exist_ok=True)
    orig_p, crop_p = _ref_paths()
    h, w = img.shape[:2]
    scale = min(1.0, PREVIEW_MAX / max(h, w))
    small = img if scale >= 1.0 else cv2.resize(
        img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(orig_p), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    cv2.imwrite(str(crop_p), crop_face(gray, boxes[0]))
    return {"faces": len(boxes)}


def reference_present():
    orig_p, crop_p = _ref_paths()
    return orig_p.is_file() and crop_p.is_file()


def reference_preview_b64():
    """Data URL of the saved reference, or None."""
    orig_p, _ = _ref_paths()
    if not orig_p.is_file():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(
        orig_p.read_bytes()).decode("ascii")


def clear_reference():
    """Delete the reference files; True when anything was removed."""
    gone = False
    for p in _ref_paths():
        try:
            if p.is_file():
                p.unlink()
                gone = True
        except OSError:
            pass
    return gone


def load_reference_crop():
    """Reference matching crop, or None when no reference is saved."""
    _, crop_p = _ref_paths()
    if not crop_p.is_file():
        return None
    return cv2.imread(str(crop_p), cv2.IMREAD_GRAYSCALE)


def train(crop):
    """LBPH matcher trained on the single reference crop."""
    make = getattr(getattr(cv2, "face", None), "LBPHFaceRecognizer_create", None)
    if make is None:
        raise RuntimeError("this OpenCV install has no face matcher (need contrib).")
    recog = make()
    recog.train([crop], np.array([0], dtype=np.int32))
    return recog


def distance(recog, crop):
    """LBPH distance of one face crop to the reference (lower = closer)."""
    _, dist = recog.predict(crop)
    return float(dist)


def scan_photo(path, recog):
    """{faces, distance} for one photo file; distance is the best (min)
    match or None when no face is found. Never writes anything."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return {"faces": 0, "distance": None, "unreadable": True}
    gray = to_gray(img)
    boxes = detect_faces(gray)
    if not boxes:
        return {"faces": 0, "distance": None}
    best = min(distance(recog, crop_face(gray, b)) for b in boxes)
    return {"faces": len(boxes), "distance": best}
