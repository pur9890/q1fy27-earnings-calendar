#!/usr/bin/env python3
"""
Builds release_times.json: an approximate result-release time for each company,
taken from when it filed LAST quarter's (Q4 FY26) results with the BSE exchange.

These times are a proxy for Q1 FY27 timing and only need to be rebuilt occasionally
(last quarter's filing times don't change). Run:
    python build_release_times.py

Sources:
  - Primary : BSE "Result" category announcements, Apr-Jun 2026 (bulk sweep).
  - Fallback: for companies whose results were filed under "Board Meeting",
              a per-company lookup via BSE search, excluding meeting *intimations*.
Companies listed only on NSE / NSE-SME (not on BSE) will have no time.
"""
import json, re, ssl, time, urllib.request
from urllib.parse import quote
from datetime import datetime, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HDR = {"User-Agent": UA, "Referer": "https://www.bseindia.com/",
       "Origin": "https://www.bseindia.com", "Accept": "application/json"}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

FROM, TO = "20260401", "20260630"          # Q4 FY26 reporting window
HERE = Path(__file__).parent
MC_JSON = HERE / "earnings_data.json"       # produced by update_calendar.py
OUT = HERE / "release_times.json"


def jget(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=35, context=CTX) as r:
        return r.read().decode("utf-8", "replace")


def norm(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\b(ltd|limited|limite|the)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def ann(cat, scrip="", page=1):
    url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
           f"pageno={page}&strCat={quote(cat)}&strPrevDate={FROM}&strToDate={TO}"
           f"&strScrip={scrip}&strSearch=P&strType=C")
    return json.loads(jget(url))


# --- 1. Bulk sweep of the clean "Result" category (fortnightly windows) --------
def sweep_results():
    windows = [("20260401", "20260415"), ("20260416", "20260430"),
               ("20260501", "20260515"), ("20260516", "20260531"),
               ("20260601", "20260615"), ("20260616", "20260630")]
    rows = {}
    for frm, to in windows:
        page, total = 1, None
        while True:
            url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
                   f"pageno={page}&strCat=Result&strPrevDate={frm}&strToDate={to}"
                   "&strScrip=&strSearch=P&strType=C")
            d = json.loads(jget(url))
            t = d.get("Table", [])
            if total is None:
                total = (d.get("Table1") or [{}])[0].get("ROWCNT", 0)
            if not t:
                break
            for r in t:
                k = norm(r.get("SLONGNAME") or "")
                dt = r.get("DT_TM") or ""
                if k and (k not in rows or dt < rows[k]):
                    rows[k] = dt
            if page * 50 >= (total or 0):
                break
            page += 1; time.sleep(0.2)
        time.sleep(0.2)
    return rows


# --- 2. Fallback: results filed under "Board Meeting" (exclude intimations) -----
POS = re.compile(r"outcome of board|financial result|audited financial|"
                 r"unaudited financial|standalone and consolidated", re.I)
NEG = re.compile(r"intimation|to be held|to consider|notice of|newspaper|"
                 r"investor|transcript|earnings call|press release|record date|"
                 r"schedule|prior|reschedul|postpon", re.I)


def search_code(name):
    try:
        html = jget(f"https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w?Type=SS&text={quote(name)}")
    except Exception:
        return None
    m = re.search(r"liclick\('(\d{6})'", html)
    return m.group(1) if m else None


def _ymd(dt):
    return dt.strftime("%Y%m%d")


def scrip_result_time(code, on_date=None):
    """Genuine results/board-outcome filing time for a scrip.
    When on_date (YYYY-MM-DD) is known, query a tight +/-5 day window around it
    (avoids page-1 truncation for prolific filers and unrelated board meetings)."""
    if on_date:
        c = _d(on_date)
        frm, to = _ymd(c - timedelta(days=5)), _ymd(c + timedelta(days=5))
    else:
        frm, to = FROM, TO
    url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
           f"pageno=1&strCat=-1&strPrevDate={frm}&strToDate={to}"
           f"&strScrip={code}&strSearch=P&strType=C")
    try:
        d = json.loads(jget(url))
    except Exception:
        return None
    good = []
    for r in d.get("Table", []):
        subj = (r.get("NEWSSUB") or "") + " " + (r.get("HEADLINE") or "")
        cat = r.get("CATEGORYNAME") or ""
        dt = r.get("DT_TM") or ""
        if NEG.search(subj):
            continue
        if cat == "Result" or POS.search(subj):
            good.append(dt)
    if not good:
        return None
    if on_date:
        # pick the genuine results filing closest to the known report date
        return min(good, key=lambda dt: abs((_d(dt) - _d(on_date)).days))
    return min(good)


def _d(s):
    return datetime.strptime(s[:10], "%Y-%m-%d")


def q4_report_dates():
    """norm(name) -> 'YYYY-MM-DD' when the company filed Q4 FY26 (from MoneyControl).
    Fetched in fortnightly chunks; the MoneyControl API times out on wide ranges."""
    hdr = {"User-Agent": UA, "Referer": "https://www.moneycontrol.com/", "Accept": "application/json"}
    months = {m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
    windows = [("2026-04-01", "2026-04-15"), ("2026-04-16", "2026-04-30"),
               ("2026-05-01", "2026-05-15"), ("2026-05-16", "2026-05-31"),
               ("2026-06-01", "2026-06-15"), ("2026-06-16", "2026-06-30")]
    out = {}
    for s, e in windows:
        url = ("https://api.moneycontrol.com/mcapi/v1/earnings/get-earnings-data"
               f"?indexId=All&page=1&startDate={s}&endDate={e}"
               "&sector=&limit=2000&sortBy=marketcap&search=&seq=desc")
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
                rows = json.load(r)["data"]["list"]
        except Exception:
            continue
        for r in rows:
            if "Q4 FY25-26" not in (r.get("resultType") or ""):
                continue
            try:
                dd, mm = r["date"].split()
                out[norm(r["stockName"])] = f"2026-{months[mm[:3].title()]:02d}-{int(dd):02d}"
            except Exception:
                pass
        time.sleep(0.2)
    return out


def fmt(iso):
    return datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M").strftime("%I:%M %p").lstrip("0")


def resolve_one(name, q4dates):
    """Look up a single company's last-quarter filing time via BSE. None if not found."""
    code = search_code(name); time.sleep(0.12)
    if not code:
        return None
    dt = scrip_result_time(code, on_date=q4dates.get(norm(name))); time.sleep(0.12)
    return fmt(dt) if dt else None


def build_incremental(comps):
    """Only resolve companies that don't already have a time (fast; for daily runs)."""
    existing = {}
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    missing = [c for c in comps if norm(c) not in existing]
    print(f"{len(comps)} companies | {len(existing)} already timed | {len(missing)} to look up")
    if not missing:
        print("No new companies need a time. Nothing to do.")
        return
    q4dates = q4_report_dates()
    added = 0
    for c in missing:
        t = resolve_one(c, q4dates)
        # Record EVERY company we checked - the time if found, else null - so
        # companies not on BSE are never re-checked on later runs (keeps builds fast).
        existing[norm(c)] = t
        if t:
            added += 1
            print(f"  + {c}  ->  {t}")
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=0, sort_keys=True),
                   encoding="utf-8")
    have = sum(1 for v in existing.values() if v)
    print(f"incremental done: +{added} new times | {have} companies have a time | "
          f"{len(existing) - have} confirmed no BSE time (won't re-check)")


def build_full(comps):
    print(f"{len(comps)} companies to resolve (FULL rebuild)")

    bmap = sweep_results()
    print(f"BSE Result-sweep: {len(bmap)} companies")

    def prefix_match(n):
        if n in bmap:
            return bmap[n]
        best = None
        for bn, dt in bmap.items():
            if len(n) >= 6 and (bn.startswith(n) or n.startswith(bn)):
                d = abs(len(bn) - len(n))
                if best is None or d < best[0]:
                    best = (d, dt)
        return best[1] if best else None

    final, unmatched = {}, []
    for c in comps:
        dt = prefix_match(norm(c))
        if dt:
            final[norm(c)] = fmt(dt)
        else:
            unmatched.append(c)
    print(f"matched from sweep: {len(final)} | fallback needed: {len(unmatched)}")

    q4dates = q4_report_dates()
    print(f"MoneyControl Q4 dates: {len(q4dates)} companies")
    for c in unmatched:
        code = search_code(c); time.sleep(0.12)
        if not code:
            continue
        dt = scrip_result_time(code, on_date=q4dates.get(norm(c))); time.sleep(0.12)
        if dt:
            final[norm(c)] = fmt(dt)

    OUT.write_text(json.dumps(final, ensure_ascii=False, indent=0, sort_keys=True),
                   encoding="utf-8")
    print(f"DONE  {len(final)}/{len(comps)} companies have a time  ->  {OUT.name}")


def main():
    import sys
    comps = [r["stockName"] for r in json.loads(MC_JSON.read_text(encoding="utf-8"))["list"]]
    # Full rebuild only when forced or when no times exist yet; otherwise incremental.
    if "--full" in sys.argv or not OUT.exists():
        build_full(comps)
    else:
        build_incremental(comps)


if __name__ == "__main__":
    main()
