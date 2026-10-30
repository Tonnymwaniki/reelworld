"""Subject outlines via SAM 3.1 on the Meta Model API.

Docs: https://dev.meta.ai/docs/sam/overview (request),
https://dev.meta.ai/docs/sam/reading-segmentation (wire grammar).
Non-streaming Responses call; boxes are parsed, masks are returned
opaque (the base85 alphabet is unverified, so no decoding is guessed).
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SAM_BASE_URL = ((os.getenv("SAM_BASE_URL") or os.getenv("META_API_BASE_URL")
                 or "https://api.meta.ai/v1").strip()
                or "https://api.meta.ai/v1").rstrip("/")
SAM_MODEL = (os.getenv("SAM_MODEL") or "sam-3.1").strip() or "sam-3.1"


def meta_key():
    """Model API key, or None when unset/placeholder (never raises)."""
    v = (os.getenv("META_API_KEY") or "").strip()
    if not v or v.lower().startswith("paste_") or v.startswith("<"):
        return None
    return v


_BOX_RE = re.compile(r"<\|box;(.*?)\|>")
_MASK_RE = re.compile(r"<\|mask;(.*?)\|>(?=,|$)")
_REC_RE = re.compile(r"(\d+)<\|box;")
_LINE_RE = re.compile(r"<(\d+)f>")


def _fields(token):
    out = {}
    for part in token.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def parse_sam_text(text):
    """Parse SAM special-token text into match dicts.

    Returns [{id, box, box_norm (0-1), confidence, mask}]. Malformed
    records are skipped, never fatal. Empty text -> [] (zero matches
    is a normal result, not an error).
    """
    matches = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not _LINE_RE.match(line):
            continue
        body = line.split(">", 1)[1]
        chunks = re.split(r",(?=\d+<\|box;)", body)
        for ch in chunks:
            m_id = _REC_RE.match(ch)
            m_box = _BOX_RE.search(ch)
            m_mask = _MASK_RE.search(ch)
            if not (m_id and m_box and m_mask):
                continue
            try:
                bf = _fields(m_box.group(1))
                box = {k: int(bf[k]) for k in ("x1", "y1", "x2", "y2", "w", "h")}
                if box["w"] <= 0 or box["h"] <= 0:
                    continue
                mhead, mdata = m_mask.group(1).split(";data=", 1)
                mf = _fields(mhead)
                hm = re.match(r"(\d+),(\d+),([!~])(.*)$", mdata, re.S)
                if not hm:
                    continue
                conf = bf.get("c", mf.get("c"))
                matches.append({
                    "id": int(m_id.group(1)),
                    "box": box,
                    "box_norm": {
                        k: round(box[k] / (box["w"] if k in ("x1", "x2")
                                           else box["h"]), 4)
                        for k in ("x1", "y1", "x2", "y2")},
                    "confidence": (float(conf) if conf is not None else None),
                    "mask": {"h": int(hm.group(1)), "w": int(hm.group(2)),
                             "enc": hm.group(3), "bytes": len(hm.group(4)),
                             "payload": hm.group(4)},
                })
            except (ValueError, KeyError):
                continue
    return matches


def outline_request(photo_bytes, mime, prompt, timeout=120):
    """Call SAM and return (matches, raw_text). Raises RuntimeError."""
    key = meta_key()
    if not key:
        raise RuntimeError("META_API_KEY is not configured")
    b64 = base64.b64encode(photo_bytes).decode("ascii")
    payload = {
        "model": SAM_MODEL,
        "stream": False,
        "metadata": {"include_confidence": "true",
                     "mask_encoding": "one_bit"},
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image",
             "image_url": f"data:{mime};base64,{b64}"}]}],
    }
    req = urllib.request.Request(
        SAM_BASE_URL + "/responses", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"SAM request failed (HTTP {e.code}): {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"SAM request failed: {e}")
    text = ""
    try:
        for item in resp.get("output", []):
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    text += part.get("text", "")
    except AttributeError:
        text = ""
    return parse_sam_text(text), text
