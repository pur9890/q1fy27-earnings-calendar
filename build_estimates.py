#!/usr/bin/env python3
"""
Reads the broker-estimates workbook (Sheet1, which already averages MOSL/Kotak/
Ambit) and writes estimates.json for the calendar to consume.

Run whenever the Excel changes:
    python build_estimates.py

Only the AVERAGE across brokers is kept (Revenue, EBITDA, EBITDA margin, PAT),
plus how many brokers contributed. Values are in Rs million (as in the sheet).
"""
import json
import re
from pathlib import Path

import openpyxl

XLSX = Path(r"C:\Users\lenovo\Desktop\MOSL & KIE Estimate Q1FY27.xlsx")
OUT = Path(__file__).with_name("estimates.json")

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

# Sheet1 column indices (0-based)
C_MOSL, C_KOTAK, C_AMBIT = 0, 1, 2
C_REV = [3, 4, 5, 6]        # MOSL, Kotak, Ambit, Average
C_EBITDA = [7, 8, 9, 10]
C_MARGIN = [11, 12, 13, 14]
C_PAT = [15, 16, 17, 18]


def num(v):
    return v if isinstance(v, (int, float)) else None


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))

    records = []
    for r in rows[2:]:
        name = (r[C_MOSL] or "").strip() if r[C_MOSL] else ""
        if not name:
            continue
        rev, ebitda, margin, pat = (num(r[C_REV[3]]), num(r[C_EBITDA[3]]),
                                    num(r[C_MARGIN[3]]), num(r[C_PAT[3]]))
        if rev is None and ebitda is None and pat is None:
            continue
        # how many brokers contributed (based on the revenue columns)
        n = sum(1 for c in C_REV[:3] if num(r[c]) is not None)
        aliases = [a.strip() for a in (r[C_KOTAK], r[C_AMBIT]) if a and str(a).strip()]
        aliases += EXTRA_ALIASES.get(name, [])
        records.append({
            "name": name,
            "aliases": aliases,
            "rev": rev, "ebitda": ebitda, "margin": margin, "pat": pat,
            "n": n,
        })

    OUT.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=0),
                   encoding="utf-8")
    print(f"DONE  {len(records)} companies with estimates  ->  {OUT.name}")


if __name__ == "__main__":
    main()
