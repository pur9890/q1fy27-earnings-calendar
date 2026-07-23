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
TKR_JSON = Path(__file__).with_name("tickers.json")          # NSE tickers for TradingView links
ACT_JSON = Path(__file__).with_name("actuals.json")          # reported actuals (Screener)
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


def tkr_norm(s):
    """Normalize a name for ticker lookup (must mirror build_tickers.py)."""
    import re as _re
    s = s.lower().replace("&", " and ")
    s = _re.sub(r"\(.*?\)", " ", s)
    s = _re.sub(r"\b(limited|ltd|the)\b", " ", s)
    return _re.sub(r"[^a-z0-9]", "", s)


def load_tickers():
    try:
        return {k: v for k, v in json.loads(TKR_JSON.read_text(encoding="utf-8")).items() if v}
    except Exception:
        return {}


def load_actuals():
    try:
        return json.loads(ACT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tv_url(ticker):
    """TradingView chart link for an NSE symbol."""
    from urllib.parse import quote
    return "https://www.tradingview.com/chart/?symbol=" + quote(f"NSE:{ticker}", safe="")


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
    """One clickable company chip (links to its estimate, else MoneyControl),
    with a watchlist star. The star's key matches the estimate slug when the
    company has one, so a star set here also shows on the estimates page."""
    nm = escape(c["name"])
    url = escape(c["url"]) if c.get("url") else ""
    mc, tm = c.get("mcap"), c.get("time")
    slug = c.get("est")
    key = slug if slug else "nm:" + est_norm(c["name"])
    bits = []
    if mc:
        bits.append(f"Mkt cap: Rs {mc:,.0f} cr")
    if tm:
        bits.append(f"Approx. time (from last quarter): {tm}")
    tkr = c.get("tkr")
    tip = escape(" · ".join(bits))
    dattr = f' data-d="{escape(dlabel)}"' if dlabel else ""
    kattr = f' data-key="{escape(key)}"'
    star = '<span class="star" title="Add to my watchlist" aria-hidden="true">&#9734;</span>'
    tspan = f' <span class="tm">({escape(tm)})</span>' if tm else ""

    # the name links to the estimate when we have one, else the chart, else MoneyControl
    if slug:
        href, cls, what = f"estimates.html#{slug}", "co hasEst", "Q1FY27 estimates (broker avg)"
    elif tkr:
        href, cls, what = tv_url(tkr), "co", f"TradingView chart (NSE:{tkr})"
    elif url:
        href, cls, what = url, "co", "MoneyControl page"
    else:
        href, cls, what = "", "co", ""
    ntip = escape((tip + " · " if tip else "") + (f"Click: {what}" if what else ""))
    label = f'<span class="nm">{nm}</span>{tspan}'
    namelink = (f'<a class="nmlink" href="{href}" target="_blank" rel="noopener" '
                f'title="{ntip}">{label}</a>' if href else
                f'<span class="nmlink" title="{tip}">{label}</span>')
    # separate small chart icon -> TradingView
    chart = (f'<a class="tv" href="{tv_url(tkr)}" target="_blank" rel="noopener" '
             f'title="TradingView chart (NSE:{tkr})" aria-label="TradingView chart">'
             f'<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" '
             f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
             f'<path d="M2 11.5l4-4 3 3 5-5.5"/></svg></a>') if tkr else ""
    return (f'<div class="{cls}" data-name="{nm.lower()}"{dattr}{kattr}>'
            f'{star}{namelink}{chart}</div>')


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


def _time_mins(tm):
    """'1:10 PM' -> minutes past midnight; None if unparseable/empty."""
    import re as _re
    m = _re.match(r"(\d+):(\d+)\s*(AM|PM)", tm or "", _re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h * 60 + mi


# NSE market hours: 9:15 AM (555) to 3:30 PM (930)
MKT_OPEN, MKT_CLOSE = 555, 930


def today_banner(by_date, today):
    """Prominent pop-out: today's reporters, grouped by market session, collapsible."""
    todays = by_date.get(today, [])
    if todays:
        groups = {"live": [], "aft": [], "pre": [], "tbc": []}
        for c in todays:
            m = _time_mins(c.get("time"))
            if m is None:
                groups["tbc"].append((10 ** 9, c))
            elif m < MKT_OPEN:
                groups["pre"].append((m, c))
            elif m <= MKT_CLOSE:
                groups["live"].append((m, c))
            else:
                groups["aft"].append((m, c))
        for g in ("live", "aft", "pre"):
            groups[g].sort(key=lambda x: x[0])

        def chips(items):
            return "".join(company_chip(c) for _, c in items)

        def grp(label, rng, dotvar, items, live=False, none_msg=None):
            if not items and not none_msg:
                return ""
            body = (f'<div class="blist">{chips(items)}</div>' if items
                    else f'<div class="bnone">{none_msg}</div>')
            return (f'<div class="bgrp{" live" if live else ""}"><div class="bgrp-h">'
                    f'<span class="gdot" style="background:var({dotvar})"></span>{label}'
                    f'<span class="cnt">{rng} &middot; {len(items)}</span></div>{body}</div>')

        body = (grp("During market hours &middot; live reaction", "9:15 AM&ndash;3:30 PM",
                    "--amber", groups["live"], live=True,
                    none_msg="No results during market hours today.")
                + grp("After market close", "after 3:30 PM", "--accent", groups["aft"])
                + grp("Pre-market", "before 9:15 AM", "--mut", groups["pre"])
                + grp("Time to be confirmed", "no last-quarter time on record",
                      "--mut", groups["tbc"]))

        pills = ('<span class="bpills">'
                 f'<span class="bpill live">{len(groups["live"])} live</span>'
                 f'<span class="bpill aft">{len(groups["aft"])} after close</span>'
                 + (f'<span class="bpill tbc">{len(groups["tbc"])} to confirm</span>'
                    if groups["tbc"] else "")
                 + '</span>')
        noun = "company" if len(todays) == 1 else "companies"
        return (f'<div class="banner" id="banner">'
                f'<div class="bhead" onclick="toggleBanner(event)">'
                f'<span class="bchev"><svg width="13" height="13" viewBox="0 0 16 16" fill="none" '
                f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                f'<path d="M6 4l4 4-4 4"/></svg></span>'
                f'<span class="bdot"></span>'
                f'<b>Reporting today</b> &middot; {today.strftime("%a, %d %b %Y")} '
                f'&middot; {len(todays)} {noun}{pills}'
                f'<button class="bjump" onclick="event.stopPropagation();'
                f'jumpEl(document.getElementById(\'today\'))">Jump to today &darr;</button></div>'
                f'<div class="bbody">{body}</div></div>')
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
    tickers = load_tickers()

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
            "tkr": tickers.get(tkr_norm(name)) or (tickers.get(tkr_norm(short)) if short else None),
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
    --time:#d7b26a;
  }}
  :root.light {{
    --bg:#f3f5fa; --panel:#ffffff; --cell2:#ffffff;
    --line:#e0e5ef; --ink:#16202f; --mut:#66707f; --accent:#2f6bff;
    --has:#eef4ff; --wk:#eff1f6; --cobg:#eef2f9; --green:#159060;
    --todaybg:#e2ecff; --todayco:#d3e2ff; --amber:#c67c12; --flash:#bcd2ff;
    --time:#9a6b1a;
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
  .bhead {{ display:flex; align-items:center; gap:8px; font-size:14px; flex-wrap:wrap;
    cursor:pointer; user-select:none; }}
  .bchev {{ display:flex; color:var(--mut); transition:transform .18s; }}
  .banner:not(.collapsed) .bchev {{ transform:rotate(90deg); }}
  .bdot {{ width:9px; height:9px; border-radius:50%; background:var(--amber);
    box-shadow:0 0 0 4px color-mix(in srgb,var(--amber) 30%,transparent); }}
  .bdot.mute {{ background:var(--mut); box-shadow:none; }}
  .bpills {{ display:flex; gap:6px; flex-wrap:wrap; margin-left:auto; }}
  .bpill {{ font-size:11px; font-weight:700; padding:2px 9px; border-radius:20px; }}
  .bpill.live {{ background:var(--amber); color:#241a00; }}
  .bpill.aft {{ background:color-mix(in srgb,var(--accent) 22%,transparent); color:var(--accent); }}
  .bpill.tbc {{ background:color-mix(in srgb,var(--mut) 26%,transparent); color:var(--mut); }}
  .bjump {{ background:var(--accent); color:#fff; border:none; border-radius:7px;
    font-size:12px; font-weight:700; padding:4px 10px; cursor:pointer; }}
  .bjump:hover {{ filter:brightness(1.08); }}
  .bbody {{ margin-top:2px; }}
  .banner.collapsed .bbody {{ display:none; }}
  .bgrp {{ margin-top:13px; }}
  .bgrp.live {{ border-left:3px solid var(--amber); padding-left:11px; }}
  .bgrp-h {{ display:flex; align-items:center; gap:8px; font-size:12.5px; font-weight:650;
    margin-bottom:8px; }}
  .bgrp-h .gdot {{ width:10px; height:10px; border-radius:50%; flex:none; }}
  .bgrp-h .cnt {{ margin-left:auto; font-size:11.5px; font-weight:700; color:var(--time);
    background:none; padding:0; border-radius:0; }}
  .bnone {{ font-size:12.5px; color:var(--mut); }}
  .blist {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .blist .co {{ display:inline-flex; max-width:100%; }}
  .blist .nmlink {{ flex:0 1 auto; }}
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
  .co {{ display:flex; align-items:center; gap:2px; font-size:11.5px; line-height:1.28;
    color:var(--ink); background:var(--cobg); border-radius:5px; padding:3px 5px;
    overflow:hidden; }}
  .co .nmlink {{ flex:1; min-width:0; color:inherit; text-decoration:none;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .co .tm {{ color:var(--time); font-weight:700; font-size:10px; }}
  .co:hover {{ background:var(--accent); color:#fff; }}
  .co:hover .tm {{ color:#dbe4ff; }}
  .co.hasEst {{ box-shadow:inset 3px 0 0 var(--green); }}
  .co.hasEst:hover {{ background:var(--green); box-shadow:none; }}
  /* TradingView chart icon */
  .tv {{ flex:none; display:flex; align-items:center; color:var(--mut); opacity:.55;
    padding:2px; border-radius:4px; }}
  .tv:hover {{ opacity:1; color:var(--ink); background:rgba(127,127,127,.25); }}
  .co:hover .tv {{ color:#fff; opacity:.85; }}
  .co:hover .tv:hover {{ opacity:1; background:rgba(255,255,255,.25); }}
  /* watchlist star (padded for an easy tap target that won't trigger the link) */
  .star {{ cursor:pointer; color:var(--mut); font-size:14px; line-height:1;
    padding:3px 5px 3px 2px; margin:-3px 0 -3px -3px; opacity:.5; }}
  .star:hover {{ opacity:1; color:var(--amber); }}
  .co.starred .star {{ color:var(--amber); opacity:1; }}
  a.co:hover .star {{ color:#fff; }}
  a.co.starred:hover .star {{ color:#fff; }}
  /* watchlist-only view: hide everything not starred */
  body.wlonly .co:not(.starred) {{ display:none; }}
  body.wlonly .cell.has:not(.hasstar) .colist {{ display:none; }}
  .wlbtn {{ background:var(--panel); border:1px solid var(--line); color:var(--ink);
    font-size:12px; font-weight:700; padding:7px 11px; border-radius:8px; cursor:pointer; }}
  .wlbtn:hover {{ border-color:var(--amber); }}
  .wlbtn.on {{ background:var(--amber); border-color:var(--amber); color:#241a00; }}
  .wlhint {{ display:none; margin:14px 26px 0; padding:12px 15px; border-radius:10px;
    background:var(--panel); border:1px dashed var(--line); color:var(--mut); font-size:13px; }}
  body.wlonly .wlhint.show {{ display:block; }}
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
    <button id="wlBtn" class="wlbtn" title="Show only my starred companies">&#9734; Watchlist</button>
    <button id="themeBtn" class="themebtn" title="Switch light / dark" aria-label="Switch theme">&#9790;</button>
  </div>
</header>
{banner}
<div id="wlHint" class="wlhint">Your watchlist is empty. Click the <b>&#9734;</b> star on any
  company to add it &mdash; it&rsquo;s saved in your browser, just for you.</div>
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

  // ---- collapsible "reporting today" banner (remembers your choice) ----
  function toggleBanner(e) {{
    if (e && e.target.closest('.bjump')) return;
    const b = document.getElementById('banner'); if (!b) return;
    const col = b.classList.toggle('collapsed');
    localStorage.setItem('cal-banner-collapsed', col ? '1' : '0');
  }}
  (function () {{
    const b = document.getElementById('banner');
    if (b && localStorage.getItem('cal-banner-collapsed') === '1') b.classList.add('collapsed');
  }})();

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

  // ---- watchlist (saved in your browser only; others still see everything) ----
  const WL_KEY = 'cal-watchlist';
  let wl = new Set();
  try {{ wl = new Set(JSON.parse(localStorage.getItem(WL_KEY) || '[]')); }} catch (e) {{}}
  const wlBtn = document.getElementById('wlBtn'), wlHint = document.getElementById('wlHint');
  function paintStars() {{
    document.querySelectorAll('.co[data-key]').forEach(el => {{
      const on = wl.has(el.dataset.key);
      el.classList.toggle('starred', on);
      const s = el.querySelector('.star'); if (s) s.innerHTML = on ? '&#9733;' : '&#9734;';
    }});
    document.querySelectorAll('#cal .cell').forEach(c =>
      c.classList.toggle('hasstar', !!c.querySelector('.co.starred')));
    wlBtn.innerHTML = (wl.size ? '&#9733;' : '&#9734;') + ' Watchlist' + (wl.size ? ' (' + wl.size + ')' : '');
  }}
  function updateHint() {{ wlHint.classList.toggle('show', wl.size === 0); }}
  document.addEventListener('click', e => {{
    const s = e.target.closest('.star'); if (!s) return;
    const chip = s.closest('.co'); if (!chip) return;
    e.preventDefault(); e.stopPropagation();
    const k = chip.dataset.key; wl.has(k) ? wl.delete(k) : wl.add(k);
    localStorage.setItem(WL_KEY, JSON.stringify([...wl])); paintStars(); updateHint();
  }}, true);
  wlBtn.addEventListener('click', () => {{
    const on = document.body.classList.toggle('wlonly');
    wlBtn.classList.toggle('on', on); updateHint();
  }});
  paintStars();
</script>
</body>
</html>
"""


def _cr(v):
    """Rs million -> Rs crore, formatted with thousands separators."""
    return "&mdash;" if v is None else f"{round(v / 10):,}"


def _pct(v):
    return "&mdash;" if v is None else f"{v * 100:.1f}%"


def _rng_tip(m):
    if not m or m.get("min") is None:
        return ""
    return escape(f"{m['n']}-broker range: {round(m['min']/10):,} ({m.get('minBy','')}) "
                  f"to {round(m['max']/10):,} ({m.get('maxBy','')})")


def _range_panel(m, kind):
    """The click-to-open detail: low/avg/high bar + every broker's number."""
    if not m or m.get("min") is None or len(m.get("brokers") or []) < 2:
        return ""
    fmt = (lambda v: f"{v*100:.1f}%") if kind == "pct" else (lambda v: f"{round(v/10):,}")
    lo, hi, avg = m["min"], m["max"], m["avg"]
    spread = hi - lo
    pos = max(0.0, min(100.0, (avg - lo) / spread * 100 if spread else 50))
    chips = []
    for name, val in m["brokers"]:
        cls = " lo" if val == lo else (" hi" if val == hi else "")
        chips.append(f'<span class="bk{cls}"><b>{escape(name)}</b> {fmt(val)}</span>')
    return (f'<div class="panel">'
            f'<div class="prng"><span>Low &middot; {escape(m.get("minBy",""))}</span>'
            f'<span>Avg &middot; {m["n"]} brokers</span>'
            f'<span>High &middot; {escape(m.get("maxBy",""))}</span></div>'
            f'<div class="prng v"><span>{fmt(lo)}</span><span>{fmt(avg)}</span><span>{fmt(hi)}</span></div>'
            f'<div class="pbar"><i style="left:{pos:.0f}%"></i></div>'
            f'<div class="pbk">{"".join(chips)}</div></div>')


def _mname(label, panel):
    """A metric name that's a click-to-expand toggle when a range panel exists."""
    if not panel:
        return label
    return (f'<span class="mtog" onclick="tgl(this)"><span class="chv">&#9656;</span>{label}</span>')


def _row_cr(label, mkey, m, actual):
    """A Rs-crore metric row: Est | editable Actual | Surprise, + click-out range."""
    if m:
        est_cr = round(m["avg"] / 10)
        est_disp, est_attr, tip = f"{est_cr:,}", str(est_cr), _rng_tip(m)
    else:
        est_disp, est_attr, tip = "&mdash;", "", ""
    auto = "" if actual is None else str(actual)
    panel = _range_panel(m, "cr")
    row = (f'<tr data-m="{mkey}" data-est="{est_attr}" class="mrow">'
           f'<td class="ml">{_mname(label, panel)}</td>'
           f'<td class="est" title="{tip}">{est_disp}</td>'
           f'<td class="act"><input class="ain" type="text" inputmode="numeric" '
           f'data-auto="{auto}" aria-label="{label} actual"></td>'
           f'<td class="surp"></td></tr>')
    return row + (f'<tr class="detail"><td colspan="4">{panel}</td></tr>' if panel else "")


def _row_margin(m):
    """EBITDA margin row: Est | auto-computed Actual | Surprise (pp), + click-out range."""
    if m:
        est_disp, est_attr = f"{m['avg']*100:.1f}%", f"{m['avg']*100:.4f}"
    else:
        est_disp, est_attr = "&mdash;", ""
    panel = _range_panel(m, "pct")
    row = (f'<tr data-m="margin" data-est="{est_attr}" class="mrow">'
           f'<td class="ml">{_mname("EBITDA margin", panel)}</td>'
           f'<td class="est">{est_disp}</td>'
           f'<td class="act"><span class="autom">&mdash;</span></td>'
           f'<td class="surp"></td></tr>')
    return row + (f'<tr class="detail"><td colspan="4">{panel}</td></tr>' if panel else "")


def build_estimates_html(records, actuals=None):
    """Standalone estimates page: Est vs (auto/manual) Actual with live surprise."""
    actuals = actuals or {}
    generated = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    recs = sorted(records, key=lambda r: r["name"].lower())
    ranged = sum(1 for r in recs if (r.get("rev") or {}).get("min") is not None)
    reported = 0
    cards = []
    for rec in recs:
        nm = escape(rec["name"])
        n = rec.get("n") or 0
        act = actuals.get(rec["slug"]) or {}
        has_act = any(act.get(k) is not None for k in ("rev", "ebitda", "pat"))
        if has_act:
            reported += 1
        badge = ('<span class="rep" title="Actuals auto-filled from Screener">Reported</span>'
                 if has_act else "")
        foot = (f"Est: avg of {n} brokers &middot; range on hover" if n > 1
                else "Est: 1 broker")
        cards.append(f"""<div class="ecard" id="{rec['slug']}" data-key="{rec['slug']}">
  <div class="ehead"><span class="ename">{nm}</span>{badge}<span class="star" title="Add to my watchlist" aria-hidden="true">&#9734;</span></div>
  <table class="bm"><tbody>
    <tr class="bmhd"><td class="ml"></td><td>Est</td><td>Actual &#8377;cr</td><td>Beat / miss</td></tr>
    {_row_cr('Revenue', 'rev', rec.get('rev'), act.get('rev'))}
    {_row_cr('EBITDA', 'ebitda', rec.get('ebitda'), act.get('ebitda'))}
    {_row_margin(rec.get('margin'))}
    {_row_cr('PAT', 'pat', rec.get('pat'), act.get('pat'))}
  </tbody></table>
  <div class="efoot">{foot} &middot; Q1&nbsp;FY27E &middot; type an Actual &rarr; surprise auto-calcs</div>
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
    grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }}
  .ecard {{ background:var(--card); border:1px solid var(--line); border-radius:11px;
    padding:13px 14px; scroll-margin-top:120px; }}
  .ecard.nomatch {{ display:none; }}
  .ehead {{ display:flex; align-items:flex-start; justify-content:space-between;
    gap:8px; margin-bottom:10px; }}
  .ename {{ font-size:14.5px; font-weight:650; text-wrap:balance; }}
  .star {{ cursor:pointer; color:var(--mut); font-size:17px; line-height:1; opacity:.55; flex:none; }}
  .star:hover {{ opacity:1; color:#f0a83c; }}
  .ecard.starred .star {{ color:#f0a83c; opacity:1; }}
  body.wlonly .ecard:not(.starred) {{ display:none; }}
  .wlbtn {{ background:var(--panel); border:1px solid var(--line); color:var(--ink);
    font-size:12px; font-weight:700; padding:8px 12px; border-radius:8px; cursor:pointer; white-space:nowrap; }}
  .wlbtn:hover {{ border-color:#f0a83c; }}
  .wlbtn.on {{ background:#f0a83c; border-color:#f0a83c; color:#241a00; }}
  .wlhint {{ display:none; grid-column:1/-1; padding:12px 15px; border-radius:10px;
    background:var(--panel); border:1px dashed var(--line); color:var(--mut); font-size:13px; }}
  body.wlonly .wlhint.show {{ display:block; }}
  .rep {{ font-size:9.5px; font-weight:700; padding:1px 7px; border-radius:20px; flex:none;
    background:color-mix(in srgb,var(--green) 22%,transparent); color:var(--green); align-self:center; }}
  .bm {{ width:100%; border-collapse:collapse; }}
  .bm td {{ padding:5px 3px; font-size:12.5px; border-top:0.5px solid var(--line); }}
  .bmhd td {{ border-top:none; font-size:9px; text-transform:uppercase; letter-spacing:.3px;
    color:var(--mut); padding:0 3px 3px; text-align:right; }}
  .bmhd td.ml {{ text-align:left; }}
  .bm td.ml {{ color:var(--mut); white-space:nowrap; }}
  .bm td.est {{ text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }}
  .bm td.act {{ text-align:right; width:68px; }}
  .ain {{ width:64px; text-align:right; font-size:12.5px; font-variant-numeric:tabular-nums;
    padding:3px 5px; border:1px solid var(--line); border-radius:6px; background:var(--bg);
    color:var(--ink); outline:none; }}
  .ain:focus {{ border-color:var(--accent); }}
  .ain.auto {{ color:var(--green); border-color:color-mix(in srgb,var(--green) 50%,var(--line)); }}
  .autom {{ color:var(--mut); font-variant-numeric:tabular-nums; }}
  .surp {{ text-align:right; font-weight:700; font-variant-numeric:tabular-nums;
    white-space:nowrap; color:var(--mut); }}
  .surp.beat {{ color:#1f9d55; }}
  .surp.miss {{ color:#e2534a; }}
  .mtog {{ cursor:pointer; display:inline-flex; align-items:center; gap:5px; }}
  .mtog:hover {{ color:var(--accent); }}
  .chv {{ font-size:9px; color:var(--mut); transition:transform .15s; }}
  .mrow.open .chv {{ transform:rotate(90deg); color:var(--accent); }}
  .detail td {{ border-top:none !important; padding:0 !important; }}
  .panel {{ display:none; background:var(--bg); border:1px solid var(--line); border-radius:9px;
    margin:2px 0 7px; padding:10px 11px; }}
  .mrow.open + .detail .panel {{ display:block; }}
  .prng {{ display:flex; justify-content:space-between; font-size:10.5px; color:var(--mut); }}
  .prng.v {{ color:var(--ink); font-weight:700; font-variant-numeric:tabular-nums; margin-top:1px; }}
  .pbar {{ position:relative; height:5px; background:var(--line); border-radius:3px; margin:7px 0 9px; }}
  .pbar i {{ position:absolute; top:-2px; width:2px; height:9px; background:var(--accent); border-radius:1px; }}
  .pbk {{ display:flex; flex-wrap:wrap; gap:5px; }}
  .bk {{ font-size:11px; font-variant-numeric:tabular-nums; background:var(--card);
    border:0.5px solid var(--line); border-radius:6px; padding:2px 7px; }}
  .bk b {{ font-weight:700; }}
  .bk.lo {{ border-color:#e2534a; color:#e2534a; }}
  .bk.hi {{ border-color:#1f9d55; color:#1f9d55; }}
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
     <b>Est</b> = broker average (hover for the low&ndash;high range). <b>Actual</b> is auto-filled
     from Screener once a company reports (<b>{reported}</b> so far, shown in <b style="color:var(--green)">green</b>);
     for the rest, <b>type the number in</b> and the <b>beat / miss</b> shows instantly.
     Your entries save in your browser and are <b>auto-replaced by the official Screener figure</b> the moment it&rsquo;s published.</div>
  <div class="bar">
    <div class="search"><input id="q" type="search"
       placeholder="Search a company&hellip; (e.g. Reliance, Infosys, Bajaj)"></div>
    <button id="wlBtn" class="wlbtn" title="Show only my starred companies">&#9734; Watchlist</button>
  </div>
</header>
<main id="grid">
<div id="wlHint" class="wlhint">Your watchlist is empty. Click the <b>&#9734;</b> star on any
  company&rsquo;s card to add it &mdash; it&rsquo;s saved in your browser and shared with the calendar.</div>
{"".join(cards)}
</main>
<footer>
  <b>Est</b> = average of MOSL / Kotak / Ambit / Spark / I-Sec for Q1&nbsp;FY27E (Revenue/NII, EBITDA/PPOP, PAT).
  <b>Actual</b> is the reported figure auto-filled from Screener (green) or typed by you; surprise =
  (actual &minus; est) &divide; est, margin surprise in percentage points. For banks/NBFCs, EBITDA is not
  meaningful and is left blank. Numbers in &#8377; crore. Updated {generated}.
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

  // click a metric name to expand its per-broker range
  function tgl(el) {{ el.closest('tr').classList.toggle('open'); }}
  window.tgl = tgl;

  const q = document.getElementById('q');
  const cards = [...document.querySelectorAll('.ecard')];
  q.addEventListener('input', () => {{
    const t = q.value.trim().toLowerCase();
    cards.forEach(c => c.classList.toggle('nomatch',
      t && !c.querySelector('.ename').textContent.toLowerCase().includes(t)));
  }});

  // ---- Actual vs Estimate surprise (editable, auto-calc, saved in your browser) ----
  const AK = 'cal-actuals';
  let store = {{}};
  try {{ store = JSON.parse(localStorage.getItem(AK) || '{{}}'); }} catch (e) {{}}
  const arrow = (d, pp) => (d >= 0 ? '▲ ' : '▼ ') + Math.abs(d).toFixed(1) + (pp ? ' pp' : '%');
  function recalc(card) {{
    const est = {{}}, act = {{}};
    card.querySelectorAll('tr[data-m]').forEach(tr => {{
      const m = tr.dataset.m;
      est[m] = tr.dataset.est !== '' ? parseFloat(tr.dataset.est) : NaN;
      const inp = tr.querySelector('input.ain');
      if (inp) {{ const v = parseFloat((inp.value || '').replace(/,/g, '')); act[m] = isNaN(v) ? null : v; }}
    }});
    act.margin = (act.rev && act.ebitda != null && act.rev !== 0) ? act.ebitda / act.rev * 100 : null;
    const mc = card.querySelector('tr[data-m="margin"] .autom');
    if (mc) mc.textContent = act.margin != null ? act.margin.toFixed(1) + '%' : '—';
    card.querySelectorAll('tr[data-m]').forEach(tr => {{
      const m = tr.dataset.m, s = tr.querySelector('.surp'), e = est[m], a = act[m];
      if (a == null || isNaN(e)) {{ s.textContent = ''; s.className = 'surp'; return; }}
      const d = m === 'margin' ? (a - e) : (a - e) / e * 100;
      s.textContent = arrow(d, m === 'margin'); s.className = 'surp ' + (d >= 0 ? 'beat' : 'miss');
    }});
  }}
  cards.forEach(card => {{
    const slug = card.id;
    card.querySelectorAll('input.ain').forEach(inp => {{
      const m = inp.closest('tr').dataset.m;
      const auto = inp.dataset.auto || '';
      const saved = store[slug] && store[slug][m];
      // Behaviour B: the official Screener figure (auto) always wins when present;
      // your manual entry only fills companies that have no actual yet, and is
      // replaced automatically once the real number is published.
      inp.value = auto !== '' ? auto : ((saved != null && saved !== '') ? saved : '');
      inp.classList.toggle('auto', inp.value !== '' && inp.value === auto);
      inp.addEventListener('input', () => {{
        inp.classList.toggle('auto', inp.value !== '' && inp.value === auto);
        store[slug] = store[slug] || {{}};
        store[slug][m] = inp.value;
        localStorage.setItem(AK, JSON.stringify(store));
        recalc(card);
      }});
    }});
    recalc(card);
  }});

  // ---- watchlist (shared with the calendar, saved in your browser only) ----
  const WL_KEY = 'cal-watchlist';
  let wl = new Set();
  try {{ wl = new Set(JSON.parse(localStorage.getItem(WL_KEY) || '[]')); }} catch (e) {{}}
  const wlBtn = document.getElementById('wlBtn'), wlHint = document.getElementById('wlHint');
  function paintStars() {{
    cards.forEach(el => {{
      const on = wl.has(el.dataset.key);
      el.classList.toggle('starred', on);
      const s = el.querySelector('.star'); if (s) s.innerHTML = on ? '&#9733;' : '&#9734;';
    }});
    wlBtn.innerHTML = (wl.size ? '&#9733;' : '&#9734;') + ' Watchlist' + (wl.size ? ' (' + wl.size + ')' : '');
  }}
  function updateHint() {{ wlHint.classList.toggle('show', wl.size === 0); }}
  document.addEventListener('click', e => {{
    const s = e.target.closest('.star'); if (!s) return;
    const card = s.closest('.ecard'); if (!card) return;
    const k = card.dataset.key; wl.has(k) ? wl.delete(k) : wl.add(k);
    localStorage.setItem(WL_KEY, JSON.stringify([...wl])); paintStars(); updateHint();
  }});
  wlBtn.addEventListener('click', () => {{
    const on = document.body.classList.toggle('wlonly');
    wlBtn.classList.toggle('on', on); updateHint();
  }});
  paintStars();
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
        OUT_EST_HTML.write_text(build_estimates_html(est_recs, load_actuals()), encoding="utf-8")
    n = sum(1 for r in data["list"] if RESULT_TYPE_LABEL in (r.get("resultType") or ""))
    print(f"OK  {n} companies  ->  {OUT_HTML.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
