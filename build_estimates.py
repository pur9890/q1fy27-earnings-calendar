#!/usr/bin/env python3
"""
Reads the broker-estimates workbook (Sheet1) and writes estimates.json.

Sheet1 holds, per company, each broker's Q1 FY27E estimate (MOSL, Kotak, Ambit,
Spark, I-Sec) plus their Average. For every metric we keep the average and the
low/high across whichever brokers actually have a number, so the site can show
e.g.  Revenue 1,263 (1,206 - 1,285).

Run whenever the Excel changes:
    python build_estimates.py

Values stay in Rs million (the site converts to Rs crore). Companies covered by
only one broker get no range - low/high would just repeat the single number.
"""
import json
from pathlib import Path

import openpyxl

XLSX = Path(r"C:\Users\lenovo\Desktop\MOSL & KIE Estimate Q1FY27 (version 1).xlsx")
OUT = Path(__file__).with_name("estimates.json")

BROKERS = ["MOSL", "Kotak", "Ambit", "Spark", "I-Sec"]

# Sheet1 layout (0-based). Row 1 = metric group, row 2 = broker, data from row 3.
C_NAME = 0
C_ALIAS = [1, 2, 3, 4]          # Kotak / Ambit / Spark / I-Sec names
C_REV, C_EBITDA, C_MARGIN, C_PAT = 5, 11, 17, 23      # each: 5 brokers then Average

# Verified extra aliases: map a record (by its MOSL name) to the exact
# MoneyControl calendar name(s), so the calendar links resolve reliably.
# (Hand-checked; excludes false positives like Shree Digvijay -> Shree Cement.)
EXTRA_ALIASES = {
    "Adani Ports": ["Adani Ports and Special Economic Zone"],
    "Aditya Birla AMC": ["Aditya Birla Sun Life AMC"],
    "Bikaji Foods": ["Bikaji Foods International"],
    "CG Power & Inds.": ["CG Power and Industrial Solutions"],
    "CIE Automotive": ["CIE Automotive India"],
    "Concor": ["Container Corporation of India"],
    "HDFC Life Insur.": ["HDFC Life Insurance Company"],
    "ICICI Lombard": ["ICICI Lombard General Insurance Company"],
    "ICICI Pru Life": ["ICICI Prudential Life Insurance Company"],
    "Indian Hotels": ["Indian Hotels Company"],
    "Jio Financial": ["Jio Financial Services"],
    "Mahindra Lifespace": ["Mahindra Lifespace Developers"],
    "M & M Financial": ["Mahindra and Mahindra Financial Services"],
    "Navin Fluorine": ["Navin Fluorine International"],
    "SBI Life Insurance": ["SBI Life Insurance Company"],
    "Sona BLW Precis.": ["Sona BLW Precision Forgings"],
    "Star Health": ["Star Health & Allied Insurance Company"],
    "TVS Motor": ["TVS Motor Company"],
    "Transport Corp.": ["Transport Corporation of India"],
    "Union Bank": ["Union Bank of India"],
}


def num(v):
    return v if isinstance(v, (int, float)) else None


def metric(row, start):
    """Average + low/high across the brokers that have a number for this metric.
    Returns None when nobody covers it; 'n' is how many brokers contributed."""
    vals = [num(row[i]) for i in range(start, start + len(BROKERS))]
    who = [(BROKERS[i], v) for i, v in enumerate(vals) if v is not None]
    if not who:
        return None
    avg = num(row[start + len(BROKERS)])          # the sheet's own Average column
    if avg is None:
        avg = sum(v for _, v in who) / len(who)
    lo = min(who, key=lambda x: x[1])
    hi = max(who, key=lambda x: x[1])
    out = {"avg": avg, "n": len(who), "brokers": [[b, v] for b, v in who]}
    if len(who) > 1:                              # a range only means something with 2+
        out.update({"min": lo[1], "max": hi[1], "minBy": lo[0], "maxBy": hi[0]})
    return out


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))

    records = []
    for r in rows[2:]:
        # Every company in Sheet1 counts. MOSL doesn't cover all of them, so fall
        # back to whichever broker names the company (Kotak/Ambit/Spark/I-Sec).
        names = [str(r[i]).strip() for i in [C_NAME] + C_ALIAS
                 if r[i] and str(r[i]).strip()]
        if not names:
            continue
        name = names[0]
        rev, ebitda = metric(r, C_REV), metric(r, C_EBITDA)
        margin, pat = metric(r, C_MARGIN), metric(r, C_PAT)
        if not any((rev, ebitda, pat)):
            continue
        aliases = names[1:] + EXTRA_ALIASES.get(name, [])
        records.append({
            "name": name,
            "aliases": sorted(set(aliases)),
            "rev": rev, "ebitda": ebitda, "margin": margin, "pat": pat,
            "n": max((m["n"] for m in (rev, ebitda, margin, pat) if m), default=0),
        })

    OUT.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=0),
                   encoding="utf-8")
    ranged = sum(1 for x in records if (x["rev"] or {}).get("min") is not None)
    print(f"DONE  {len(records)} companies  ->  {OUT.name}")
    print(f"      {ranged} have a revenue range (2+ brokers), "
          f"{len(records) - ranged} single-broker")


if __name__ == "__main__":
    main()
