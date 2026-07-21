#!/usr/bin/env python3
"""
Builds tickers.json: company -> NSE ticker, used for the TradingView chart links.

Source: NSE's official equity list (EQUITY_L.csv), which maps every listed
company name to its trading symbol. One download, then offline name matching -
no per-company lookups, so this is cheap enough to run on every build.

    python build_tickers.py

Companies not on NSE (BSE-only / NSE-SME) simply get no ticker and show no
chart icon, rather than risking a wrong chart.
"""
import csv, io, json, re, ssl, urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
NSE_CSV = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

HERE = Path(__file__).parent
MC_JSON = HERE / "earnings_data.json"
OUT = HERE / "tickers.json"


def norm(s, drop_parens):
    s = s.lower().replace("&", " and ")
    if drop_parens:
        s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(limited|ltd|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def fetch_nse():
    req = urllib.request.Request(NSE_CSV, headers={"User-Agent": UA,
                                                   "Referer": "https://www.nseindia.com/"})
    with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
        text = r.read().decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [(r["SYMBOL"].strip(), (r.get("NAME OF COMPANY") or "").strip()) for r in rows]


def main():
    listed = fetch_nse()
    symbols = {s for s, _ in listed}
    exact, stripped, dupes = {}, {}, set()
    for sym, name in listed:
        if not name:
            continue
        exact.setdefault(norm(name, False), sym)
        k = norm(name, True)
        if k in stripped and stripped[k] != sym:
            dupes.add(k)          # ambiguous once "(India)" etc. is removed
        else:
            stripped[k] = sym
    for k in dupes:
        stripped.pop(k, None)
    print(f"NSE list: {len(listed)} companies")

    rows = json.loads(MC_JSON.read_text(encoding="utf-8"))["list"]
    comps = {}
    for r in rows:
        nm = r.get("stockName") or r.get("stockShortName") or ""
        if nm:
            comps[norm(nm, True)] = (nm, (r.get("stockShortName") or "").strip())

    out, hits = {}, 0
    for key, (name, short) in comps.items():
        sym = (exact.get(norm(name, False))
               or stripped.get(norm(name, True))
               or (short.upper() if short.upper() in symbols else None))
        out[key] = sym
        if sym:
            hits += 1

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"DONE  {hits}/{len(out)} companies matched to an NSE ticker  ->  {OUT.name}")


if __name__ == "__main__":
    main()
