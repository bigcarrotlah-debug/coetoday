#!/usr/bin/env python3
"""
coetoday.sg data pipeline (v3).
1. Pulls the full LTA "COE Bidding Results" dataset from data.gov.sg.
2. Rebuilds data/latest.json (full history + PQP + next close date).
3. Pre-renders the latest premiums into index.html so crawlers that don't
   run JavaScript still see real prices in the raw HTML.
"""
import json, math, re, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "d_69b3380ad7e51aff3a7dcc84eba52b8a"
API = "https://data.gov.sg/api/action/datastore_search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; coetoday.sg pipeline; +https://coetoday.sg)"}
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "latest.json"
PAGE = ROOT / "index.html"
SGT = timezone(timedelta(hours=8))

CAT_MAP = {
    "Category A": "A", "Category B": "B", "Category C": "C",
    "Category D": "D", "Category E": "E",
}
CAT_DESC = {
    "A": "Cars &le;1,600cc &amp; 130bhp",
    "B": "Cars &gt;1,600cc or 130bhp",
    "C": "Goods vehicles &amp; buses",
    "D": "Motorcycles",
    "E": "Open category",
}

def fetch_rows():
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
        raise RuntimeError("API returned zero records - check DATASET_ID")
    return rows

def month_label(month_str, bidding_no):
    dt = datetime.strptime(month_str, "%Y-%m")
    return f"{dt.strftime('%b %Y')} \u00b7 {'1st' if str(bidding_no)=='1' else '2nd'}"

def close_date_guess(month_str, bidding_no):
    dt = datetime.strptime(month_str, "%Y-%m").replace(tzinfo=SGT)
    wednesdays, d = [], dt
    while d.month == dt.month:
        if d.weekday() == 2:
            wednesdays.append(d)
        d += timedelta(days=1)
    idx = 0 if str(bidding_no) == "1" else 2
    return wednesdays[min(idx, len(wednesdays)-1)].date().isoformat()

def next_close(now):
    d = now
    for _ in range(70):
        if d.weekday() == 2:
            nth = math.ceil(d.day / 7)
            candidate = d.replace(hour=16, minute=0, second=0, microsecond=0)
            if nth in (1, 3) and candidate > now:
                return candidate.isoformat()
        d += timedelta(days=1)
    return None

def money(n):
    return "&mdash;" if n is None else "$" + f"{n:,}"

def render_page(ordered, pqp):
    """Bake the latest results into index.html between the marker comments."""
    if not PAGE.exists():
        print("index.html not found - skipping pre-render")
        return
    html = PAGE.read_text()
    latest = ordered[-1]
    prev = ordered[-2] if len(ordered) > 1 else {"premiums": {}}

    # --- board rows ---
    rows_html = []
    for c in "ABCDE":
        now, was = latest["premiums"].get(c), prev["premiums"].get(c)
        chip = '<span class="delta flat">no change</span>'
        if now is not None and was is not None and now != was:
            diff = now - was
            pct = f"{100*diff/was:+.1f}"
            if diff > 0:
                chip = f'<span class="delta up">&#9650; {money(diff)} ({pct}%)</span>'
            else:
                chip = f'<span class="delta down">&#9660; {money(-diff)} ({pct}%)</span>'
        quota = ""
        if latest.get("quota", {}).get(c):
            quota = f'<div class="quota">Quota {latest["quota"][c]:,}</div>'
        rows_html.append(
            f'<div class="row"><div class="cat-cell">'
            f'<div class="cat {"d" if c=="D" else ""}">{c}</div>'
            f'<div style="min-width:0"><div class="cname">Cat {c}</div>'
            f'<div class="cdesc">{CAT_DESC[c]}</div></div></div>'
            f'<div class="spark-cell" style="text-align:center"></div>'
            f'<div class="pwrap"><div class="premium">{money(now)}</div>{chip}{quota}</div></div>'
        )
    html = re.sub(r"<!--ROWS_START-->.*?<!--ROWS_END-->",
                  "<!--ROWS_START-->" + "".join(rows_html) + "<!--ROWS_END-->",
                  html, flags=re.S)

    # --- readable close date ---
    cd = datetime.fromisoformat(latest["close_date"])
    date_long = cd.strftime("%a %-d %b %Y")   # Wed 19 Aug 2026
    date_short = cd.strftime("%-d %b %Y")

    # --- as-of line ---
    html = re.sub(r"<!--ASOF_START-->.*?<!--ASOF_END-->",
                  f'<!--ASOF_START-->Latest results &mdash; bidding closed {date_long}<!--ASOF_END-->',
                  html, flags=re.S)

    # --- dated title ---
    html = re.sub(r"<!--TITLE_START-->.*?<!--TITLE_END-->",
                  f'<!--TITLE_START--><title>COE Prices Today ({date_short}) '
                  f'&mdash; Latest Bidding Results &amp; Trends | COETODAY.SG</title><!--TITLE_END-->',
                  html, flags=re.S)

    # --- auto-written summary prose (real content for crawlers and humans) ---
    def move(c):
        now, was = latest["premiums"].get(c), prev["premiums"].get(c)
        if now is None:
            return None
        if was is None or now == was:
            return f"Cat {c} was unchanged at {money(now)}"
        d = now - was
        verb = "rose" if d > 0 else "fell"
        return f"Cat {c} {verb} {money(abs(d))} ({100*d/was:+.1f}%) to {money(now)}"

    parts = [m for m in (move(c) for c in "ABCDE") if m]
    ups = sum(1 for c in "ABCDE"
              if latest["premiums"].get(c) is not None
              and prev["premiums"].get(c) is not None
              and latest["premiums"][c] > prev["premiums"][c])
    mood = ("Premiums rose across most categories." if ups >= 3
            else "Premiums eased across most categories." if ups <= 1
            else "Premiums were mixed across the categories.")

    pqp_bits = ", ".join(f"Cat {c} {money(pqp[c])}" for c in "ABCD" if pqp.get(c))
    summary = (
        f'<p><strong>COE results for {latest["label"]} (bidding closed {date_long}).</strong> '
        f'{mood} ' + "; ".join(parts) + '. '
        f'Figures are the Quota Premium at the close of the exercise, published by LTA.</p>'
        f'<p style="margin-top:10px">For owners renewing instead of bidding, the current Prevailing '
        f'Quota Premium (PQP) &mdash; the three-month moving average used for COE renewal &mdash; '
        f'stands at {pqp_bits}. The next bidding exercise opens in the following round; '
        f'this page updates within minutes of each close.</p>'
    )
    html = re.sub(r"<!--SUMMARY_START-->.*?<!--SUMMARY_END-->",
                  "<!--SUMMARY_START-->" + summary + "<!--SUMMARY_END-->",
                  html, flags=re.S)

    # --- JSON-LD freshness signal ---
    ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"COE Prices Today ({date_short})",
        "url": "https://coetoday.sg/",
        "datePublished": latest["close_date"],
        "dateModified": datetime.now(SGT).date().isoformat(),
        "inLanguage": "en-SG",
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "COETODAY.SG"},
    }
    html = re.sub(r"<!--LD_START-->.*?<!--LD_END-->",
                  '<!--LD_START--><script type="application/ld+json">'
                  + json.dumps(ld, ensure_ascii=False) + '</script><!--LD_END-->',
                  html, flags=re.S)

    # --- meta description with live numbers ---
    a, b = latest["premiums"].get("A"), latest["premiums"].get("B")
    desc = (f'Singapore COE results for {latest["label"]}: '
            f'Cat A {money(a)}, Cat B {money(b)}. '
            f'All five categories, price trends, PQP for COE renewal and the next bidding countdown.')
    desc = desc.replace("&mdash;", "n/a").replace("&amp;", "and")
    html = re.sub(r"<!--DESC_START-->.*?<!--DESC_END-->",
                  f'<!--DESC_START--><meta name="description" content="{desc}"><!--DESC_END-->',
                  html, flags=re.S)

    PAGE.write_text(html)
    print(f"Pre-rendered index.html for {latest['label']}")

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

    pqp = {}
    for cat in "ABCD":
        recent = [e["premiums"][cat] for e in ordered[-6:] if cat in e["premiums"]]
        pqp[cat] = round(sum(recent) / len(recent)) if recent else None

    now = datetime.now(SGT)
    OUT.write_text(json.dumps({
        "updated": now.isoformat(timespec="seconds"),
        "next_close": next_close(now),
        "pqp": pqp,
        "exercises": ordered,
    }, ensure_ascii=False, indent=1))
    print(f"Wrote {OUT} - {len(ordered)} exercises, latest: {ordered[-1]['label']}")

    render_page(ordered, pqp)

if __name__ == "__main__":
    main()
