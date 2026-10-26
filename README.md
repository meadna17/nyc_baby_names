# Susannah in NYC

How popular is the name **Susannah** in New York City, and which ethnicity groups
does it appear in? Built on the NYC Health Department's
[Popular Baby Names](https://data.cityofnewyork.us/d/25th-nujf) dataset (NYC Open Data).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python susannah_names.py
```

This downloads the whole dataset from the NYC Open Data API (cached in `data/raw_download.csv`,
use `--refresh` to re-download), cleans it, filters to Susannah and similar spellings, and writes:

- `data/names_clean.csv`: the cleaned rows for Susannah and similar spellings
- `output/spellings_by_year.png`: births per year, Susannah vs. Susanna, Susana, Suzanna, Suzannah
- `output/ethnicity_by_year.png`: Susannah births per year, stacked by ethnicity group
- `output/ethnicity_total.png`: total share by ethnicity group
- a text summary in the terminal (peak year, ethnicity shares, best rank)

Options: `--name`, `--variants Susanna,Susana`, `--gender F|M|all`, `--csv file.csv`
(use a CSV downloaded from the dataset page instead of the API).

Optional: get a free app token from NYC Open Data and `export NYC_APP_TOKEN=...` for higher rate limits.

## Caveats

- **No neighborhoods.** The dataset has only year, gender, ethnicity group, name, count, and rank.
  Neighborhood-level questions need a different source (see ideas below).
- **Missing years are not zeros.** Names with very few births don't appear in some years,
  and a rare spelling may be missing entirely. If a name isn't found, the script lists the
  similarly-spelled names that are.
- **Ethnicity labels** changed across years; the script folds them into four groups
  (Asian & Pacific Islander, Black Non-Hispanic, Hispanic, White Non-Hispanic).
- Ranks near a count of ~10 can swing from year to year (noted on the dataset page).

## Ideas for next steps

- Compare against national data from the Social Security Administration's baby names files.
- Measure how "unusual" the name is: its rank vs. the number of distinct names each year.
- For neighborhood-level views, look at Census/ACS demographics by ZIP or neighborhood
  tabulation area and compare, keeping in mind that names aren't broken out by location.
