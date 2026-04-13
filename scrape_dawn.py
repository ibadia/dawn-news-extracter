#!/usr/bin/env python3
"""Scrape Dawn latest-news archives and save article data into chunked CSV files.

Requirements fulfilled from readme.md:
- Date range from 2023-01-01 to 2026-01-01
- Uses Oxylabs proxy to reduce rate-limiting risk
- Saves output into data_1.csv, data_2.csv, ...
- Maximum 10,000 rows per CSV file
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set

import requests
from bs4 import BeautifulSoup
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_ARCHIVE_URL = "https://www.dawn.com/latest-news/{date}"
DEFAULT_START_DATE = dt.date(2023, 1, 1)
DEFAULT_END_DATE = dt.date(2026, 1, 1)
MAX_ROWS_PER_FILE = 10_000
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ArticleRecord:
    date: str
    title: str
    article_url: str
    article_text: str


class CsvChunkWriter:
    """Write rows into chunked CSV files with fixed row capacity."""

    def __init__(self, output_dir: Path, max_rows: int = MAX_ROWS_PER_FILE) -> None:
        self.output_dir = output_dir
        self.max_rows = max_rows
        self.file_index = 0
        self.rows_in_current_file = 0
        self._file_handle = None
        self._writer: Optional[csv.DictWriter] = None
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _open_new_file(self) -> None:
        if self._file_handle:
            self._file_handle.close()

        self.file_index += 1
        self.rows_in_current_file = 0
        file_path = self.output_dir / f"data_{self.file_index}.csv"
        self._file_handle = file_path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._file_handle,
            fieldnames=["date", "title", "article_url", "article_text"],
        )
        self._writer.writeheader()
        print(f"Opened {file_path}")

    def write(self, record: ArticleRecord) -> None:
        if self._writer is None or self.rows_in_current_file >= self.max_rows:
            self._open_new_file()

        assert self._writer is not None
        self._writer.writerow(
            {
                "date": record.date,
                "title": record.title,
                "article_url": record.article_url,
                "article_text": record.article_text,
            }
        )
        self.rows_in_current_file += 1

    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


def daterange(start_date: dt.date, end_date: dt.date) -> Iterator[dt.date]:
    """Yield every day between start_date and end_date (inclusive)."""
    current = start_date
    while current <= end_date:
        yield current
        current += dt.timedelta(days=1)


def build_proxy_config(
    host: str,
    port: int,
    username: str,
    password: str,
    proxy_url: str = "",
) -> Dict[str, str]:
    proxy_url = proxy_url.strip() or f"http://{username}:{password}@{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}


def build_session(timeout: int, proxies: Dict[str, str]) -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    session.proxies.update(proxies)
    session.request_timeout = timeout  # custom attribute
    return session


def fetch(session: requests.Session, url: str) -> Response:
    timeout = getattr(session, "request_timeout", 30)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response


def parse_archive_article_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen: Set[str] = set()

    for heading in soup.select("article h2 a") + soup.select("h2.story__title a"):
        href = heading.get("href")
        if not href or not href.startswith("https://www.dawn.com/news/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        urls.append(href)

    return urls


def parse_article_page(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.select_one("h2.story__title") or soup.select_one("h1.story__title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    paragraphs = soup.select("div.story__content p") or soup.select("article p")
    text_parts = [p.get_text(" ", strip=True) for p in paragraphs]
    article_text = "\n".join(part for part in text_parts if part)

    return {"title": title, "article_text": article_text}


def scrape(
    session: requests.Session,
    start_date: dt.date,
    end_date: dt.date,
    writer: CsvChunkWriter,
    sleep_seconds: float,
) -> None:
    seen_links: Set[str] = set()

    for day in daterange(start_date, end_date):
        archive_url = BASE_ARCHIVE_URL.format(date=day.isoformat())
        print(f"Processing archive day: {day.isoformat()}")

        try:
            archive_resp = fetch(session, archive_url)
        except requests.RequestException as exc:
            print(f"Failed archive page {archive_url}: {exc}", file=sys.stderr)
            continue

        links = parse_archive_article_links(archive_resp.text)
        print(f"  Found {len(links)} article links")

        for article_url in links:
            if article_url in seen_links:
                continue
            seen_links.add(article_url)

            try:
                article_resp = fetch(session, article_url)
                parsed = parse_article_page(article_resp.text)
            except requests.RequestException as exc:
                print(f"  Failed article {article_url}: {exc}", file=sys.stderr)
                continue

            writer.write(
                ArticleRecord(
                    date=day.isoformat(),
                    title=parsed["title"],
                    article_url=article_url,
                    article_text=parsed["article_text"],
                )
            )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Dawn latest-news archives into CSV chunk files"
    )
    parser.add_argument("--start-date", default=str(DEFAULT_START_DATE), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=str(DEFAULT_END_DATE), help="YYYY-MM-DD")
    parser.add_argument("--output-dir", default=".", help="Directory for data_*.csv files")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS_PER_FILE)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=30)

    parser.add_argument("--proxy-host", default="pr.oxylabs.io")
    parser.add_argument("--proxy-port", type=int, default=7777)
    parser.add_argument("--proxy-username", required=True)
    parser.add_argument("--proxy-password", required=True)
    parser.add_argument(
        "--proxy-url",
        default="",
        help="Optional full proxy URL; overrides host/port/username/password when provided.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        start_date = dt.date.fromisoformat(args.start_date)
        end_date = dt.date.fromisoformat(args.end_date)
    except ValueError as exc:
        print(f"Invalid date format: {exc}", file=sys.stderr)
        return 1

    if start_date > end_date:
        print("start-date must be <= end-date", file=sys.stderr)
        return 1

    proxies = build_proxy_config(
        host=args.proxy_host,
        port=args.proxy_port,
        username=args.proxy_username,
        password=args.proxy_password,
        proxy_url=args.proxy_url,
    )

    session = build_session(timeout=args.timeout, proxies=proxies)
    writer = CsvChunkWriter(output_dir=Path(args.output_dir), max_rows=args.max_rows)

    try:
        scrape(
            session=session,
            start_date=start_date,
            end_date=end_date,
            writer=writer,
            sleep_seconds=args.sleep_seconds,
        )
    finally:
        writer.close()

    print("Scraping finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
