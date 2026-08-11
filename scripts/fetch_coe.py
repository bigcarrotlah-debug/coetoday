#!/usr/bin/env python3
"""
coetoday.sg data pipeline (v2 — fixed 403).
Pulls the full LTA "COE Bidding Results" dataset from data.gov.sg
via the datastore_search API, rebuilds data/latest.json
(full history + PQP + next close date).
"""
import json, math, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "d_69b3380ad7e51aff3a7dcc84eba52b8a"
API = "https://data.gov.sg/api/action/datastore_search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; coetoday.sg pipeline; +https://coetoday.sg)"}
OUT = Path(__file__).resolve().parent.parent / "data" / "latest.json"
SGT = timezone(timedelta(hours=8))

CAT_MAP = {
    "Category A": "A", "Category B": "B", "Category C": "C",
    "Category D": "D", "Category E": "E",
}

def fetch_rows():
    """Page through datastore_search until all records are in."""
    rows, offset, limit = [], 0, 5000
    while True:
        qs = urllib.parse.urlencode({"resource_id": DATASET_ID, "limit": limit, "offset": offset})
        req = urllib.request.Request(f"{API}?{qs}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.load(r)
        if not payload.get("success"):
            raise RuntimeError(f"API returned success=false: {payload}")
        batch = payload["result"]["records"]
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    if not rows:
        raise RuntimeError("API returned zero records — check DATASET_ID")
    return rows

def month_label(month_str, bidding_no):
    dt = datetime.strptime(month_str, "%Y-%m")
    return f"{dt.strftime('%b %Y')} · {'1st' if str(bidding_no)=='1' else '2nd'}"

def close_date_guess(month_str, bidding_no):
    """1st/3rd Wednesday of the month (good enough for charting)."""
    dt = datetime.strptime(month_str, "%Y-%m").replace(tzinfo=SGT)
    wednesdays = []
    d = dt
    while d.month == dt.month:
        if d.weekday() == 2:
            wednesdays.append(d)
        d += timedelta(days=1)
    idx = 0 if str(bidding_no) == "1" else 2
    w = wednesdays[min(idx, len(wednesdays)-1)]
    return w.date().isoformat()

def next_close(now):
    """Next 1st/3rd Wednesday 4pm SGT after now."""
    d = now
    for _ in range(70):
        if d.weekday() == 2:
            nth = math.ceil(d.day / 7)
            candidate = d.replace(hour=16, minute=0, second=0, microsecond=0)
            if nth in (1, 3) and candidate > now:
                return candidate.isoformat()
        d += timedelta(days=1)
    return None

def main():
    rows = fetch_rows()
    exercises = {}
    for row in rows:
        cat = CAT_MAP.get(str(row.get("vehicle_class", "")).strip())
        if not cat:
            continue
        key = (row["month"], str(row["bidding_no"]))
        ex = exercises.setdefault(key, {
            "close_date": close_date_guess(*key),
            "label": month_label(*key),
            "premiums": {}, "quota": {},
        })
        try:
            ex["premiums"][cat] = int(float(row["premium"]))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            ex["quota"][cat] = int(float(row["quota"]))
        except (KeyError, TypeError, ValueError):
            pass

    ordered = [exercises[k] for k in sorted(exercises, key=lambda k: (k[0], k[1]))]

    # PQP = 3-month moving average of QP per category (cats A–D)
    pqp = {}
    for cat in "ABCD":
        recent = [e["premiums"][cat] for e in ordered[-6:] if cat in e["premiums"]]
        pqp[cat] = round(sum(recent) / len(recent)) if recent else None

    now = datetime.now(SGT)
    out = {
        "updated": now.isoformat(timespec="seconds"),
        "next_close": next_close(now),
        "pqp": pqp,
        "exercises": ordered,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"Wrote {OUT} — {len(ordered)} exercises, latest: {ordered[-1]['label']}")

if __name__ == "__main__":
    main()
