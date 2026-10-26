#!/usr/bin/env python3
"""Build a self-contained, offline HTML baby-name explorer from the SSA files.

The page lets you search names (girls and boys listed separately, since a name
like Regan appears for both), pick several, and compare them over time for the
whole US and one state, as babies per year or per 100,000 births.

Usage:
  python build_explorer.py                      # uses the cached SSA zips (downloads if missing)
  python build_explorer.py --state CA
  python build_explorer.py --default "Paulina|F,Regan|F,Manuel|M"
  python build_explorer.py --min-total 50       # include rarer names (bigger file)

Writes output/name_explorer.html. Double-click it to open in your browser.
It needs the zips that ssa_names.py caches in data/ssa/, or it downloads them.
"""
import argparse
import base64
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

from ssa_names import NATIONAL_URL, STATE_URL, get_zip, read_national, read_state

STARTER = ["Susannah|F", "Paulina|F", "Regan|F", "Manuel|M"]
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def yearly_totals(df, sex, y0, y1):
    """Births of one sex per year, as recorded in the file (index 0 = year y0)."""
    s = df[df["sex"] == sex].groupby("year")["count"].sum()
    return s.reindex(range(y0, y1 + 1), fill_value=0).astype(int).tolist()


def dense_series(df, keys):
    """{key: [first_year, [count per year from first_year to last_year]]}, 0 = not listed."""
    sub = df[df["key"].isin(keys)]
    out = {}
    for key, g in sub.groupby("key", sort=False):
        years = g["year"].to_numpy()
        start, end = int(years.min()), int(years.max())
        arr = np.zeros(end - start + 1, dtype=np.int64)
        arr[years - start] = g["count"].to_numpy()
        out[key] = [start, arr.tolist()]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", default="NY", help="two-letter state code (default NY)")
    p.add_argument("--min-total", type=int, default=100,
                   help="include names with at least this many births since 1880 (default 100)")
    p.add_argument("--default", default=",".join(STARTER),
                   help='starter names, like "Paulina|F,Manuel|M" (F = girls, M = boys)')
    p.add_argument("--national-zip")
    p.add_argument("--state-zip")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out", default=os.path.join("output", "name_explorer.html"))
    a = p.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(here, "explorer_template.html")
    if not os.path.exists(template_path):
        sys.exit(f"Missing {template_path}")
    state = a.state.upper()
    cache = os.path.join(a.data_dir, "ssa")

    nat = read_national(get_zip(NATIONAL_URL, a.national_zip, cache, a.refresh))
    st = read_state(get_zip(STATE_URL, a.state_zip, cache, a.refresh), state)
    nat = nat[nat["sex"].isin(["F", "M"])].copy()
    st = st[st["sex"].isin(["F", "M"])].copy()
    y0, y1 = int(nat["year"].min()), int(nat["year"].max())
    print(f"National: {len(nat):,} rows, {y0}-{y1}. {state}: {len(st):,} rows, from {int(st['year'].min())}.")

    nat["key"] = nat["name"] + "|" + nat["sex"]
    st["key"] = st["name"] + "|" + st["sex"]
    totals = nat.groupby("key")["count"].sum()

    starters = [k.strip() for k in a.default.split(",") if k.strip()]
    keep = set(totals[totals >= a.min_total].index)
    for k in starters:
        if k in totals.index:
            keep.add(k)
        else:
            print(f"Note: starter name {k!r} isn't in the SSA data; skipping it.")
    starters = [k for k in starters if k in totals.index]

    names = sorted(((k, int(totals[k])) for k in keep), key=lambda kv: (-kv[1], kv[0]))
    payload = {
        "y0": y0, "y1": y1,
        "stateCode": state, "stateName": STATE_NAMES.get(state, state),
        "stStart": int(st["year"].min()),
        "minTotal": a.min_total,
        "defaults": starters,
        "names": names,
        "usaTot": {s: yearly_totals(nat, s, y0, y1) for s in ("F", "M")},
        "stTot": {s: yearly_totals(st, s, y0, y1) for s in ("F", "M")},
        "usa": dense_series(nat, keep),
        "st": dense_series(st, keep),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(raw, 9)
    b64 = base64.b64encode(packed).decode("ascii")

    with open(template_path, encoding="utf-8") as f:
        html = f.read()
    if "__PAYLOAD_B64__" not in html:
        sys.exit("Template is missing its __PAYLOAD_B64__ placeholder.")
    html = html.replace("__PAYLOAD_B64__", b64)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{len(names):,} name/sex entries (>= {a.min_total} births). "
          f"Data {len(raw) / 1e6:.1f} MB -> {len(packed) / 1e6:.1f} MB compressed; "
          f"page is {len(html) / 1e6:.1f} MB.")
    print(f"Wrote {a.out}. Open it in your browser.")


if __name__ == "__main__":
    main()
