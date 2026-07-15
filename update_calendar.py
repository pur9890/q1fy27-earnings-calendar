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
import time
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
TIMES_JSON = Path(__file__).with_name("release_times.json")  # approx times, built separately

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


def norm_name(s):
    """Normalize a company name for matching (must mirror build_release_times.py)."""
    import re as _re
    s = s.lower().replace("&", " and ")
    s = _re.sub(r"\b(ltd|limited|limite|the)\b", "", s)
    return _re.sub(r"[^a-z0-9]", "", s)


def load_times():
    try:
        return json.loads(TIMES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def fetch():
    """Fetch the calendar data, retrying on transient errors (MoneyControl
    occasionally returns 400/403/503 from datacenter IPs)."""
    url = API.format(s=START_DATE, e=END_DATE)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
                payload = json.load(r)
            if payload.get("success"):
                return payload["data"]
            last = RuntimeError("API returned success=0: %r" % payload.get("data"))
        except Exception as e:
            last = e
        if attempt < 4:
            time.sleep(4 * (attempt + 1))    # 4s, 8s, 12s, 16s backoff
    raise last


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
def month_grid(year, month, by_date, today=None):
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
        cls = "cell"
        if d.weekday() >= 5:
            cls += " weekend"
        if comps:
            cls += " has"
        is_today = today is not None and d == today
        if is_today:
            cls += " today"
        today_tag = '<span class="todaytag">TODAY</span>' if is_today else ""
        cnt_badge = f'<span class="cnt">{len(comps)}</span>' if comps else ""
        head = (f'<div class="{cls}"{" id=\"today\"" if is_today else ""}>'
                f'<div class="dnum"><span class="dl">{dnum}{today_tag}</span>{cnt_badge}</div>')
        if comps:
            items = []
            for c in comps:
                nm = escape(c["name"])
                url = escape(c["url"]) if c.get("url") else ""
                mc = c.get("mcap")
                tm = c.get("time")
                mc_bits = []
                if mc:
                    mc_bits.append(f"Mkt cap: Rs {mc:,.0f} cr")
                if tm:
                    mc_bits.append(f"Approx. time (from last quarter): {tm}")
                tip = escape(" · ".join(mc_bits))
                tip_attr = f' title="{tip}"' if tip else ""
                tspan = f' <span class="tm">({escape(tm)})</span>' if tm else ""
                inner = f'<span class="nm">{nm}</span>{tspan}'
                if url:
                    items.append(f'<a class="co" href="{url}" target="_blank" '
                                 f'rel="noopener"{tip_attr} data-name="{nm.lower()}">{inner}</a>')
                else:
                    items.append(f'<span class="co"{tip_attr} '
                                 f'data-name="{nm.lower()}">{inner}</span>')
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
    times = load_times()

    by_date = {}
    total = 0
    timed = 0
    for r in rows:
        if RESULT_TYPE_LABEL not in (r.get("resultType") or ""):
            continue
        d = parse_iso(r["date"])
        name = r.get("stockName") or r.get("stockShortName") or "?"
        tm = times.get(norm_name(name))
        if tm:
            timed += 1
        by_date.setdefault(d, []).append({
            "name": name,
            "url": r.get("stockUrl") or "",
            "mcap": r.get("marketCap"),
            "exch": r.get("exchange") or "",
            "time": tm,
        })
        total += 1

    # keep market-cap desc order within each day (API already sorted)
    today = datetime.now(IST).date()
    months = sorted({(d.year, d.month) for d in by_date})
    grids = "".join(month_grid(y, m, by_date, today) for y, m in months)

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
    --todaybg:#1b2b4d;
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
  .cell.today {{ border-color:var(--accent); box-shadow:0 0 0 2px var(--accent) inset,
    0 0 18px rgba(79,140,255,.40); background:var(--todaybg); }}
  .cell.today .dnum {{ color:var(--accent); }}
  .dl {{ display:inline-flex; align-items:center; gap:6px; }}
  .todaytag {{ background:var(--accent); color:#fff; font-size:8.5px; font-weight:800;
    padding:1px 6px; border-radius:20px; letter-spacing:.6px; }}
  .dnum {{ font-size:12px; color:var(--mut); font-weight:600; margin-bottom:5px;
    display:flex; align-items:center; justify-content:space-between; }}
  .cnt {{ background:var(--accent); color:#fff; border-radius:20px;
    font-size:10.5px; padding:1px 7px; font-weight:700; }}
  .colist {{ display:flex; flex-direction:column; gap:3px; }}
  .co {{ display:block; font-size:11.5px; line-height:1.28; color:var(--ink);
    background:var(--cobg); border-radius:5px; padding:3px 6px; text-decoration:none;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .co .tm {{ color:var(--mut); font-weight:600; font-size:10px; }}
  a.co:hover {{ background:var(--accent); color:#fff; }}
  a.co:hover .tm {{ color:#dbe4ff; }}
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
     <b>{total}</b> companies across <b>{len(by_date)}</b> dates &middot;
     times in <b>(brackets)</b> = approx., based on last quarter&rsquo;s filing</div>
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
  Times in brackets are <b>approximate</b> &mdash; they show when the company filed its <b>last quarter (Q4&nbsp;FY26)</b> results with the BSE,
  used here as a rough guide. Actual {QUARTER_TITLE} timing may differ, and some companies (mainly NSE-SME listings) have no time shown.
</footer>
<script>
  // Bring today's highlighted cell into view on load.
  (function () {{
    const t = document.getElementById('today');
    if (t) setTimeout(() => t.scrollIntoView({{block: 'center', behavior: 'smooth'}}), 150);
  }})();
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
