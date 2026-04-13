You need to write a code which gets the last 2 years of data from dawn.com

https://www.dawn.com/latest-news/YYYY-MM-DD

i want it from 1st January 2023 to 1st January 2026

Use oxylabs to ensure that you are not hitting the limit, i will give you the oxylabs proxy url.

all code must be clean and a simple python script saving data in a csv file like this.

data_1.csv and in csv file it have the data and the news article

onee csv file can contain at max 10000 rows only

## Implementation

Use `scrape_dawn.py`.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run with provided Oxylabs credentials

```bash
python scrape_dawn.py \
  --start-date 2023-01-01 \
  --end-date 2026-01-01 \
  --proxy-username "ibadski_8WEQw" \
  --proxy-password "Ibad1234567_"
```

The script writes chunked CSV files (`data_1.csv`, `data_2.csv`, ...) with max 10,000 rows per file.
