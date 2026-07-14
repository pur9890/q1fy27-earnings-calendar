#!/usr/bin/env python3
"""
Q1 FY27 Earnings Calendar for Indian listed companies.

Scrapes the MoneyControl results-calendar API and regenerates a simple,
self-contained HTML calendar (earnings_calendar.html) in this folder.

Run it any time to refresh the data:
    python update_calendar.py

Data source (discovered from moneycontrol.com/markets/earnings/results-calendar):
    https://api.moneycontrol.com/mcapi/v1/earnings/get-earnings-data
"""

import json
import ssl
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path
from html import escape

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Q1 FY27 = quarter Apr-Jun 2026; results are announced Jul-Sep 2026.
START_DATE = "2026-07-01"
END_DATE   = "2026-09-30"
RESULT_TYPE_LABEL = "Q1 FY26-27"          # what MoneyControl calls Q1 FY27
QUARTER_TITLE = "Q1 FY27"

OUT_HTML = Path(__file__).with_name("earnings_calendar.html")
OUT_JSON = Path(__file__).with_name("earnings_data.json")

API = ("https://api.moneycontrol.com/mcapi/v1/earnings/get-earnings-data"
       "?indexId=All&page=1&startDate={s}&endDate={e}"
       "&sector=&limit=5000&sortBy=marketcap&search=&seq=desc")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://www.moneycontrol.com/markets/earnings/results-calendar/",
    "Accept": "application/json",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def fetch():
    url = API.format(s=START_DATE, e=END_DATE)
    req = urllib.request.Request(url, headers=HEADERS)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
        payload = json.load(r)
    if not payload.get("success"):
        raise RuntimeError("API returned success=0: %r" % payload.get("data"))
    return payload["data"]


def parse_iso(datestr):
    """'16 Jul' -> date(2026, 7, 16), choosing the year inside the query range."""
    day_s, mon_s = datestr.split()
    mon = MONTHS[mon_s[:3].title()]
    day = int(day_s)
    lo = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    hi = datetime.strptime(END_DATE, "%Y-%m-%d").date()
    for yr in range(lo.year, hi.year + 1):
        try:
            d = date(yr, mon, day)
        except ValueError:
            continue
        if lo <= d <= hi:
            return d
    return date(lo.year, mon, day)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def month_grid(year, month, by_date):
    """Return HTML for one month's calendar grid (Mon-first weeks)."""
    first = date(year, month, 1)
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    n_days = (next_month - first).days
    lead = first.weekday()  # Mon=0

    cells = []
    for _ in range(lead):
        cells.append('<div class="cell empty"></div>')

    for dnum in range(1, n_days + 1):
        d = date(year, month, dnum)
        comps = by_date.get(d, [])
        wknd = " weekend" if d.weekday() >= 5 else ""
        head = (f'<div class="cell{wknd}{" has" if comps else ""}">'
                f'<div class="dnum">{dnum}'
                + (f'<span class="cnt">{len(comps)}</span>' if comps else "")
                + '</div>')
        if comps:
            items = []
            for c in comps:
                nm = escape(c["name"])
                url = escape(c["url"]) if c.get("url") else ""
                mc = c.get("mcap")
                mc_attr = f' title="Mkt cap: Rs {mc:,.0f} cr"' if mc else ""
                if url:
                    items.append(f'<a class="co" href="{url}" target="_blank" '
                                 f'rel="noopener"{mc_attr} data-name="{nm.lower()}">{nm}</a>')
                else:
                    items.append(f'<span class="co"{mc_attr} '
                                 f'data-name="{nm.lower()}">{nm}</span>')
            head += '<div class="colist">' + "".join(items) + '</div>'
        head += '</div>'
        cells.append(head)

    while len(cells) % 7:
        cells.append('<div class="cell empty"></div>')

    dows = "".join(f'<div class="dow">{d}</div>'
                   for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    label = first.strftime("%B %Y")
    total = sum(len(by_date.get(date(year, month, x + 1), []))
                for x in range(n_days))
    return (f'<section class="month">'
            f'<h2>{label} <span class="mtot">{total} companies</span></h2>'
            f'<div class="grid">{dows}{"".join(cells)}</div></section>')


def build_html(data):
    rows = data["list"]
    as_on = data.get("asOnDate", "")

    by_date = {}
    total = 0
    for r in rows:
        if RESULT_TYPE_LABEL not in (r.get("resultType") or ""):
            continue
        d = parse_iso(r["date"])
        by_date.setdefault(d, []).append({
            "name": r.get("stockName") or r.get("stockShortName") or "?",
            "url": r.get("stockUrl") or "",
            "mcap": r.get("marketCap"),
            "exch": r.get("exchange") or "",
        })
        total += 1

    # keep market-cap desc order within each day (API already sorted)
    months = sorted({(d.year, d.month) for d in by_date})
    grids = "".join(month_grid(y, m, by_date) for y, m in months)

    generated = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    first_day = min(by_date) if by_date else None
    last_day = max(by_date) if by_date else None
    span = (f"{first_day.strftime('%d %b')} &ndash; {last_day.strftime('%d %b %Y')}"
            if first_day else "&mdash;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{QUARTER_TITLE} Earnings Calendar &mdash; Indian Listed Companies</title>
<style>
  :root {{
    --bg:#0f1420; --panel:#151b2b; --cell:#1a2233; --cell2:#161d2c;
    --line:#28324a; --ink:#e7ecf5; --mut:#8b97ad; --accent:#4f8cff;
    --has:#1d2740; --wk:#141a28; --cobg:#222d45; --green:#26a269;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
  header {{ padding:22px 26px 14px; border-bottom:1px solid var(--line);
    position:sticky; top:0; background:var(--bg); z-index:5; }}
  h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.2px; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .sub b {{ color:var(--ink); }}
  .bar {{ display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
    margin-top:12px; }}
  .search {{ flex:1; min-width:220px; max-width:420px; }}
  .search input {{ width:100%; padding:9px 12px; border-radius:8px;
    border:1px solid var(--line); background:var(--panel); color:var(--ink);
    font-size:14px; outline:none; }}
  .search input:focus {{ border-color:var(--accent); }}
  .chip {{ font-size:12px; color:var(--mut); }}
  .chip b {{ color:var(--ink); }}
  main {{ padding:20px 26px 60px; }}
  .month {{ margin-bottom:34px; }}
  .month h2 {{ font-size:17px; margin:0 0 10px; font-weight:650; }}
  .mtot {{ font-size:12px; color:var(--mut); font-weight:500; margin-left:6px; }}
  .grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }}
  .dow {{ text-align:center; font-size:11px; color:var(--mut);
    text-transform:uppercase; letter-spacing:.6px; padding:2px 0 4px; }}
  .cell {{ min-height:96px; background:var(--cell2); border:1px solid var(--line);
    border-radius:9px; padding:6px 6px 7px; overflow:hidden; }}
  .cell.weekend {{ background:var(--wk); }}
  .cell.has {{ background:var(--has); }}
  .cell.empty {{ background:transparent; border:none; }}
  .dnum {{ font-size:12px; color:var(--mut); font-weight:600; margin-bottom:5px;
    display:flex; align-items:center; justify-content:space-between; }}
  .cnt {{ background:var(--accent); color:#fff; border-radius:20px;
    font-size:10.5px; padding:1px 7px; font-weight:700; }}
  .colist {{ display:flex; flex-direction:column; gap:3px; }}
  .co {{ display:block; font-size:11.5px; line-height:1.28; color:var(--ink);
    background:var(--cobg); border-radius:5px; padding:3px 6px; text-decoration:none;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  a.co:hover {{ background:var(--accent); color:#fff; }}
  .co.dim {{ opacity:.14; }}
  .cell.nomatch {{ opacity:.4; }}
  footer {{ padding:16px 26px 40px; color:var(--mut); font-size:12px;
    border-top:1px solid var(--line); }}
  footer a {{ color:var(--accent); }}
  @media (max-width:720px) {{
    .grid {{ gap:3px; }} .cell {{ min-height:70px; padding:4px; }}
    .co {{ font-size:10.5px; }} main,header {{ padding-left:12px; padding-right:12px; }}
  }}
</style>
</head>
<body>
<header>
  <h1>{QUARTER_TITLE} Earnings Calendar &mdash; Indian Listed Companies</h1>
  <div class="sub">Quarter <b>{QUARTER_TITLE}</b> (Apr&ndash;Jun 2026) results &middot;
     reporting window <b>{span}</b> &middot;
     <b>{total}</b> companies across <b>{len(by_date)}</b> dates</div>
  <div class="bar">
    <div class="search"><input id="q" type="search"
       placeholder="Search a company&hellip; (e.g. Reliance, TCS, Infosys)"></div>
    <div class="chip">Source: <b>MoneyControl</b> &middot; data as on <b>{escape(as_on)}</b></div>
    <div class="chip">Updated <b>{generated}</b></div>
  </div>
</header>
<main>
{grids}
</main>
<footer>
  Auto-generated from MoneyControl&rsquo;s
  <a href="https://www.moneycontrol.com/markets/earnings/results-calendar/" target="_blank" rel="noopener">Results Calendar</a>.
  Click any company to open its MoneyControl page. Dates &amp; companies update whenever you re-run <code>update_calendar.py</code>.
  Result timings are announced by companies and may change.
</footer>
<script>
  const q = document.getElementById('q');
  const cos = [...document.querySelectorAll('.co')];
  const cells = [...document.querySelectorAll('.cell.has')];
  q.addEventListener('input', () => {{
    const t = q.value.trim().toLowerCase();
    if (!t) {{ cos.forEach(c=>c.classList.remove('dim'));
              cells.forEach(c=>c.classList.remove('nomatch')); return; }}
    cos.forEach(c => c.classList.toggle('dim', !c.dataset.name.includes(t)));
    cells.forEach(cell => {{
      const any = [...cell.querySelectorAll('.co')].some(c=>c.dataset.name.includes(t));
      cell.classList.toggle('nomatch', !any);
    }});
  }});
</script>
</body>
</html>
"""


def main():
    try:
        data = fetch()
    except Exception as e:
        print("ERROR fetching data:", e, file=sys.stderr)
        return 1
    OUT_JSON.write_text(json.dumps(data, indent=1), encoding="utf-8")
    html = build_html(data)
    OUT_HTML.write_text(html, encoding="utf-8")
    n = sum(1 for r in data["list"] if RESULT_TYPE_LABEL in (r.get("resultType") or ""))
    print(f"OK  {n} companies  ->  {OUT_HTML.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
