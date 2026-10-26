#!/usr/bin/env python3
"""How popular is Susannah across the whole US? (Social Security Administration data)

Downloads the SSA's public baby-name files, then charts:

  1. US births per year (since 1880) for Susannah and similar spellings
  2. Susannah per 100,000 girls born: the US vs. one state (default New York)

Usage:
  python ssa_names.py                        # download and run
  python ssa_names.py --state NY --name Susannah
  python ssa_names.py --national-zip names.zip --state-zip namesbystate.zip
                                              # use zips you downloaded yourself

Data: https://www.ssa.gov/oact/babynames/limits.html
  - National file: one yobYYYY.txt per year, lines like  Name,F,count
  - State file:    one XX.TXT per state, lines like     XX,F,year,Name,count
SSA leaves out a name when it would reveal a count below 5 in a geographic area,
so very rare names are missing. "Per 100,000" uses the births in the file itself,
which slightly undercounts true births (the names under that cutoff are absent).
SSA data has no ethnicity or city detail.
"""
import argparse
import io
import os
import re
import sys
import zipfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib.ticker import FuncFormatter

from susannah_names import (DEFAULT_VARIANTS, GRID, INK, MUTED, SERIES_COLORS,
                            SURFACE, new_fig)

NATIONAL_URL = "https://www.ssa.gov/oact/babynames/names.zip"
STATE_URL = "https://www.ssa.gov/oact/babynames/state/namesbystate.zip"
USER_AGENT = "susannah-names-learning-project/1.0 (personal, non-commercial)"
COMMA = FuncFormatter(lambda v, _: f"{int(v):,}")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def get_zip(url, local_path, cache_dir, refresh):
    """Return a path to the zip: the user's own file, a cached download, or a fresh one."""
    if local_path:
        if not os.path.exists(local_path):
            sys.exit(f"File not found: {local_path}")
        return local_path
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, os.path.basename(url))
    if os.path.exists(dest) and not refresh:
        print(f"Using cached {dest} (use --refresh to re-download).")
        return dest
    print(f"Downloading {url} ...")
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest + ".part", "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        os.replace(dest + ".part", dest)
    except requests.RequestException as exc:
        sys.exit(
            f"Could not download {url}: {exc}\n"
            "Workaround: download the zip files from "
            "https://www.ssa.gov/oact/babynames/limits.html in your browser, then run\n"
            "  python ssa_names.py --national-zip path\\to\\names.zip "
            "--state-zip path\\to\\namesbystate.zip"
        )
    return dest


def read_national(zip_path):
    """All yobYYYY.txt files -> DataFrame[year, name, sex, count]."""
    frames = []
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            m = re.search(r"yob(\d{4})\.txt$", member, re.IGNORECASE)
            if not m:
                continue
            with z.open(member) as f:
                df = pd.read_csv(f, header=None, names=["name", "sex", "count"])
            df["year"] = int(m.group(1))
            frames.append(df)
    if not frames:
        sys.exit("No yobYYYY.txt files found in the national zip. Is it the right file?")
    out = pd.concat(frames, ignore_index=True)
    out["name"] = out["name"].astype(str).str.strip().str.title()
    out["sex"] = out["sex"].astype(str).str.strip().str.upper()
    return out


def read_state(zip_path, state):
    """The XX.TXT file for one state -> DataFrame[year, name, sex, count]."""
    with zipfile.ZipFile(zip_path) as z:
        target = next((n for n in z.namelist()
                       if os.path.basename(n).upper() == f"{state.upper()}.TXT"), None)
        if target is None:
            sample = sorted(os.path.basename(n) for n in z.namelist())[:12]
            sys.exit(f"No file for state '{state}' in the state zip. Files include: {sample}")
        with z.open(target) as f:
            df = pd.read_csv(f, header=None, names=["state", "sex", "year", "name", "count"])
    df["name"] = df["name"].astype(str).str.strip().str.title()
    df["sex"] = df["sex"].astype(str).str.strip().str.upper()
    return df[["year", "name", "sex", "count"]]


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def per_100k(df, name, sex):
    """Births of `name` per 100,000 recorded births of that sex, by year."""
    s = df[df["sex"] == sex]
    total = s.groupby("year")["count"].sum()
    mine = s[s["name"] == name].groupby("year")["count"].sum()
    return (mine / total * 100_000).dropna()


def national_rank(df, name, sex):
    """Approximate rank by year (1 = most common), using counts within the sex."""
    s = df[df["sex"] == sex].copy()
    s["rank"] = s.groupby("year")["count"].rank(method="min", ascending=False)
    return s[s["name"] == name].set_index("year")["rank"].astype(int)


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def plot_spellings(nat, names, sex, path):
    s = nat[(nat["sex"] == sex) & (nat["name"].isin(names))]
    years = range(int(nat["year"].min()), int(nat["year"].max()) + 1)
    wide = s.groupby(["year", "name"])["count"].sum().unstack("name").reindex(years)
    order = [n for n in names if n in wide.columns]
    fig, ax = new_fig(10, 5)
    for i, n in enumerate(order):
        series = wide[n]
        ax.plot(series.index, series.values, color=SERIES_COLORS[i % len(SERIES_COLORS)],
                linewidth=2, label=n)
        last = series.dropna()
        if not last.empty:
            ax.annotate(n, (last.index[-1], last.iloc[-1]), xytext=(6, 0),
                        textcoords="offset points", color=INK, fontsize=9, va="center")
    ax.yaxis.set_major_formatter(COMMA)
    ax.set_xlim(min(years), max(years) + 12)
    ax.set_title(f"{names[0]} and similar spellings: US births per year",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=30)
    ax.set_ylabel("Babies", color=MUTED)
    if len(order) >= 2:
        ax.legend(frameon=False, labelcolor=INK, loc="lower left",
                  bbox_to_anchor=(0, 1.0), ncol=len(order))
    fig.text(0.01, 0.01, "Source: Social Security Administration. Names with fewer than 5 "
             "births in an area are left out.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_vs_state(us, st, name, state, path):
    fig, ax = new_fig(10, 5)
    for i, (label, series) in enumerate([("United States", us), (state.upper(), st)]):
        ax.plot(series.index, series.values, color=SERIES_COLORS[i], linewidth=2, label=label)
        ax.annotate(label, (series.index[-1], series.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", color=INK, fontsize=9, va="center")
    ax.set_xlim(min(us.index.min(), st.index.min()), max(us.index.max(), st.index.max()) + 12)
    ax.set_title(f"{name} per 100,000 girls born: US vs. {state.upper()}",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=30)
    ax.set_ylabel("Per 100,000 girls", color=MUTED)
    ax.legend(frameon=False, labelcolor=INK, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=2)
    fig.text(0.01, 0.01, "Source: Social Security Administration. Rates use births recorded in "
             "the files, which leave out names below the privacy cutoff.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="Susannah")
    p.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    p.add_argument("--sex", default="F", choices=["F", "M"])
    p.add_argument("--state", default="NY", help="two-letter state code to compare (default NY)")
    p.add_argument("--national-zip", help="path to a names.zip you downloaded")
    p.add_argument("--state-zip", help="path to a namesbystate.zip you downloaded")
    p.add_argument("--refresh", action="store_true", help="re-download cached zips")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--data-dir", default="data")
    a = p.parse_args()

    name = a.name.strip().title()
    variants = [v.strip().title() for v in a.variants.split(",") if v.strip() and v.strip().title() != name]
    names = [name] + variants
    cache = os.path.join(a.data_dir, "ssa")
    os.makedirs(a.out_dir, exist_ok=True)

    nat = read_national(get_zip(NATIONAL_URL, a.national_zip, cache, a.refresh))
    print(f"National file: {len(nat):,} rows, {int(nat['year'].min())}-{int(nat['year'].max())}")
    print("Sample rows:", nat.head(2).to_dict("records"))

    found = nat[(nat["sex"] == a.sex) & (nat["name"].isin(names))]
    if found.empty:
        near = sorted(n for n in nat[nat["sex"] == a.sex]["name"].unique()
                      if n.lower().startswith(name[:3].lower()))
        sys.exit(f"None of {names} appear in the national data. Names starting with "
                 f"'{name[:3]}': {near[:40]}")

    plot_spellings(nat, names, a.sex, os.path.join(a.out_dir, "ssa_spellings_by_year.png"))

    # --- summary
    mine = nat[(nat["sex"] == a.sex) & (nat["name"] == name)].groupby("year")["count"].sum()
    print(f"\n=== {name} in the US (SSA, {int(nat['year'].min())}-{int(nat['year'].max())}) ===")
    if mine.empty:
        print(f"'{name}' itself is not in the national data; other spellings were charted.")
        print(f"Spellings found: {sorted(found['name'].unique())}")
    else:
        latest = int(nat["year"].max())
        ranks = national_rank(nat, name, a.sex)
        print(f"Total babies on record: {int(mine.sum()):,}")
        print(f"Peak year: {int(mine.idxmax())} ({int(mine.max()):,} babies, rank #{ranks.get(mine.idxmax(), '?')})")
        print(f"Latest year ({latest}): {int(mine.get(latest, 0)):,} babies"
              + (f", rank #{ranks[latest]}" if latest in ranks.index else " (not listed)"))
        by_decade = mine.groupby((mine.index // 10) * 10).sum()
        print("\nBabies per decade:")
        for dec, v in by_decade.items():
            print(f"  {dec}s: {int(v):,}")
        print("(Ranks are computed from the file's counts; they approximate SSA's published ranks.)")

        # --- compare to the state
        st_zip = get_zip(STATE_URL, a.state_zip, cache, a.refresh)
        st = read_state(st_zip, a.state)
        us_rate = per_100k(nat, name, a.sex)
        st_rate = per_100k(st, name, a.sex)
        if st_rate.empty:
            print(f"\n'{name}' does not appear in the {a.state.upper()} file.")
        else:
            plot_vs_state(us_rate, st_rate, name, a.state,
                          os.path.join(a.out_dir, "ssa_state_vs_us.png"))
            yrs = [y for y in (1950, 1980, 2000, 2010, latest) if y in st_rate.index and y in us_rate.index]
            print(f"\nPer 100,000 {a.sex} births, {a.state.upper()} vs. US:")
            for y in yrs:
                print(f"  {y}: {a.state.upper()} {st_rate[y]:.1f} | US {us_rate[y]:.1f}")
            st_total = st[(st['sex'] == a.sex) & (st['name'] == name)]['count'].sum()
            print(f"{a.state.upper()} total babies on record: {int(st_total):,}")

    print(f"\nCharts saved to {a.out_dir}/")


if __name__ == "__main__":
    main()
