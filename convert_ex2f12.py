"""Convert an authorized JKT48 EX2F12 JSON export into the VC monitor ingest format.

Usage: python convert_ex2f12.py EX2F12.json vc-ex2f12-snapshot.json
No network calls are made by this script.
"""
import json
import sys
from pathlib import Path

def convert(doc):
    if doc.get("status") is not True or not isinstance(doc.get("data"), dict):
        raise ValueError("Invalid or unsuccessful API response")
    data = doc["data"]
    code = data.get("code")
    if code != "EX2F12":
        raise ValueError("Expected EX2F12, received %r" % code)
    sessions = data.get("session")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("Missing sessions; refusing to ingest an empty snapshot")
    items = []
    ids = set()
    for session in sessions:
        for key in ("date", "label", "start_time", "end_time", "session_detail"):
            if key not in session:
                raise ValueError("Missing session field: " + key)
        for lane in session["session_detail"]:
            available = lane.get("quota_available")
            if not isinstance(available, bool):
                raise ValueError("Invalid quota_available (must be boolean)")
            item_id = "|".join((code, session["date"], session["label"],
                                session["start_time"], lane["label"]))
            if item_id in ids:
                raise ValueError("Duplicate slot: " + item_id)
            ids.add(item_id)
            items.append({
                "id": item_id,
                "member": lane["jkt48_member_name"],
                "session": ("%s %s %s–%s WIB · %s" %
                            (session["date"], session["label"],
                             session["start_time"][:5], session["end_time"][:5],
                             lane["label"])),
                "stock": None,
                "status": "available" if available else "unavailable",
            })
    if not items:
        raise ValueError("No member slots in response")
    return {"collector": "windows-json-import", "items": items}

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python convert_ex2f12.py EX2F12.json snapshot.json")
    inp, out = map(Path, sys.argv[1:])
    payload = convert(json.loads(inp.read_text(encoding="utf-8-sig")))
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Converted %d slots -> %s" % (len(payload["items"]), out))
