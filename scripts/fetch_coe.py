#!/usr/bin/env python3
"""
coetoday.sg data pipeline.
Pulls the full LTA "COE Bidding Results" dataset from data.gov.sg,
rebuilds data/latest.json (full history + PQP + next close date).

IMPORTANT before first run:
  1. Go to https://data.gov.sg and search "COE bidding results" (LTA).
  2. Copy the dataset ID from the URL and set DATASET_ID below.
     (Same verify-the-ID step you did for resaleshdb.)
"""
import json, math, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "REPLACE_WITH_DATASET_ID"   # <-- verify on data.gov.sg
API = "https://api-production.data.gov.sg/v2/public/api/datasets/{}/poll-download"
OUT = Path(__file__).resolve().parent.parent / "data" / "latest.json"
SGT = timezone(timedelta(hours=8))

CAT_MAP = {
    "Category A": "A", "Category B": "B", "Category C": "C",
    "Category D": "D", "Category E": "E",
}

def fetch_rows():
    """data.gov.sg v2: poll-download returns a signed CSV/JSON URL for the full dataset."""
    req = urllib.request.Request(API.format(DATASET_ID), method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.load(r)
    url = meta["data"]["url"]
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read().decode("utf-8")
    # Dataset ships as CSV: month,bidding_no,vehicle_class,quota,bids_success,bids_received,premium
    import csv, io
    return list(csv.DictReader(io.StringIO(raw)))

def month_label(month_str, bidding_no):
    dt = datetime.strptime(month_str, "%Y-%m")
    return f"{dt.strftime('%b %Y')} · {'1st' if str(bidding_no)=='1' else '2nd'}"

def close_date_guess(month_str, bidding_no):
    """1st/3rd Wednesday of the month, 4pm SGT (good enough for charting)."""
    dt = datetime.strptime(month_str, "%Y-%m").replace(tzinfo=SGT)
    wednesdays = []
    d = dt
    while d.month == dt.month:
        if d.weekday() == 2:
            wednesdays.append(d)
        d += timedelta(days=1)
    idx = 0 if str(bidding_no) == "1" else 2
    w = wednesdays[min(idx, len(wednesdays)-1)]
    return w.replace(hour=16).date().isoformat()

def next_close(now):
    """Next 1st/3rd Wednesday 4pm SGT after now (LTA sometimes shifts — page also has manual override)."""
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
        cat = CAT_MAP.get(row["vehicle_class"])
        if not cat:
            continue
        key = (row["month"], str(row["bidding_no"]))
        ex = exercises.setdefault(key, {
            "close_date": close_date_guess(*key),
            "label": month_label(*key),
            "premiums": {}, "quota": {},
        })
        ex["premiums"][cat] = int(float(row["premium"]))
        try:
            ex["quota"][cat] = int(float(row["quota"]))
        except (KeyError, ValueError):
            pass

    ordered = [exercises[k] for k in sorted(exercises, key=lambda k: (k[0], k[1]))]

    # PQP = 3-month moving average of QP per category (cats A–D), rounded per LTA convention
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
