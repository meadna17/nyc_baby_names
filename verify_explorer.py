#!/usr/bin/env python3
"""Check that output/name_explorer.html shows what the official SSA files say.

It reads the raw SSA zips with its own small parser (it does NOT reuse the code
that built the page), pulls the data back out of the HTML, and compares them.

Usage:
  python verify_explorer.py                 # data checks (fast, standard library only)
  python verify_explorer.py --browser       # also drive the real page in Chromium
  python verify_explorer.py --expect "Susannah|F|1975|152"   # your own spot check (US count)

Exit code is 0 when nothing FAILED, 1 otherwise. WARN lines are worth a look but are not errors.
The --browser checks need:  pip install playwright && playwright install chromium
"""
import argparse
import base64
import csv
import gzip
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

RESULTS = []
BAD_ROWS = {"n": 0}


def _say(tag, name, detail):
    RESULTS.append((tag, name, detail))
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail else ""))


def check(name, cond, detail=""):
    _say("PASS" if cond else "FAIL", name, detail)
    return cond


def warn(name, detail=""):
    _say("WARN", name, detail)


def section(title):
    print(f"\n{title}")


# ---------------------------------------------------------------- raw SSA files
def iter_national(path):
    """Yield (name, sex, year, count) from names.zip (yobYYYY.txt: Name,Sex,Count)."""
    with zipfile.ZipFile(path) as zf:
        for member in sorted(zf.namelist()):
            m = re.search(r"yob(\d{4})\.txt$", member, re.I)
            if not m:
                continue
            year = int(m.group(1))
            with zf.open(member) as fh:
                for row in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                    if not row:
                        continue
                    if len(row) != 3 or not row[2].isdigit():
                        BAD_ROWS["n"] += 1
                        continue
                    yield row[0], row[1], year, int(row[2])


def iter_state(path, state):
    """Yield (name, sex, year, count) from the state's file in namesbystate.zip (ST,sex,year,name,count)."""
    with zipfile.ZipFile(path) as zf:
        member = next((n for n in zf.namelist() if os.path.basename(n).upper() == state + ".TXT"), None)
        if member is None:
            sys.exit(f"{state}.TXT not found inside {path}")
        with zf.open(member) as fh:
            for row in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                if not row:
                    continue
                if len(row) != 5 or not row[2].isdigit() or not row[4].isdigit():
                    BAD_ROWS["n"] += 1
                    continue
                yield row[3], row[1], int(row[2]), int(row[4])


def dense(year_counts):
    """{year: count} -> [first_year, [count per year to last_year]] with 0 for unlisted years."""
    s, e = min(year_counts), max(year_counts)
    arr = [0] * (e - s + 1)
    for y, c in year_counts.items():
        arr[y - s] = c
    return [s, arr]


# ---------------------------------------------------------------- the page
def extract_payload(html):
    m = re.search(r'<script id="payload" type="text/plain">(.*?)</script>', html, re.S)
    if not m or "__PAYLOAD_B64__" in m.group(1):
        sys.exit("No data found inside the HTML (was it built with build_explorer.py?).")
    return json.loads(gzip.decompress(base64.b64decode(m.group(1).strip())).decode("utf-8")), m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", default=os.path.join("output", "name_explorer.html"))
    ap.add_argument("--national-zip", default=os.path.join("data", "ssa", "names.zip"))
    ap.add_argument("--state-zip", default=os.path.join("data", "ssa", "namesbystate.zip"))
    ap.add_argument("--browser", action="store_true", help="also test the rendered page in headless Chromium")
    ap.add_argument("--expect", action="append", default=[], metavar="NAME|S|YEAR|COUNT",
                    help="a US count you looked up yourself, e.g. 'Susannah|F|1975|152' (repeatable)")
    a = ap.parse_args()

    for p in (a.html, a.national_zip, a.state_zip):
        if not os.path.exists(p):
            sys.exit(f"Missing file: {p}")
    html = Path(a.html).read_text(encoding="utf-8")
    D, payload_match = extract_payload(html)
    state = D["stateCode"]
    y0, y1 = D["y0"], D["y1"]
    nyears = y1 - y0 + 1
    names = D["names"]
    name_keys = [k for k, _ in names]
    name_set = set(name_keys)
    print(f"Page: {a.html}  ({len(html) / 1e6:.1f} MB)  |  {len(names):,} names, US {y0}-{y1}, "
          f"{D['stateName']} from {D['stStart']}, cutoff {D['minTotal']} births")

    # ------------------------------------------------ read the raw files (pass 1: totals)
    print("Reading the official files...")
    tot = defaultdict(int)
    ytot = {"F": defaultdict(int), "M": defaultdict(int)}
    sexes, years, min_count = set(), set(), 10 ** 9
    for name, sex, year, c in iter_national(a.national_zip):
        tot[f"{name}|{sex}"] += c
        sexes.add(sex)
        years.add(year)
        min_count = min(min_count, c)
        if sex in ytot:
            ytot[sex][year] += c
    # pass 2: yearly series for the names on the page
    usa_raw = defaultdict(dict)
    for name, sex, year, c in iter_national(a.national_zip):
        k = f"{name}|{sex}"
        if k in name_set:
            usa_raw[k][year] = c
    st_raw = defaultdict(dict)
    st_ytot = {"F": defaultdict(int), "M": defaultdict(int)}
    st_years, st_min = set(), 10 ** 9
    st_sexes = set()
    for name, sex, year, c in iter_state(a.state_zip, state):
        st_raw[f"{name}|{sex}"][year] = c
        st_years.add(year)
        st_sexes.add(sex)
        st_min = min(st_min, c)
        if sex in st_ytot:
            st_ytot[sex][year] += c

    # ------------------------------------------------ 1. basics
    section("1. Basics")
    check("Raw files parsed cleanly", BAD_ROWS["n"] == 0, f"{BAD_ROWS['n']} malformed rows")
    check("US year range matches the files", (y0, y1) == (min(years), max(years)), f"page {y0}-{y1}, files {min(years)}-{max(years)}")
    check("Every year in the range has a file", years == set(range(y0, y1 + 1)))
    check("State start year matches the file", D["stStart"] == min(st_years), f"page {D['stStart']}, file {min(st_years)}")
    check("Only sexes F and M exist in the files", sexes <= {"F", "M"} and st_sexes <= {"F", "M"}, f"{sorted(sexes)} / {sorted(st_sexes)}")

    # ------------------------------------------------ 2. every number round-trips
    section("2. Every number on the page matches the files")
    problems = []
    for k in name_keys:
        if k not in usa_raw:
            problems.append(f"{k}: on the page but not in the national files")
            continue
        if D["usa"].get(k) != dense(usa_raw[k]):
            problems.append(f"{k}: US yearly counts differ")
        if k in st_raw:
            if D["st"].get(k) != dense(st_raw[k]):
                problems.append(f"{k}: {state} yearly counts differ")
        elif k in D["st"]:
            problems.append(f"{k}: page has {state} data but the state file has none")
    stray = (set(D["usa"]) | set(D["st"])) - name_set
    problems += [f"{k}: has a series but is not in the name list" for k in sorted(stray)]
    check(f"US and {state} yearly counts, all {len(name_keys):,} names", not problems,
          "; ".join(problems[:5]) + (f" ... and {len(problems) - 5} more" if len(problems) > 5 else ""))
    n_cells = sum(len(v) for v in usa_raw.values()) + sum(len(v) for k, v in st_raw.items() if k in name_set)
    print(f"        ({n_cells:,} individual name/year counts compared)")

    # ------------------------------------------------ 3. totals
    section("3. Totals reconcile")
    bad = [k for k, t in names if tot.get(k) != t]
    check("Each name's lifetime total (shown in the dropdown) equals the sum in the files", not bad, "; ".join(bad[:5]))
    bad = [k for k, t in names if sum(D["usa"].get(k, [0, []])[1]) != t]
    check("...and equals the sum of its yearly counts on the page", not bad, "; ".join(bad[:5]))
    for s in ("F", "M"):
        want = [ytot[s].get(y, 0) for y in range(y0, y1 + 1)]
        check(f"US births of sex {s} per year (per-100,000 denominator)", D["usaTot"][s] == want)
        want = [st_ytot[s].get(y, 0) for y in range(y0, y1 + 1)]
        check(f"{state} births of sex {s} per year (per-100,000 denominator)", D["stTot"][s] == want)
    check("Name list is sorted by total, biggest first",
          names == sorted(names, key=lambda kv: (-kv[1], kv[0])))

    # ------------------------------------------------ 4. girls and boys stay separate
    section("4. Girls and boys are kept apart")
    check("Every key looks like Name|F or Name|M", all(re.fullmatch(r"[^|]+\|[FM]", k) for k in name_keys))
    both = sorted({k.split("|")[0] for k in name_keys if k.endswith("|F")} &
                  {k.split("|")[0] for k in name_keys if k.endswith("|M")},
                  key=lambda n: -(tot.get(n + "|F", 0) + tot.get(n + "|M", 0)))
    check("A name used for both sexes has two separate entries", len(both) > 0 or len(name_keys) < 50,
          f"{len(both):,} such names, e.g. {', '.join(both[:4])}")
    for n in [d.split("|")[0] for d in D["defaults"]]:
        f, m = tot.get(n + "|F", 0), tot.get(n + "|M", 0)
        if f and m:
            print(f"        {n}: {f:,} girls and {m:,} boys, listed separately")

    # ------------------------------------------------ 5. missing is not zero
    section("5. 'Not listed' is shown as under 5, never as zero")
    check("Smallest count in the national files is 5 (nothing under 5 is published)", min_count >= 5, f"smallest = {min_count}")
    check(f"Smallest count in the {state} file is 5", st_min >= 5, f"smallest = {st_min}")
    gappy = [k for k in D["defaults"] if k in D["st"] and 0 in D["st"][k][1]]
    for k in gappy:
        s0, arr = D["st"][k]
        print(f"        {k}: unlisted (under 5) in {arr.count(0)} of {len(arr)} {state} years, shown as gaps")
    first_state_series = min((D["st"][k][0] for k in D["st"]), default=D["stStart"])
    check(f"No {state} series starts before the state files do", first_state_series >= D["stStart"])

    # ------------------------------------------------ 6. which names were left out
    section("6. The cutoff is applied correctly")
    starters = set(D["defaults"])
    missing = [k for k, t in tot.items() if t >= D["minTotal"] and k not in name_set and k.split("|")[1] in ("F", "M")]
    check(f"No name with at least {D['minTotal']} births is missing", not missing, "; ".join(missing[:5]))
    extras = [k for k, t in names if t < D["minTotal"] and k not in starters]
    check("Names below the cutoff are only your starter names", not extras, "; ".join(extras[:5]))
    below = sorted((t for k, t in tot.items() if t < D["minTotal"] and k not in name_set), reverse=True)
    if below:
        print(f"        largest name left out: {below[0]} births; rebuild with --min-total 5 to include all names")
    odd = [k for k in name_keys if not re.fullmatch(r"[A-Za-z]+\|[FM]", k)]
    if odd:
        warn("Names with characters other than letters", ", ".join(odd[:8]))
    else:
        print("        all names are plain letters (nothing to escape in the page)")

    # ------------------------------------------------ 7. things you can check by hand
    section("7. Spot-check table: compare these with the page (hover the peak year)")
    rows = []
    for k in D["defaults"]:
        if k not in usa_raw:
            continue
        sx = k.split("|")[1]
        peak = max(usa_raw[k], key=lambda y: (usa_raw[k][y], -y))
        for label, year in (("peak", peak), ("latest", y1)):
            c = usa_raw[k].get(year)
            rate = (c / ytot[sx][year] * 1e5) if c else None
            sc = st_raw.get(k, {}).get(year)
            srate = (sc / st_ytot[sx][year] * 1e5) if sc and st_ytot[sx].get(year) else None
            rows.append((k.replace("|F", " (girls)").replace("|M", " (boys)"), label, year,
                         f"{c:,}" if c else "under 5", f"{rate:.1f}" if rate else "-",
                         f"{sc:,}" if sc else "under 5", f"{srate:.1f}" if srate else "-"))
    hdr = ("Name", "", "Year", "US babies", "US /100k", f"{state} babies", f"{state} /100k")
    widths = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(len(hdr))]
    for r in [hdr] + rows:
        print("        " + "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)))
    # known values quoted earlier in the project (informational: SSA can revise files)
    for key, year, want in (("Susannah|F", 1975, 152),):
        got = usa_raw.get(key, {}).get(year)
        if got is not None and got != want:
            warn(f"{key} {year}: files say {got}, earlier run said {want}", "SSA may have revised the files")
    for e in a.expect:
        try:
            n, s, y, c = e.split("|")
            key, y, c = f"{n}|{s.upper()}", int(y), int(c)
        except ValueError:
            sys.exit(f"--expect needs NAME|S|YEAR|COUNT, got {e!r}")
        from_files = usa_raw.get(key, {}).get(y)
        from_page = D["usa"].get(key)
        page_val = from_page[1][y - from_page[0]] if from_page and 0 <= y - from_page[0] < len(from_page[1]) else None
        check(f"Your spot check {key} {y} = {c}", from_files == c and page_val == c,
              f"files {from_files}, page {page_val}")

    # ------------------------------------------------ 8. the HTML file is self-contained
    section("8. The HTML file is self-contained (safe to email)")
    rest = html[:payload_match.start()] + html[payload_match.end():]
    leaks = []
    patterns = {
        "external script/stylesheet": r"<script[^>]+\bsrc\s*=|<link\b|@import|url\(\s*[\"']?https?:",
        "link to another site": r"(?:src|href|action)\s*=\s*[\"']\s*(?:https?:)?//",
        "network call": r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|importScripts",
    }
    for label, pat in patterns.items():
        if re.search(pat, rest, re.I):
            leaks.append(label)
    check("No outside requests, scripts, fonts or links", not leaks, ", ".join(leaks))
    check("Data placeholder was replaced", "__PAYLOAD_B64__" not in html)
    mb = len(html.encode("utf-8")) / 1e6
    if mb > 20:
        warn("File is large for email", f"{mb:.1f} MB (Gmail limit 25 MB); zip it or raise --min-total")
    else:
        print(f"        file size {mb:.1f} MB")

    # ------------------------------------------------ 9. browser
    if a.browser:
        section("9. The rendered page (real browser)")
        browser_checks(a.html, D, usa_raw, st_raw, ytot, st_ytot, tot)

    # ------------------------------------------------ summary
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    npass = sum(1 for r in RESULTS if r[0] == "PASS")
    print(f"\n{'ALL CHECKS PASSED' if not fails else 'SOME CHECKS FAILED'}: "
          f"{npass} passed, {len(fails)} failed, {len(warns)} warnings.")
    for _, name, detail in fails:
        print(f"  FAILED: {name} {detail}")
    sys.exit(1 if fails else 0)


# ---------------------------------------------------------------- browser checks
def browser_checks(html_path, D, usa_raw, st_raw, ytot, st_ytot, tot):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("Browser checks skipped", "pip install playwright && playwright install chromium")
        return
    y0, y1 = D["y0"], D["y1"]
    url = Path(html_path).resolve().as_uri()
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:  # no Chromium installed
        warn("Browser checks skipped", f"could not start Chromium: {str(exc).splitlines()[0]}")
        return
    try:
        ctx = browser.new_context(viewport={"width": 1100, "height": 900}, locale="en-US")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def open_page(keys, extra=""):
            page.goto("about:blank")
            page.goto(url + "#n=" + quote(",".join(keys), safe="|,") + extra)
            page.wait_for_selector("#chips .chip")

        def label(k):
            return k.split("|")[0] + " (" + ("girls" if k.endswith("|F") else "boys") + ")"

        keys = [k for k in D["defaults"] if k in usa_raw][:4]

        # search box: exact name first, with the right totals
        mism = []
        for k in keys:
            n = k.split("|")[0]
            open_page([keys[0]])
            page.fill("#q", n)
            page.wait_for_selector("#sug li")
            first_two = page.eval_on_selector_all("#sug li[data-k]", "ls => ls.map(l => [l.dataset.k, l.innerText])")
            hit = [t for kk, t in first_two if kk == k]
            if k == keys[0]:
                continue  # already selected, hidden from suggestions by design
            if not hit or f"{tot[k]:,} births" not in hit[0].replace("\n", " "):
                mism.append(k)
        check("Search finds each name and shows the right lifetime total", not mism, ", ".join(mism))

        # decade tables
        decades = list(range((y0 // 10) * 10, y1 + 1, 10))
        for k in keys:
            open_page([k])
            page.evaluate("document.querySelector('details').open = true")
            tables = page.eval_on_selector_all(
                "#tables table",
                "ts => ts.map(t => [...t.querySelectorAll('tbody tr')].map(r => [...r.children].map(c => c.textContent.trim())))")
            for tname, series in (("US", usa_raw.get(k, {})), (D["stateCode"], st_raw.get(k, {}))):
                tidx = 0 if tname == "US" else 1
                want = []
                total = 0
                for d in decades:
                    vals = [series[y] for y in range(max(d, y0), min(d + 9, y1) + 1) if y in series]
                    want.append(f"{sum(vals):,}" if vals else "–")
                    total += sum(vals)
                want = [label(k)] + want + [f"{total:,}"]
                got = tables[tidx][0] if len(tables) > tidx and tables[tidx] else None
                check(f"Decade table, {tname}, {label(k)}", got == want,
                      "" if got == want else f"page {got} vs files {want}")

        # hover tooltips, both panels, counts and per-100k
        def expect(panel, k, year, metric):
            series = usa_raw.get(k, {}) if panel == "usa" else st_raw.get(k, {})
            start = y0 if panel == "usa" else D["stStart"]
            if year < start:
                return ("text", "no data")
            c = series.get(year)
            if c is None:
                return ("text", "under 5 (not listed)")
            if metric == "count":
                return ("text", f"{c:,} babies")
            denom = (ytot if panel == "usa" else st_ytot)[k.split("|")[1]][year]
            return ("rate", c / denom * 1e5, c)

        def matches(tip, exp):
            if exp[0] == "text":
                return exp[1] in tip
            m = re.search(r"([\d,.]+) per 100k \(([\d,]+) babies\)", tip)
            return bool(m) and abs(float(m.group(1).replace(",", "")) - exp[1]) <= 0.051 \
                and int(m.group(2).replace(",", "")) == exp[2]

        for metric in ("count", "rate"):
            bad, n = [], 0
            for k in keys[:3]:
                open_page([k], "" if metric == "count" else "&m=rate")
                s = usa_raw[k]
                peak = max(s, key=lambda y: (s[y], -y))
                gap = next((y for y in range(min(s), y1 + 1) if y not in s), None)
                test_years = sorted({peak, y1, y0 + 5, D["stStart"] - 3, D["stStart"] + 20} |
                                    ({gap} if gap else set()))
                test_years = [y for y in test_years if y0 <= y <= y1]
                box = page.locator("#usa .hit").bounding_box()
                for year in test_years:
                    x = box["x"] + (year - y0) / (y1 - y0) * box["width"]
                    page.mouse.move(x, box["y"] + box["height"] / 2)
                    page.wait_for_timeout(30)
                    for panel in ("usa", "st"):
                        tip = page.inner_text(f"#tip-{panel}")
                        n += 1
                        if not (f"{year}" in tip.split("\n")[0] and matches(tip, expect(panel, k, year, metric))):
                            bad.append(f"{label(k)} {year} {panel}: page says {tip.replace(chr(10), ' | ')!r}")
            check(f"Hover values match the files ({'babies' if metric == 'count' else 'per 100,000'}), {n} points",
                  not bad, "; ".join(bad[:3]))

        # girls and boys of the same name never merge
        both = next((k.split("|")[0] for k in keys if k.split("|")[0] + "|M" in usa_raw and k.split("|")[0] + "|F" in usa_raw), None)
        if both is None:
            both = next((n for n in (k.split("|")[0] for k in D["defaults"])
                         if tot.get(n + "|F") and tot.get(n + "|M")), None)
        if both:
            open_page([both + "|F", both + "|M"])
            chips = page.eval_on_selector_all("#chips .chip", "cs => cs.map(c => c.innerText.replace('×','').trim())")
            check(f"{both} as a girl and as a boy are two separate lines", len(chips) == 2 and chips[0] != chips[1], str(chips))

        check("No JavaScript errors in the console", not errors, "; ".join(errors[:3]))
    finally:
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
