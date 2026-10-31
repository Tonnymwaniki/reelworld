"""Run one story refresh in-process so a failure prints its traceback.

The demo code comes from the environment, never from this file.

PowerShell:
  $env:DEMO_CODE = '<your demo code>'
  python scripts/refresh_probe.py <story_id> [voice]
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


def main():
    sid = sys.argv[1]
    body = {}
    if len(sys.argv) > 2:
        body["voice"] = sys.argv[2]
    client = TestClient(api.app)
    res = client.post(f"/api/stories/{sid}/refresh", json=body,
                      headers={"X-Demo-Code": os.environ.get("DEMO_CODE", "")})
    print("status:", res.status_code)
    try:
        data = res.json()
    except Exception:
        print(res.text[:1000])
        return
    shown = data.get("trace", data) if isinstance(data, dict) else data
    print(json.dumps(shown, indent=1, ensure_ascii=False)[:3000])


main()
