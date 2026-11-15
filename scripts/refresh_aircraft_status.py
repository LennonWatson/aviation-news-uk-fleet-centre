#!/usr/bin/env python3
"""Refresh last-known ADS-B observations for registrations in index.html.

This is a conservative status tracker, not a live flight tracker. It stores
last-known observations and only labels an aircraft "Possible storage" when
repeated ground detections and a prolonged lack of airborne detections support it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "index.html"
DATA_PATH = ROOT / "data" / "aircraft-status.json"
API_BASE = "https://api.adsb.lol/v2"
DELAY_SECONDS = float(os.getenv("ADSBLOL_REQUEST_DELAY", "1.0"))
TIMEOUT_SECONDS = 25


def extract_js_object(source: str, marker: str) -> dict:
    """Extract a JSON-compatible object literal following a JS marker."""
    start = source.find(marker)
    if start < 0:
        raise RuntimeError(f"Could not find {marker!r} in index.html")
    start += len(marker)
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source) or source[start] != "{":
        raise RuntimeError(f"{marker} is not followed by an object")
    depth, quoted, escaped = 0, False, False
    for pos in range(start, len(source)):
        ch = source[pos]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            continue
        if ch == '"':
            quoted = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(source[start:pos + 1])
    raise RuntimeError(f"Could not parse object after {marker}")


def registrations_from_site() -> list[str]:
    html = HTML_PATH.read_text(encoding="utf-8")
    reg_data = extract_js_object(html, "const REG_DATA=")
    regs = {
        str(reg).strip().upper()
        for type_map in reg_data.values()
        for reg_list in type_map.values()
        for reg in reg_list
        if str(reg).strip()
    }
    return sorted(regs)


def api_lookup(registration: str, api_key: str | None) -> dict | None:
    url = f"{API_BASE}/reg/{quote(registration, safe='')}"
    headers = {"User-Agent": "AviationNewsUK-FleetCentre/1.0 (aircraft last-seen database)"}
    if api_key:
        headers["x-api-key"] = api_key
    req = Request(url, headers=headers)
    with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    aircraft = payload.get("ac", []) if isinstance(payload, dict) else []
    if isinstance(payload, dict) and payload.get("r"):
        aircraft = [payload]
    # Only accept a result whose registration matches the requested mark.
    for item in aircraft:
        if str(item.get("r", "")).strip().upper() == registration:
            return item
    return None


def iso_from_age(now: datetime, seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(now.timestamp() - float(seconds), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def classify(record: dict, now: datetime) -> tuple[str, str]:
    """Return conservative status and confidence."""
    def age_days(field: str) -> float | None:
        value = record.get(field)
        if not value:
            return None
        try:
            return (now - datetime.fromisoformat(value)).total_seconds() / 86400
        except (TypeError, ValueError):
            return None

    airborne_age = age_days("last_airborne_detected_utc")
    ground_age = age_days("last_ground_detected_utc")
    ground_count = int(record.get("ground_observations", 0))

    if airborne_age is not None and airborne_age <= 2:
        return "Recent airborne activity", "High"
    if ground_age is not None and ground_age <= 2:
        return "Recently detected on ground", "High"
    if ground_count >= 5 and ground_age is not None and ground_age >= 7 and (
        airborne_age is None or airborne_age >= 7
    ):
        return "Possible storage", "Low"
    if airborne_age is not None:
        return "Previously detected airborne", "Medium"
    if ground_age is not None:
        return "Previously detected on ground", "Medium"
    return "No ADS-B detection recorded", "Unknown"


def main() -> int:
    if not HTML_PATH.exists():
        print("ERROR: index.html not found at repository root", file=sys.stderr)
        return 2

    regs = registrations_from_site()
    old = json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}
    records = old.get("aircraft", {})
    now = datetime.now(timezone.utc)
    api_key = os.getenv("ADSBLOL_API_KEY", "").strip() or None
    updated = 0
    not_seen = 0
    errors: list[str] = []

    print(f"Checking {len(regs)} registrations using adsb.lol...")
    for index, reg in enumerate(regs, start=1):
        try:
            item = api_lookup(reg, api_key)
            if item:
                rec = records.get(reg, {
                    "registration": reg,
                    "ground_observations": 0,
                    "airborne_observations": 0,
                })
                seen = item.get("seen")
                seen_pos = item.get("seen_pos", seen)
                detected = iso_from_age(now, seen if seen is not None else 0)
                positioned = iso_from_age(now, seen_pos if seen_pos is not None else seen)
                rec.update({
                    "registration": reg,
                    "icao_hex": item.get("hex") or rec.get("icao_hex"),
                    "type_code": item.get("t") or rec.get("type_code"),
                    "callsign": (item.get("flight") or "").strip() or rec.get("callsign"),
                    "last_detected_utc": detected or rec.get("last_detected_utc"),
                    "last_position_utc": positioned or rec.get("last_position_utc"),
                    "latitude": item.get("lat") if item.get("lat") is not None else rec.get("latitude"),
                    "longitude": item.get("lon") if item.get("lon") is not None else rec.get("longitude"),
                    "altitude_baro": item.get("alt_baro"),
                    "ground_speed_kt": item.get("gs"),
                    "track_degrees": item.get("track"),
                    "source": "adsb.lol",
                    "last_checked_utc": now.isoformat(),
                })
                if item.get("alt_baro") == "ground":
                    rec["ground_observations"] = int(rec.get("ground_observations", 0)) + 1
                    rec["last_ground_detected_utc"] = detected or now.isoformat()
                elif isinstance(item.get("alt_baro"), (int, float)):
                    rec["airborne_observations"] = int(rec.get("airborne_observations", 0)) + 1
                    rec["last_airborne_detected_utc"] = detected or now.isoformat()
                records[reg] = rec
                updated += 1
            else:
                not_seen += 1
                # Preserve previous sighting; a missing API result is not evidence
                # that the aircraft is stored, retired, or no longer exists.
                rec = records.setdefault(reg, {
                    "registration": reg,
                    "ground_observations": 0,
                    "airborne_observations": 0,
                })
                rec["last_checked_utc"] = now.isoformat()
            if index % 50 == 0:
                print(f"Processed {index}/{len(regs)}")
        except HTTPError as exc:
            errors.append(f"{reg}: HTTP {exc.code}")
            if exc.code == 429:
                retry = int(exc.headers.get("Retry-After", "60"))
                print(f"Rate limited; waiting {retry} seconds")
                time.sleep(max(5, min(retry, 300)))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            errors.append(f"{reg}: {type(exc).__name__}: {exc}")
        if index < len(regs):
            time.sleep(DELAY_SECONDS)

    for rec in records.values():
        status, confidence = classify(rec, now)
        rec["status"] = status
        rec["confidence"] = confidence

    output = {
        "updated_utc": now.isoformat(),
        "source": "adsb.lol",
        "licence": "Open Database License (ODbL) 1.0",
        "attribution": "Aircraft observations provided by adsb.lol",
        "registrations_in_site_database": len(regs),
        "aircraft_records": len(records),
        "records_updated_this_run": updated,
        "registrations_not_returned_by_api": not_seen,
        "errors": errors[:100],
        "aircraft": records,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(
        f"Saved {len(records)} records. Updated: {updated}; "
        f"not returned: {not_seen}; errors: {len(errors)}"
    )
    # Don't fail the workflow for occasional per-registration misses.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
