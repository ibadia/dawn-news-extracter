#!/usr/bin/env python3
"""Scrape Dawn latest-news pages by date and save article data into chunked CSV files.

Requirements implemented from readme.md:
- Collect data from dawn.com latest-news daily archives.
- Date range: configurable, default 2023-01-01 to 2026-01-01.
- Use Oxylabs proxy.
- Save output as data_1.csv, data_2.csv, ...
- Maximum 10,000 rows per CSV file.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.dawn.com"
LATEST_NEWS_URL = "https://www.dawn.com/latest-news/{day}"
ROWS_PER_FILE = 10_000
REQUEST_TIMEOUT = 45


@dataclass
class Config:
    start_date: date
    end_date: date
    output_dir: Path
    proxy_host: str
    proxy_port: int
    proxy_username: str
    proxy_password: str
    proxy_auth_prefix: str
    delay_seconds: float
    max_retries: int


class DawnScraper:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        normalized_username = self._normalize_proxy_username(
            config.proxy_username, config.proxy_auth_prefix
        )
        proxy_uri = (
            f"http://{requests.utils.quote(normalized_username, safe='')}:"
            f"{requests.utils.quote(config.proxy_password, safe='')}"
            f"@{config.proxy_host}:{config.proxy_port}"
        )
        self.session.proxies = {"http": proxy_uri, "https": proxy_uri}

        self._seen_urls: Set[str] = set()

    @staticmethod
    def _normalize_proxy_username(username: str, auth_prefix: str) -> str:
        """
        Oxylabs Residential authentication commonly requires customer-<username>.
        If the prefix is already present, keep it unchanged.
        """
        if not auth_prefix:
            return username
        if username.startswith(f"{auth_prefix}-"):
            return username
        return f"{auth_prefix}-{username}"

    def _request_with_retry(self, url: str) -> Optional[requests.Response]:
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                if attempt == self.config.max_retries:
                    print(f"[ERROR] Failed URL after retries: {url} ({exc})", file=sys.stderr)
                    return None
                sleep_seconds = min(2**attempt, 10)
                print(
                    f"[WARN] Attempt {attempt}/{self.config.max_retries} failed for {url}: {exc}. "
                    f"Retrying in {sleep_seconds}s...",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)
        return None

    def _extract_article_urls(self, archive_html: str) -> List[str]:
        soup = BeautifulSoup(archive_html, "html.parser")
        article_urls: List[str] = []

        # Dawn uses multiple list/card styles across pages; capture likely story links.
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            if not href:
                continue
            absolute = urljoin(BASE_URL, href)
            if self._is_candidate_article_url(absolute):
                article_urls.append(absolute)

        # Preserve order while de-duplicating.
        ordered_unique = list(dict.fromkeys(article_urls))
        return ordered_unique

    @staticmethod
    def _is_candidate_article_url(url: str) -> bool:
        if not url.startswith(BASE_URL):
            return False

        # Most Dawn story URLs follow /news/<id>/... or /news/<id>
        if re.search(r"/news/\d+", url):
            return True

        return False

    def _extract_article_fields(self, article_url: str, html: str) -> Dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        title_tag = soup.find("h2", class_=re.compile(r"story__title"))
        if title_tag:
            title = " ".join(title_tag.get_text(" ", strip=True).split())
        elif soup.title:
            title = " ".join(soup.title.get_text(" ", strip=True).split())

        published = ""
        time_tag = soup.find("span", class_=re.compile(r"story__time"))
        if time_tag:
            published = " ".join(time_tag.get_text(" ", strip=True).split())

        paragraphs = []
        for p_tag in soup.select("div.story__content p"):
            text = " ".join(p_tag.get_text(" ", strip=True).split())
            if text:
                paragraphs.append(text)

        if not paragraphs:
            # Fallback for pages with different markup.
            for p_tag in soup.select("article p"):
                text = " ".join(p_tag.get_text(" ", strip=True).split())
                if text:
                    paragraphs.append(text)

        article_text = "\n".join(paragraphs)

        return {
            "article_url": article_url,
            "title": title,
            "published": published,
            "article_text": article_text,
        }

    def iter_rows(self) -> Iterable[Dict[str, str]]:
        current = self.config.start_date
        while current <= self.config.end_date:
            day = current.isoformat()
            archive_url = LATEST_NEWS_URL.format(day=day)
            print(f"[INFO] Scraping archive date {day}")

            archive_resp = self._request_with_retry(archive_url)
            if archive_resp is None:
                current += timedelta(days=1)
                continue

            article_urls = self._extract_article_urls(archive_resp.text)
            if not article_urls:
                print(f"[WARN] No article URLs found for {day}", file=sys.stderr)

            for article_url in article_urls:
                if article_url in self._seen_urls:
                    continue
                self._seen_urls.add(article_url)

                article_resp = self._request_with_retry(article_url)
                if article_resp is None:
                    continue

                row = self._extract_article_fields(article_url, article_resp.text)
                row["archive_date"] = day
                yield row

                if self.config.delay_seconds > 0:
                    time.sleep(self.config.delay_seconds)

            current += timedelta(days=1)


def write_chunked_csv(rows: Iterable[Dict[str, str]], output_dir: Path) -> Tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = ["archive_date", "published", "title", "article_url", "article_text"]
    file_index = 1
    row_in_file = 0
    total_rows = 0

    csv_file = (output_dir / f"data_{file_index}.csv").open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    try:
        for row in rows:
            if row_in_file >= ROWS_PER_FILE:
                csv_file.close()
                file_index += 1
                row_in_file = 0
                csv_file = (output_dir / f"data_{file_index}.csv").open(
                    "w", newline="", encoding="utf-8"
                )
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                writer.writeheader()

            writer.writerow({name: row.get(name, "") for name in fieldnames})
            row_in_file += 1
            total_rows += 1
    finally:
        csv_file.close()

    return total_rows, file_index


def parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {raw!r}. Expected YYYY-MM-DD") from exc


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Scrape Dawn latest-news archive by date range.")
    parser.add_argument("--start-date", type=parse_date, default=date(2023, 1, 1))
    parser.add_argument("--end-date", type=parse_date, default=date(2026, 1, 1))
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--proxy-host", default="pr.oxylabs.io")
    parser.add_argument("--proxy-port", type=int, default=7777)
    parser.add_argument("--proxy-username", default="ibadski_8WEQw")
    parser.add_argument("--proxy-password", default="Ibad1234567_")
    parser.add_argument(
        "--proxy-auth-prefix",
        default="customer",
        help="Prefix for Oxylabs proxy user auth string (default: customer).",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=4)
    args = parser.parse_args()

    if args.start_date > args.end_date:
        parser.error("--start-date must be <= --end-date")

    return Config(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        proxy_username=args.proxy_username,
        proxy_password=args.proxy_password,
        proxy_auth_prefix=args.proxy_auth_prefix,
        delay_seconds=args.delay_seconds,
        max_retries=args.max_retries,
    )


def main() -> int:
    config = parse_args()
    scraper = DawnScraper(config)

    rows = scraper.iter_rows()
    total_rows, total_files = write_chunked_csv(rows, config.output_dir)

    print(f"[DONE] Export complete. Rows: {total_rows}, CSV files: {total_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
