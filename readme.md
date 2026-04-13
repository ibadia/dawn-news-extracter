You need to write a code which gets the last 2 years of data from dawn.com

https://www.dawn.com/latest-news/YYYY-MM-DD

i want it from 1st January 2023 to 1st January 2026

Use oxylabs to ensure that you are not hitting the limit, i will give you the oxylabs proxy url.

all code must be clean and a simple python script saving data in a csv file like this.

data_1.csv and in csv file it have the data and the news article

onee csv file can contain at max 10000 rows only

---

## Implemented script

- Script: `scrape_dawn.py`
- Dependencies: `requests`, `beautifulsoup4` (listed in `requirements.txt`)

### Install

```bash
python3 -m pip install -r requirements.txt
```

### Run (default date range is 2023-01-01 to 2026-01-01)

```bash
python3 scrape_dawn.py \
  --proxy-username "<YOUR_OXYLABS_USERNAME>" \
  --proxy-password "<YOUR_OXYLABS_PASSWORD>"
```

### Run with explicit Oxylabs proxy URL

```bash
python3 scrape_dawn.py \
  --proxy-username "<YOUR_OXYLABS_USERNAME>" \
  --proxy-password "<YOUR_OXYLABS_PASSWORD>" \
  --proxy-url "http://<user>:<pass>@pr.oxylabs.io:7777"
```

### Output

- Files are written as `data_1.csv`, `data_2.csv`, ...
- Each file has at most `10000` rows.
- CSV columns:
  - `date`
  - `title`
  - `article_url`
  - `article_text`
