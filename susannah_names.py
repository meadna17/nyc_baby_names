#!/usr/bin/env python3
"""How popular is the name Susannah in NYC?

Pulls the NYC Health Department "Popular Baby Names" dataset (NYC Open Data,
Socrata dataset id 25th-nujf), cleans it, and makes two charts plus a summary:

  1. Births per year for Susannah and similar spellings
  2. Susannah births per year, split by the dataset's ethnicity groups

Usage:
  python susannah_names.py                       # fetch live data from the API
  python susannah_names.py --csv names.csv       # use a CSV you downloaded
  python susannah_names.py --name Susannah --variants Susanna,Susana
  python susannah_names.py --gender all          # include boys' rows too

Optional: set NYC_APP_TOKEN (free, from NYC Open Data) for higher rate limits.

Note: the dataset has NO neighborhood/borough column, so this can't break
results down by neighborhood.
"""
import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib.ticker import MaxNLocator

DATASET_ID = "25th-nujf"
API_URL = f"https://data.cityofnewyork.us/resource/{DATASET_ID}.json"
DATASET_PAGE = f"https://data.cityofnewyork.us/d/{DATASET_ID}"
DEFAULT_VARIANTS = ["Susanna", "Susana", "Suzanna", "Suzannah"]

# Chart styling: fixed categorical order, quiet grid, text in neutral ink.
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#dddcd8"
ETH_ORDER = [
    "Asian & Pacific Islander",
    "Black Non-Hispanic",
    "Hispanic",
    "White Non-Hispanic",
]
ETH_COLORS = dict(zip(ETH_ORDER, SERIES_COLORS))  # color follows the group, always


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def fetch_from_api(names):
    """Query the Socrata (SODA) API for just the names we care about."""
    quoted = ",".join("'" + n.upper().replace("'", "''") + "'" for n in names)
    params = {"$where": f"upper(nm) in ({quoted})", "$limit": 50000}
    headers = {}
    token = os.environ.get("NYC_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    try:
        resp = requests.get(API_URL, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(
            f"Could not fetch from the NYC Open Data API: {exc}\n"
            f"Workaround: download the CSV from {DATASET_PAGE} "
            f"(Export > CSV) and re-run with --csv path/to/file.csv"
        )
    return pd.DataFrame(resp.json())


def load_csv(path):
    return pd.read_csv(path)


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------
def pick(df, candidates, label):
    for c in candidates:
        if c in df.columns:
            return c
    sys.exit(f"Could not find a {label} column. Columns present: {list(df.columns)}")


def norm_ethnicity(value):
    """Collapse the inconsistent labels used across years into 4 groups."""
    u = str(value).upper()
    if "ASIAN" in u or "PACIFIC" in u:
        return "Asian & Pacific Islander"
    if "BLACK" in u:
        return "Black Non-Hispanic"
    if "WHITE" in u:
        return "White Non-Hispanic"
    if "HISP" in u:  # checked after BLACK/WHITE because "NON HISP" contains HISP
        return "Hispanic"
    return str(value).title()


def clean(raw):
    df = raw.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    year = pick(df, ["brth_yr", "year_of_birth", "birth_year", "year"], "birth year")
    gender = pick(df, ["gndr", "gender", "sex"], "gender")
    eth = pick(df, ["ethcty", "ethnicity"], "ethnicity")
    name = pick(df, ["nm", "childs_first_name", "child_s_first_name", "name"], "name")
    count = pick(df, ["cnt", "count"], "count")
    rank_col = next((c for c in ["rnk", "rank"] if c in df.columns), None)

    out = pd.DataFrame(
        {
            "year": pd.to_numeric(df[year], errors="coerce"),
            "gender": df[gender].astype(str).str.strip().str.upper().str[0],
            "ethnicity": df[eth].map(norm_ethnicity),
            "name": df[name].astype(str).str.strip().str.title(),
            "count": pd.to_numeric(df[count], errors="coerce"),
            "rank": pd.to_numeric(df[rank_col], errors="coerce") if rank_col else float("nan"),
        }
    )
    out = out.dropna(subset=["year", "count"])
    out["year"] = out["year"].astype(int)
    out["count"] = out["count"].astype(int)

    # Some years list the same record twice (e.g. under two spellings of the
    # same ethnicity label). Once labels are normalized, exact repeats collapse.
    before = len(out)
    out = out.drop_duplicates(subset=["year", "gender", "ethnicity", "name", "count"])
    dropped = before - len(out)
    if dropped:
        print(f"Removed {dropped} duplicate row(s).")

    # Anything still sharing a key has conflicting counts; flag it, don't hide it.
    key = ["year", "gender", "ethnicity", "name"]
    conflicts = out[out.duplicated(subset=key, keep=False)]
    if not conflicts.empty:
        print(f"WARNING: {len(conflicts)} rows share a key but differ in count; "
              "they will be summed. Inspect the cleaned CSV if this matters.")
    return out.sort_values(key).reset_index(drop=True)


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def style_axes(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))


def new_fig(w=9, h=5):
    fig, ax = plt.subplots(figsize=(w, h), facecolor=SURFACE)
    style_axes(ax)
    return fig, ax


def plot_spellings(df, main, variants, path):
    order = [n for n in [main] + variants if n in set(df["name"])]
    if not order:
        print("No rows found for any of the spellings; skipping spelling chart.")
        return
    years = range(df["year"].min(), df["year"].max() + 1)
    wide = df.groupby(["year", "name"])["count"].sum().unstack("name").reindex(years)

    fig, ax = new_fig()
    for i, name in enumerate(order):
        color = SERIES_COLORS[i % len(SERIES_COLORS)]
        s = wide[name]
        ax.plot(s.index, s.values, color=color, linewidth=2, marker="o",
                markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label=name)
        last = s.dropna()
        if not last.empty:
            ax.annotate(name, (last.index[-1], last.iloc[-1]), xytext=(8, 0),
                        textcoords="offset points", color=INK, fontsize=9, va="center")
    ax.set_title(f"{main} and similar spellings: NYC births per year",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=30)
    ax.set_ylabel("Babies", color=MUTED)
    ax.set_xticks(list(years))
    ax.tick_params(axis="x", labelrotation=45)
    ax.set_xlim(min(years) - 0.5, max(years) + 1.8)
    if len(order) >= 2:
        ax.legend(frameon=False, labelcolor=INK, loc="lower left",
                  bbox_to_anchor=(0, 1.0), ncol=len(order))
    fig.text(0.01, 0.01,
             "A gap means the name wasn't listed that year (likely under the dataset's "
             "privacy cutoff), not necessarily zero births.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_ethnicity(main_df, main, path_by_year, path_total):
    years = list(range(main_df["year"].min(), main_df["year"].max() + 1))
    piv = (main_df.groupby(["year", "ethnicity"])["count"].sum()
           .unstack("ethnicity", fill_value=0).reindex(years, fill_value=0))
    groups = [g for g in ETH_ORDER if g in piv.columns] + \
             [g for g in piv.columns if g not in ETH_ORDER]

    fig, ax = new_fig()
    bottom = pd.Series(0, index=piv.index, dtype=float)
    for g in groups:
        ax.bar(piv.index, piv[g], bottom=bottom, label=g, width=0.8,
               color=ETH_COLORS.get(g, "#8a8984"), edgecolor=SURFACE, linewidth=1.5)
        bottom += piv[g]
    ax.set_title(f"{main} births per year, by ethnicity group",
                 loc="left", color=INK, fontsize=13, fontweight="bold", pad=30)
    ax.set_ylabel("Babies", color=MUTED)
    ax.set_xticks(years)
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend(frameon=False, labelcolor=INK, loc="lower left",
              bbox_to_anchor=(0, 1.0), ncol=len(groups), fontsize=9)
    fig.text(0.01, 0.01, "Ethnicity groups are those used by the NYC Health Department's dataset.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path_by_year, dpi=150, facecolor=SURFACE)
    plt.close(fig)

    totals = piv.sum().reindex(groups)
    fig, ax = new_fig(8, 3.6)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.barh(groups[::-1], totals.values[::-1], height=0.55,
            color=[ETH_COLORS.get(g, "#8a8984") for g in groups[::-1]])
    grand = totals.sum()
    for i, v in enumerate(totals.values[::-1]):
        ax.annotate(f"{int(v)}  ({v / grand:.0%})", (v, i), xytext=(6, 0),
                    textcoords="offset points", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, totals.max() * 1.25)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(f"{main}: total births in the dataset, by ethnicity group",
                 loc="left", color=INK, fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path_total, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def summarize(df, main):
    m = df[df["name"] == main]
    if m.empty:
        print(f"\nNo rows for '{main}' in this data.")
        return
    print(f"\n=== {main} in NYC ({df['year'].min()}-{df['year'].max()} in this data) ===")
    by_year = m.groupby("year")["count"].sum()
    print("\nBirths per year:")
    print(by_year.to_string())
    print(f"\nTotal: {by_year.sum()} | Peak year: {by_year.idxmax()} ({by_year.max()})")
    missing = [y for y in range(df["year"].min(), df["year"].max() + 1) if y not in by_year.index]
    if missing:
        print(f"Years not listed (likely below the privacy cutoff): {missing}")
    eth = m.groupby("ethnicity")["count"].sum().sort_values(ascending=False)
    print("\nBy ethnicity group (all years):")
    for g, v in eth.items():
        print(f"  {g}: {v} ({v / eth.sum():.0%})")
    if m["rank"].notna().any():
        best = m.loc[m.groupby("ethnicity")["rank"].idxmin()]
        print("\nBest (lowest-number) rank reached within each group:")
        for _, r in best.iterrows():
            print(f"  {r['ethnicity']}: #{int(r['rank'])} in {r['year']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="Susannah")
    p.add_argument("--variants", default=",".join(DEFAULT_VARIANTS),
                   help="comma-separated similar spellings to compare")
    p.add_argument("--gender", default="F", choices=["F", "M", "all"])
    p.add_argument("--csv", help="use a downloaded CSV instead of calling the API")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--data-dir", default="data")
    a = p.parse_args()

    main_name = a.name.strip().title()
    variants = [v.strip().title() for v in a.variants.split(",") if v.strip()]
    variants = [v for v in variants if v != main_name]
    names = [main_name] + variants

    raw = load_csv(a.csv) if a.csv else fetch_from_api(names)
    if raw.empty:
        sys.exit("The query returned no rows.")
    df = clean(raw)
    df = df[df["name"].isin(names)]
    if a.gender != "all":
        df = df[df["gender"] == a.gender]
    if df.empty:
        sys.exit("No matching rows after filtering. Try --gender all or different spellings.")

    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.data_dir, exist_ok=True)
    df.to_csv(os.path.join(a.data_dir, "names_clean.csv"), index=False)

    plot_spellings(df, main_name, variants, os.path.join(a.out_dir, "spellings_by_year.png"))
    main_df = df[df["name"] == main_name]
    if not main_df.empty:
        plot_ethnicity(main_df, main_name,
                       os.path.join(a.out_dir, "ethnicity_by_year.png"),
                       os.path.join(a.out_dir, "ethnicity_total.png"))
    summarize(df, main_name)
    print(f"\nSaved cleaned data to {a.data_dir}/ and charts to {a.out_dir}/")


if __name__ == "__main__":
    main()
