#!/usr/bin/env python3
"""
Reads the broker-estimates workbook (Q2 FY27 sheet) and writes estimates.json.

The sheet holds, per company, each broker's Q2 FY27E estimate (MOSL, Kotak, Ambit,
Spark, I-Sec, B&K) plus their Average. For every metric we keep the average and the
low/high across whichever brokers actually have a number, so the site can show
e.g.  Revenue 1,263 (1,206 - 1,285).

Run whenever the Excel changes:
    python build_estimates.py

Values stay in Rs million (the site converts to Rs crore). Companies covered by
only one broker get no range - low/high would just repeat the single number.
"""
import json
import re
from pathlib import Path

import openpyxl

XLSX = Path(r"C:\Users\lenovo\OneDrive\Desktop\p\MOSL & KIE Estimate Q1FY27 (version 1).xlsx")
SHEET = "Sheet1 Q2FY27"         # Q2 FY27 consolidated tab in the workbook
OUT = Path(__file__).with_name("estimates.json")

BROKERS = ["MOSL", "Kotak", "Ambit", "Spark", "I-Sec", "B&K"]

# Sheet layout (0-based). Row 1 = metric group, row 2 = broker, data from row 3.
# 6 name columns, then each metric block = 6 brokers followed by an Average column.
C_NAME = 0
C_ALIAS = [1, 2, 3, 4, 5]       # Kotak / Ambit / Spark / I-Sec / B&K names
C_REV, C_EBITDA, C_MARGIN, C_PAT = 6, 13, 20, 27      # each: 6 brokers then Average

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


# Keep ONLY brokers whose Q2 FY27 numbers are actually in the workbook.
# Spark / Ambit / MOSL have no Q2 preview tab, so any values in their columns on
# the "Sheet1 Q2FY27" consolidated tab are stale Q1 carry-over and are ignored.
# (When the user adds a Spark/Ambit/MOSL Q2 tab, add them here + to PREVIEW.)
Q2_BROKERS = {"Kotak", "I-Sec", "B&K"}
BLOCKS = (6, 13, 20, 27)          # broker-start columns for Rev/EBITDA/Margin/PAT
METRIC_KEYS = ("rev", "ebitda", "margin", "pat")

# For a broker whose consolidated column on "Sheet1 Q2FY27" was NOT reliably
# synced for Q2 (e.g. I-Sec, which still held Q1 values for most companies),
# pull its numbers straight from its own dedicated Q2 preview tab instead.
# Kotak and B&K were synced into the consolidated tab (verified 0 stale), so
# they are read from there and need no override.
PREVIEW = {
    "I-Sec": {"sheet": "ISec Q2 FY27 preview", "name": 1,
              "cols": {"rev": 2, "ebitda": 3, "margin": 4, "pat": 5}},
}


def _jnorm(s):
    """Loose name key for joining preview tabs to the consolidated rows."""
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\b(ltd|limited|limite|the)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def metric(row, start):
    """Average + low/high across the brokers that have a number for this metric.
    Returns None when nobody covers it; 'n' is how many brokers contributed.
    The average is recomputed from the kept brokers (the sheet's own Average
    column is ignored because it includes the excluded/stale broker columns)."""
    vals = [num(row[i]) for i in range(start, start + len(BROKERS))]
    who = [(BROKERS[i], v) for i, v in enumerate(vals) if v is not None]
    if not who:
        return None
    avg = sum(v for _, v in who) / len(who)
    lo = min(who, key=lambda x: x[1])
    hi = max(who, key=lambda x: x[1])
    out = {"avg": avg, "n": len(who), "brokers": [[b, v] for b, v in who]}
    if len(who) > 1:                              # a range only means something with 2+
        out.update({"min": lo[1], "max": hi[1], "minBy": lo[0], "maxBy": hi[0]})
    return out


def _idkey(r):
    """Company identity = first non-empty of the six name columns."""
    for i in [C_NAME] + C_ALIAS:
        if i < len(r) and r[i] and str(r[i]).strip():
            return str(r[i]).strip().lower()
    return None


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    ws = wb[SHEET]
    rows = list(ws.iter_rows(values_only=True))

    # Build per-broker Q2 preview maps (authoritative Sep-26E numbers).
    pv = {}
    for b, cfg in PREVIEW.items():
        m = {}
        if cfg["sheet"] in wb.sheetnames:
            for r in list(wb[cfg["sheet"]].iter_rows(values_only=True))[2:]:
                nm = r[cfg["name"]] if cfg["name"] < len(r) else None
                if not nm:
                    continue
                vals = {k: (r[c] if c < len(r) and isinstance(r[c], (int, float)) else None)
                        for k, c in cfg["cols"].items()}
                if any(v is not None for v in vals.values()):
                    m[_jnorm(nm)] = vals
        pv[b] = m

    def clean(r):
        """Keep only Q2 brokers: drop excluded ones, and replace a preview-backed
        broker's consolidated values with its authoritative preview numbers."""
        r = list(r)
        rownames = [r[i] for i in [C_NAME] + C_ALIAS if i < len(r) and r[i]]
        for bi, b in enumerate(BROKERS):
            if b in PREVIEW:
                hit = None
                for nm in rownames:
                    hit = pv[b].get(_jnorm(nm))
                    if hit:
                        break
                for start, mk in zip(BLOCKS, METRIC_KEYS):
                    r[start + bi] = hit.get(mk) if hit else None
            elif b not in Q2_BROKERS:
                for start in BLOCKS:
                    if start + bi < len(r):
                        r[start + bi] = None
            # else (Kotak, B&K): keep the consolidated value as-is
        return r

    records = []
    for r in rows[2:]:
        # Every company counts. MOSL doesn't cover all of them, so fall back to
        # whichever broker names the company (Kotak/Ambit/Spark/I-Sec/B&K).
        names = [str(r[i]).strip() for i in [C_NAME] + C_ALIAS
                 if r[i] and str(r[i]).strip()]
        if not names:
            continue
        name = names[0]
        r = clean(r)
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
