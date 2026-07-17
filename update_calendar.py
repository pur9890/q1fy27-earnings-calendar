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
EST_JSON = Path(__file__).with_name("estimates.json")        # broker estimates, built separately
OUT_EST_HTML = Path(__file__).with_name("estimates.html")

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


def est_norm(s):
    """Normalize a company name for estimate matching (strips parentheticals)."""
    import re as _re
    s = s.lower().replace("&", " and ")
    s = _re.sub(r"\(.*?\)", "", s)
    s = _re.sub(r"\b(ltd|limited|the)\b", "", s)
    return _re.sub(r"[^a-z0-9]", "", s)


def load_estimates():
    """Returns (lookup: norm_name -> slug, records: list). Empty if no file."""
    try:
        recs = json.loads(EST_JSON.read_text(encoding="utf-8"))["records"]
    except Exception:
        return {}, []
    lookup = {}
    for rec in recs:
        rec["slug"] = est_norm(rec["name"])
        for nm in [rec["name"]] + rec.get("aliases", []):
            lookup.setdefault(est_norm(nm), rec["slug"])
    return lookup, recs


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
def company_chip(c, dlabel=""):
    """One clickable company chip (links to its estimate, else MoneyControl)."""
    nm = escape(c["name"])
    url = escape(c["url"]) if c.get("url") else ""
    mc, tm = c.get("mcap"), c.get("time")
    bits = []
    if mc:
        bits.append(f"Mkt cap: Rs {mc:,.0f} cr")
    if tm:
        bits.append(f"Approx. time (from last quarter): {tm}")
    tip = escape(" · ".join(bits))
    dattr = f' data-d="{escape(dlabel)}"' if dlabel else ""
    tspan = f' <span class="tm">({escape(tm)})</span>' if tm else ""
    inner = f'<span class="nm">{nm}</span>{tspan}'
    slug = c.get("est")
    if slug:
        etip = escape((" · " if tip else "") + "Click: Q1FY27 estimates (broker avg)")
        return (f'<a class="co hasEst" href="estimates.html#{slug}" target="_blank" '
                f'rel="noopener" title="{tip}{etip}" data-name="{nm.lower()}"{dattr}>{inner}</a>')
    tip_attr = f' title="{tip}"' if tip else ""
    if url:
        return (f'<a class="co" href="{url}" target="_blank" rel="noopener"{tip_attr} '
                f'data-name="{nm.lower()}"{dattr}>{inner}</a>')
    return f'<span class="co"{tip_attr} data-name="{nm.lower()}"{dattr}>{inner}</span>'


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
        idattr = ' id="today"' if is_today else ""
        head = (f'<div class="{cls}"{idattr} data-date="{d.isoformat()}">'
                f'<div class="dnum"><span class="dl">{dnum}{today_tag}</span>{cnt_badge}</div>')
        if comps:
            dlabel = d.strftime("%d %b")
            head += ('<div class="colist">'
                     + "".join(company_chip(c, dlabel) for c in comps) + '</div>')
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


def today_banner(by_date, today):
    """Prominent pop-out: who reports today (or the next reporting day)."""
    todays = by_date.get(today, [])
    if todays:
        chips = "".join(company_chip(c) for c in todays)
        noun = "company" if len(todays) == 1 else "companies"
        return (f'<div class="banner" id="banner">'
                f'<div class="bhead"><span class="bdot"></span>'
                f'<b>Reporting today</b> &middot; {today.strftime("%a, %d %b %Y")} '
                f'&middot; {len(todays)} {noun}'
                f'<button class="bjump" onclick="jumpEl(document.getElementById(\'today\'))">'
                f'Jump to today &darr;</button></div>'
                f'<div class="blist">{chips}</div></div>')
    future = sorted(dd for dd in by_date if dd > today)
    if future:
        nd = future[0]
        n = len(by_date[nd])
        return (f'<div class="banner none" id="banner">'
                f'<span class="bdot mute"></span> No results scheduled for '
                f'<b>today ({today.strftime("%d %b")})</b>. Next reporting day: '
                f'<b>{nd.strftime("%a, %d %b")}</b> &middot; {n} companies '
                f'<button class="bjump" onclick="jumpDate(\'{nd.isoformat()}\')">Show &darr;</button></div>')
    return ""


def build_html(data):
    rows = data["list"]
    as_on = data.get("asOnDate", "")
    times = load_times()
    est_lookup, _est_recs = load_estimates()

    by_date = {}
    total = 0
    timed = 0
    for r in rows:
        if RESULT_TYPE_LABEL not in (r.get("resultType") or ""):
            continue
        d = parse_iso(r["date"])
        name = r.get("stockName") or r.get("stockShortName") or "?"
        short = r.get("stockShortName") or ""
        tm = times.get(norm_name(name))
        if tm:
            timed += 1
        # Match estimates on the full name first, then MoneyControl's short name
        # (a ticker/abbreviation like CDSL, TCS, HUL) which mirrors how brokers
        # label companies -- this catches short-form-vs-full-name mismatches.
        est_slug = est_lookup.get(est_norm(name))
        if not est_slug and short and est_norm(short) != est_norm(name):
            est_slug = est_lookup.get(est_norm(short))
        by_date.setdefault(d, []).append({
            "name": name,
            "url": r.get("stockUrl") or "",
            "mcap": r.get("marketCap"),
            "exch": r.get("exchange") or "",
            "time": tm,
            "est": est_slug,
        })
        total += 1

    # keep market-cap desc order within each day (API already sorted)
    today = datetime.now(IST).date()
    months = sorted({(d.year, d.month) for d in by_date})
    grids = "".join(month_grid(y, m, by_date, today) for y, m in months)
    banner = today_banner(by_date, today)

    generated = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    est_nav = ('<a class="estlink" href="estimates.html" target="_blank" '
               'rel="noopener">&#128202; Broker estimates &rarr;</a>' if est_lookup else "")
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
    --bg:#0e131f; --panel:#151b2b; --cell2:#161d2c;
    --line:#28324a; --ink:#e7ecf5; --mut:#8b97ad; --accent:#4f8cff;
    --has:#1a2438; --wk:#131926; --cobg:#232d47; --green:#2bb673;
    --todaybg:#17284a; --todayco:#2b4675; --amber:#f0a83c; --flash:#3a63c7;
  }}
  :root.light {{
    --bg:#f3f5fa; --panel:#ffffff; --cell2:#ffffff;
    --line:#e0e5ef; --ink:#16202f; --mut:#66707f; --accent:#2f6bff;
    --has:#eef4ff; --wk:#eff1f6; --cobg:#eef2f9; --green:#159060;
    --todaybg:#e2ecff; --todayco:#d3e2ff; --amber:#c67c12; --flash:#bcd2ff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
  header {{ padding:20px 26px 14px; border-bottom:1px solid var(--line);
    position:sticky; top:0; background:var(--bg); z-index:20; }}
  h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.2px; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .sub b {{ color:var(--ink); }}
  .bar {{ display:flex; flex-wrap:wrap; gap:10px 16px; align-items:center; margin-top:12px; }}
  .search {{ flex:1; min-width:220px; max-width:430px; position:relative; }}
  .search input {{ width:100%; padding:9px 12px; border-radius:8px;
    border:1px solid var(--line); background:var(--panel); color:var(--ink);
    font-size:14px; outline:none; }}
  .search input:focus {{ border-color:var(--accent); }}
  .sresults {{ display:none; position:absolute; left:0; right:0; top:calc(100% + 4px);
    background:var(--panel); border:1px solid var(--line); border-radius:9px;
    box-shadow:0 12px 30px rgba(0,0,0,.35); max-height:320px; overflow-y:auto; z-index:30; }}
  .sr {{ display:flex; justify-content:space-between; gap:10px; align-items:center;
    padding:8px 12px; font-size:13px; cursor:pointer; border-bottom:1px solid var(--line); }}
  .sr:last-child {{ border-bottom:none; }}
  .sr:hover, .sr.act {{ background:var(--has); }}
  .sr .srd {{ color:var(--accent); font-size:12px; font-weight:700; white-space:nowrap; }}
  .sr.none {{ color:var(--mut); cursor:default; }}
  .chip {{ font-size:12px; color:var(--mut); }}
  .chip b {{ color:var(--ink); }}
  a.estlink {{ font-size:12px; color:var(--accent); text-decoration:none; font-weight:700; }}
  a.estlink:hover {{ text-decoration:underline; }}
  .themebtn {{ margin-left:auto; background:var(--panel); border:1px solid var(--line);
    color:var(--ink); font-size:15px; line-height:1; padding:7px 10px; border-radius:8px;
    cursor:pointer; }}
  .themebtn:hover {{ border-color:var(--accent); }}
  /* today pop-out banner */
  .banner {{ margin:16px 26px 0; padding:12px 15px; border-radius:11px;
    background:var(--todaybg); border:1px solid var(--accent); }}
  .banner.none {{ background:var(--panel); border-color:var(--line); color:var(--mut);
    font-size:13.5px; }}
  .bhead {{ display:flex; align-items:center; gap:8px; font-size:14px; flex-wrap:wrap; }}
  .bdot {{ width:9px; height:9px; border-radius:50%; background:var(--amber);
    box-shadow:0 0 0 4px color-mix(in srgb,var(--amber) 30%,transparent); }}
  .bdot.mute {{ background:var(--mut); box-shadow:none; }}
  .bjump {{ background:var(--accent); color:#fff; border:none; border-radius:7px;
    font-size:12px; font-weight:700; padding:4px 10px; cursor:pointer; }}
  .bjump:hover {{ filter:brightness(1.08); }}
  .blist {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }}
  .blist .co {{ display:inline-block; }}
  main {{ padding:18px 26px 60px; }}
  .month {{ margin-bottom:34px; }}
  .month h2 {{ font-size:17px; margin:0 0 10px; font-weight:650; }}
  .mtot {{ font-size:12px; color:var(--mut); font-weight:500; margin-left:6px; }}
  .grid {{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }}
  .dow {{ text-align:center; font-size:11px; color:var(--mut);
    text-transform:uppercase; letter-spacing:.6px; padding:2px 0 4px; }}
  .cell {{ min-height:96px; background:var(--cell2); border:1px solid var(--line);
    border-radius:9px; padding:6px 6px 7px; overflow:hidden; scroll-margin-top:130px; }}
  .cell.weekend {{ background:var(--wk); }}
  .cell.has {{ background:var(--has); }}
  .cell.empty {{ background:transparent; border:none; }}
  .cell.today {{ border-color:var(--accent); border-width:2px; padding:5px 5px 6px;
    box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent);
    background:var(--todaybg); }}
  .cell.today .dnum {{ color:var(--accent); }}
  .cell.today .co {{ background:var(--todayco); }}
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
  a.co.hasEst {{ box-shadow:inset 3px 0 0 var(--green); }}
  a.co.hasEst:hover {{ background:var(--green); box-shadow:none; }}
  @keyframes coflash {{ 0%,55% {{ background:var(--flash); color:#fff; }} 100% {{}} }}
  .co.flash {{ animation:coflash 1.7s ease-out; }}
  @media (prefers-reduced-motion: reduce) {{ .co.flash {{ animation:none; outline:2px solid var(--accent); }} }}
  footer {{ padding:16px 26px 40px; color:var(--mut); font-size:12px;
    border-top:1px solid var(--line); }}
  footer a {{ color:var(--accent); }}
  @media (max-width:720px) {{
    .grid {{ gap:3px; }} .cell {{ min-height:70px; padding:4px; }}
    .co {{ font-size:10.5px; }}
    main,header {{ padding-left:12px; padding-right:12px; }} .banner {{ margin:14px 12px 0; }}
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
    <div class="search">
      <input id="q" type="search" autocomplete="off"
         placeholder="Search a company&hellip; jumps to its result date">
      <div id="sresults" class="sresults"></div>
    </div>
    <div class="chip">Source: <b>MoneyControl</b> &middot; data as on <b>{escape(as_on)}</b></div>
    <div class="chip">Updated <b>{generated}</b></div>
    {est_nav}
    <button id="themeBtn" class="themebtn" title="Switch light / dark" aria-label="Switch theme">&#9790;</button>
  </div>
</header>
{banner}
<main id="cal">
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
  // ---- light / dark theme (remembers your choice) ----
  const root = document.documentElement, tb = document.getElementById('themeBtn');
  function applyTheme(t) {{
    root.classList.toggle('light', t === 'light');
    tb.innerHTML = t === 'light' ? '&#9728;' : '&#9790;';   // sun / moon
  }}
  applyTheme(localStorage.getItem('cal-theme') || 'dark');
  tb.addEventListener('click', () => {{
    const t = root.classList.contains('light') ? 'dark' : 'light';
    localStorage.setItem('cal-theme', t); applyTheme(t);
  }});

  // ---- jump helpers ----
  function jumpEl(el) {{
    if (!el) return;
    (el.closest('.cell') || el).scrollIntoView({{block: 'center', behavior: 'smooth'}});
    if (el.classList.contains('co')) {{
      el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
    }}
  }}
  function jumpDate(iso) {{ jumpEl(document.querySelector('.cell[data-date="' + iso + '"]')); }}

  // bring today into view on load
  (function () {{
    const t = document.getElementById('today');
    if (t) setTimeout(() => t.scrollIntoView({{block: 'center', behavior: 'smooth'}}), 200);
  }})();

  // ---- search that jumps straight to the result date ----
  const q = document.getElementById('q'), box = document.getElementById('sresults');
  const idx = [...document.querySelectorAll('#cal .co')].map(el => ({{
    name: el.dataset.name || '', label: el.querySelector('.nm').textContent,
    d: el.dataset.d || '', el
  }}));
  let hits = [], act = -1;
  function render() {{
    if (!hits.length) {{ box.innerHTML = '<div class="sr none">No matching company</div>'; box.style.display = 'block'; return; }}
    box.innerHTML = hits.map((o, i) =>
      '<div class="sr' + (i === act ? ' act' : '') + '" data-i="' + i + '">' +
      '<span>' + o.label + '</span><span class="srd">' + o.d + '</span></div>').join('');
    box.style.display = 'block';
  }}
  q.addEventListener('input', () => {{
    const t = q.value.trim().toLowerCase();
    if (!t) {{ box.style.display = 'none'; hits = []; return; }}
    hits = idx.filter(o => o.name.includes(t)).slice(0, 12); act = -1; render();
  }});
  q.addEventListener('keydown', e => {{
    if (e.key === 'ArrowDown') {{ e.preventDefault(); act = Math.min(act + 1, hits.length - 1); render(); }}
    else if (e.key === 'ArrowUp') {{ e.preventDefault(); act = Math.max(act - 1, 0); render(); }}
    else if (e.key === 'Enter' && hits.length) {{ e.preventDefault(); pick(act < 0 ? 0 : act); }}
    else if (e.key === 'Escape') {{ box.style.display = 'none'; }}
  }});
  function pick(i) {{ const o = hits[i]; if (!o) return; box.style.display = 'none'; q.blur(); jumpEl(o.el); }}
  box.addEventListener('mousedown', e => {{ const r = e.target.closest('.sr'); if (r && r.dataset.i) pick(+r.dataset.i); }});
  document.addEventListener('click', e => {{ if (!e.target.closest('.search')) box.style.display = 'none'; }});
</script>
</body>
</html>
"""


def _cr(v):
    """Rs million -> Rs crore, formatted with thousands separators."""
    return "&mdash;" if v is None else f"{round(v / 10):,}"


def _pct(v):
    return "&mdash;" if v is None else f"{v * 100:.1f}%"


def _metric(label, m, kind="cr"):
    """One metric: average, plus the low-high range across brokers when 2+ cover it."""
    fmt = _cr if kind == "cr" else _pct
    if not m:
        return f'<div class="m"><span class="ml">{label}</span><span class="mv">&mdash;</span></div>'
    bar = ""
    if m.get("min") is not None and m.get("max") is not None:
        lo, hi = m["min"], m["max"]
        spread = hi - lo
        pos = ((m["avg"] - lo) / spread * 100) if spread else 50
        pos = max(0.0, min(100.0, pos))
        tip = escape(f"Low {fmt(lo).replace('&mdash;','-')} ({m.get('minBy','')}) "
                     f"/ High {fmt(hi).replace('&mdash;','-')} ({m.get('maxBy','')})")
        bar = (f'<span class="track" title="{tip}"><i style="left:{pos:.0f}%"></i></span>'
               f'<span class="rg">{fmt(lo)} &ndash; {fmt(hi)}</span>')
    return (f'<div class="m"><span class="ml">{label}</span>'
            f'<span class="mv">{fmt(m["avg"])}</span>{bar}</div>')


def build_estimates_html(records):
    """Standalone estimates page (all covered companies), opened in a new tab."""
    generated = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    recs = sorted(records, key=lambda r: r["name"].lower())
    ranged = sum(1 for r in recs if (r.get("rev") or {}).get("min") is not None)
    cards = []
    for rec in recs:
        nm = escape(rec["name"])
        n = rec.get("n") or 0
        foot = (f"Average of {n} brokers &middot; range = low&ndash;high" if n > 1
                else "1 broker &middot; no range")
        cards.append(f"""<div class="ecard" id="{rec['slug']}">
  <div class="ename">{nm}</div>
  <div class="metrics">
    {_metric('Revenue', rec.get('rev'))}
    {_metric('EBITDA', rec.get('ebitda'))}
    {_metric('EBITDA margin', rec.get('margin'), 'pct')}
    {_metric('PAT', rec.get('pat'))}
  </div>
  <div class="efoot">{foot} &middot; Q1&nbsp;FY27E</div>
</div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q1 FY27 Broker Estimates &mdash; Indian Listed Companies</title>
<style>
  :root {{ --bg:#0e131f; --panel:#151b2b; --card:#161d2c; --line:#28324a;
    --ink:#e7ecf5; --mut:#8b97ad; --accent:#4f8cff; --green:#2bb673; }}
  :root.light {{ --bg:#f3f5fa; --panel:#ffffff; --card:#ffffff; --line:#e0e5ef;
    --ink:#16202f; --mut:#66707f; --accent:#2f6bff; --green:#159060; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
  header {{ padding:22px 26px 14px; border-bottom:1px solid var(--line);
    position:sticky; top:0; background:var(--bg); z-index:5; }}
  .toprow {{ display:flex; align-items:center; justify-content:space-between; gap:10px; }}
  .themebtn {{ background:var(--panel); border:1px solid var(--line); color:var(--ink);
    font-size:15px; line-height:1; padding:7px 10px; border-radius:8px; cursor:pointer; }}
  .themebtn:hover {{ border-color:var(--accent); }}
  h1 {{ margin:0 0 4px; font-size:21px; }}
  .sub {{ color:var(--mut); font-size:13px; }}
  .sub b {{ color:var(--ink); }}
  a.back {{ color:var(--accent); text-decoration:none; font-size:13px; font-weight:600; }}
  a.back:hover {{ text-decoration:underline; }}
  .bar {{ display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center; margin-top:12px; }}
  .search {{ flex:1; min-width:220px; max-width:420px; }}
  .search input {{ width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--line);
    background:var(--panel); color:var(--ink); font-size:14px; outline:none; }}
  .search input:focus {{ border-color:var(--accent); }}
  main {{ padding:20px 26px 60px; display:grid; align-items:start;
    grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; }}
  .ecard {{ background:var(--card); border:1px solid var(--line); border-radius:11px;
    padding:13px 14px; scroll-margin-top:120px; }}
  .ecard.nomatch {{ display:none; }}
  .ename {{ font-size:14.5px; font-weight:650; margin-bottom:10px; text-wrap:balance; }}
  .metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:9px 12px; }}
  .m {{ display:flex; flex-direction:column; gap:1px; }}
  .ml {{ font-size:10.5px; color:var(--mut); text-transform:uppercase; letter-spacing:.4px; }}
  .mv {{ font-size:16px; font-weight:700; font-variant-numeric:tabular-nums; }}
  .track {{ display:block; height:3px; background:var(--line); border-radius:2px;
    margin:6px 0 4px; position:relative; }}
  .track i {{ position:absolute; top:-2px; width:3px; height:7px; background:var(--accent);
    border-radius:1px; }}
  .rg {{ font-size:11px; color:var(--mut); font-variant-numeric:tabular-nums; }}
  .efoot {{ margin-top:11px; padding-top:9px; border-top:1px solid var(--line);
    font-size:11px; color:var(--mut); }}
  .ecard:target {{ border-color:var(--accent);
    box-shadow:0 0 0 2px var(--accent) inset, 0 0 22px rgba(79,140,255,.45); }}
  footer {{ padding:16px 26px 44px; color:var(--mut); font-size:12px; border-top:1px solid var(--line); }}
  @media (max-width:640px) {{ main {{ padding:14px 12px 50px; }} header {{ padding:16px 12px 12px; }} }}
</style>
</head>
<body>
<header>
  <div class="toprow">
    <a class="back" href="index.html">&larr; Back to calendar</a>
    <button id="themeBtn" class="themebtn" title="Switch light / dark" aria-label="Switch theme">&#9790;</button>
  </div>
  <h1 style="margin-top:8px">Q1&nbsp;FY27 Broker Estimates &mdash; Averages</h1>
  <div class="sub">Consensus for <b>Apr&ndash;Jun 2026</b> (reported Jul&ndash;Aug) &middot;
     average of <b>MOSL / Kotak / Ambit / Spark / I-Sec</b> &middot; <b>{len(recs)}</b> companies.
     All figures in <b>&#8377; crore</b> (EBITDA margin in %).<br>
     The big number is the <b>average</b>; below it the <b>low&ndash;high</b> across brokers,
     with the tick showing where the average sits ({ranged} companies have 2+ brokers;
     the rest are covered by one broker, so no range).</div>
  <div class="bar">
    <div class="search"><input id="q" type="search"
       placeholder="Search a company&hellip; (e.g. Reliance, Infosys, Bajaj)"></div>
  </div>
</header>
<main id="grid">
{"".join(cards)}
</main>
<footer>
  Estimates are broker previews (averaged), <b>not actuals</b>. Revenue = Revenue/NII, EBITDA = EBITDA/PPOP,
  PAT = net profit, as reported by MOSL, Kotak (KIE) and Ambit for Q1&nbsp;FY27E. Updated {generated}.
  Open a company from the calendar to jump straight to its card.
</footer>
<script>
  // light / dark theme, shared with the calendar via the same saved preference
  const root = document.documentElement, tb = document.getElementById('themeBtn');
  function applyTheme(t) {{
    root.classList.toggle('light', t === 'light');
    tb.innerHTML = t === 'light' ? '&#9728;' : '&#9790;';
  }}
  applyTheme(localStorage.getItem('cal-theme') || 'dark');
  tb.addEventListener('click', () => {{
    const t = root.classList.contains('light') ? 'dark' : 'light';
    localStorage.setItem('cal-theme', t); applyTheme(t);
  }});

  const q = document.getElementById('q');
  const cards = [...document.querySelectorAll('.ecard')];
  q.addEventListener('input', () => {{
    const t = q.value.trim().toLowerCase();
    cards.forEach(c => c.classList.toggle('nomatch',
      t && !c.querySelector('.ename').textContent.toLowerCase().includes(t)));
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
    # estimates tab (all covered companies), if the estimates file is present
    _lookup, est_recs = load_estimates()
    if est_recs:
        OUT_EST_HTML.write_text(build_estimates_html(est_recs), encoding="utf-8")
    n = sum(1 for r in data["list"] if RESULT_TYPE_LABEL in (r.get("resultType") or ""))
    print(f"OK  {n} companies  ->  {OUT_HTML.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
