#!/usr/bin/env python3
"""
Builds actuals.json: reported Q1 FY27 (Jun-2026) numbers per company, from
Screener.in, used to auto-fill the "Actual" column on the estimates cards.

Reached via the NSE ticker in tickers.json (Screener slug = ticker). Only the
Jun-2026 quarter is read: Revenue (Sales), EBITDA (Operating Profit), PAT
(Net Profit). Companies not yet reported have no Jun-2026 column -> skipped.

    python build_actuals.py            # incremental: only companies past their
                                       # result date that we don't already have
    python build_actuals.py --full     # re-fetch everything

Only companies with an estimate AND a ticker are fetched (that's where a
surprise can be computed). Values are in Rs crore (as Screener reports them).
"""
import gzip, json, re, ssl, sys, time, urllib.request
from datetime import date, datetime
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

HERE = Path(__file__).parent
MC_JSON = HERE / "earnings_data.json"
EST_JSON = HERE / "estimates.json"
TKR_JSON = HERE / "tickers.json"
OUT = HERE / "actuals.json"

QUARTER = "Jun 2026"
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def norm(s):
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(limited|ltd|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def clean(s):
    s = re.sub(r"<[^>]+>", "", s).replace("\xa0", " ").replace("&nbsp;", " ")
    return s.strip().rstrip("+").strip()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    r = urllib.request.urlopen(req, timeout=30, context=CTX)
    d = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        d = gzip.decompress(d)
    return d.decode("utf-8", "replace")


def _num(v):
    try:
        return round(float(v.replace(",", "")))
    except Exception:
        return None


def fetch_actual(ticker):
    """Return {'rev','ebitda','pat'} in Rs cr for Jun-2026, or None if not reported."""
    html = None
    for path in (f"https://www.screener.in/company/{ticker}/consolidated/",
                 f"https://www.screener.in/company/{ticker}/"):
        try:
            html = _get(path)
            break
        except Exception:
            html = None
    if not html:
        return None
    m = re.search(r"Quarterly Results.*?</table>", html, re.S)
    if not m:
        return None
    seg = m.group(0)
    months = re.findall(r"<th[^>]*>\s*([A-Za-z]{3}\s*\d{4})", seg)
    if QUARTER not in months:
        return None
    idx = months.index(QUARTER)
    rows = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if cells:
            rows[clean(cells[0])] = [clean(c) for c in cells[1:]]

    def find(*names):
        for label, vals in rows.items():
            low = label.lower()
            if any(low.startswith(n) for n in names) and idx < len(vals):
                return _num(vals[idx])
        return None

    rev = find("sales", "revenue", "total income")
    ebitda = find("operating profit")          # absent for banks/NBFCs -> None
    pat = find("net profit", "profit after tax", "profit for")
    if rev is None and pat is None and ebitda is None:
        return None
    return {"rev": rev, "ebitda": ebitda, "pat": pat}


def report_date(datestr):
    try:
        dd, mm = datestr.split()
        return date(2026, MONTHS[mm[:3].title()], int(dd))
    except Exception:
        return None


def main():
    today = datetime.now().date()
    est = json.loads(EST_JSON.read_text(encoding="utf-8"))["records"]
    # est_lookup maps a normalized name/alias -> the estimate slug (its card id)
    est_lookup = {}
    for r in est:
        slug = norm(r["name"])
        for nm in [r["name"]] + r.get("aliases", []):
            est_lookup.setdefault(norm(nm), slug)
    tickers = {k: v for k, v in json.loads(TKR_JSON.read_text(encoding="utf-8")).items() if v}

    # reported companies that map to an estimate card, keyed by that card's SLUG
    want = {}
    for r in json.loads(MC_JSON.read_text(encoding="utf-8"))["list"]:
        nm = r.get("stockName") or r.get("stockShortName") or ""
        short = r.get("stockShortName") or ""
        slug = est_lookup.get(norm(nm)) or (est_lookup.get(norm(short)) if short else None)
        d = report_date(r.get("date", ""))
        tkr = tickers.get(norm(nm)) or (tickers.get(norm(short)) if short else None)
        if slug and tkr and d and d < today:
            want[slug] = tkr

    known = {}
    if OUT.exists() and "--full" not in sys.argv:
        try:
            known = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            known = {}

    todo = [(k, t) for k, t in want.items() if k not in known]
    print(f"{len(want)} reported+covered companies | {len(known)} already have actuals | {len(todo)} to fetch")
    hits = 0
    for i, (key, tkr) in enumerate(todo, 1):
        try:
            a = fetch_actual(tkr)
        except Exception:
            a = None
        if a:
            known[key] = a
            hits += 1
        if i % 20 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}  (+{hits} with actuals)", flush=True)
        time.sleep(0.4)

    OUT.write_text(json.dumps(known, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"DONE  {len(known)} companies have actuals  ->  {OUT.name}")


if __name__ == "__main__":
    main()
