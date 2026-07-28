"""
CleverTap concierge QBR summary for Jan-May 2026.

Aggregates Sent, Delivered, Viewed, and Clicked for the concierge journeys
listed below and prints a month-wise table that is easy to paste into a QBR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

CT_COOKIE = ""
CT_CSRF_TOKEN = ""
CT_BASE_URL = ""
CT_REFERER_URL = ""

YEAR = 2026
MONTH_WINDOWS = [
    ("JAN", "20260101", "20260131"),
    ("FEB", "20260201", "20260228"),
    ("MAR", "20260301", "20260331"),
    ("APR", "20260401", "20260430"),
    ("MAY", "20260501", "20260531"),
]

CONCIERGE_GROUPS = {
    "Day05": [
        ("WA_Day05_SameState", 4140),
        ("WA_Day05_DifferentState", 4153),
        ("WA_Day05_International", 4166),
    ],
    "Day20": [
        ("WA_Day20_SameState", 4105),
        ("WA_Day20_DifferentState", 4118),
    ],
    "Day30": [
        ("WA_Day30_SameState", 3980),
        ("WA_Day30_DifferentState", 3993),
    ],
    "Day60": [
        ("WA_Day60_SameState", 3934),
        ("WA_Day60_DifferentState", 3947),
        ("WA_Day60_International", 3960),
    ],
}


@dataclass
class Totals:
    sent: int = 0
    delivered: int = 0
    viewed: int = 0
    clicked: int = 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


def load_config() -> None:
    global CT_COOKIE, CT_CSRF_TOKEN, CT_BASE_URL, CT_REFERER_URL

    load_env_file(ENV_FILE)

    CT_COOKIE = os.getenv("CT_COOKIE", "")
    CT_CSRF_TOKEN = os.getenv("CT_CSRF_TOKEN", "")
    CT_BASE_URL = os.getenv("CT_BASE_URL", "https://in1.dashboard.clevertap.com/W8W-6R9-885Z")
    CT_REFERER_URL = os.getenv(
        "CT_REFERER_URL",
        "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/journeys/journey/239/report/node-stats",
    )

    missing = []
    if not CT_COOKIE:
        missing.append("CT_COOKIE")
    if not CT_CSRF_TOKEN:
        missing.append("CT_CSRF_TOKEN")

    if missing:
        raise ValueError(f"Missing required config in .env: {', '.join(missing)}")


def int_value(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def fetch_range_totals(session: requests.Session, campaign_id: int, from_date: str, to_date: str) -> Totals:
    url = f"{CT_BASE_URL}/json/notification/calculateTrend.html"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "cookie": CT_COOKIE,
        "origin": "https://in1.dashboard.clevertap.com",
        "referer": CT_REFERER_URL,
        "x-clevertap-csrf-token": CT_CSRF_TOKEN,
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
    }

    response = session.post(
        url,
        headers=headers,
        data={"id": campaign_id, "from": from_date, "to": to_date},
        params={"uc": "1"},
        timeout=30,
    )

    if response.status_code in {401, 403}:
        raise RuntimeError(f"Session expired (HTTP {response.status_code}). Refresh CT_COOKIE and CT_CSRF_TOKEN.")

    response.raise_for_status()
    payload = response.json()

    if payload.get("success") is False:
        raise RuntimeError(str(payload.get("error", "CleverTap API returned success=false")))

    all_days = payload.get("All")
    if not isinstance(all_days, dict):
        raise RuntimeError("CleverTap response missing 'All' object")

    totals = Totals()
    for date_key, day in all_days.items():
        if not isinstance(date_key, str) or not from_date <= date_key <= to_date:
            continue
        if not isinstance(day, dict):
            continue

        totals.sent += int_value(day.get("sent", 0))
        totals.delivered += int_value(day.get("delivered", 0))
        totals.viewed += int_value(day.get("viewed", 0))
        totals.clicked += int_value(day.get("clicked", 0))

    return totals


def rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def format_percent(value: float) -> str:
    return f"{value:.2f}%"


def build_rows(session: requests.Session) -> list[list[str]]:
    rows: list[list[str]] = []

    for month_label, from_date, to_date in MONTH_WINDOWS:
        for group_name, campaigns in CONCIERGE_GROUPS.items():
            group_totals = Totals()
            active_campaigns = 0

            for campaign_name, campaign_id in campaigns:
                totals = fetch_range_totals(session, campaign_id, from_date, to_date)
                if totals.sent or totals.delivered or totals.viewed or totals.clicked:
                    active_campaigns += 1

                group_totals.sent += totals.sent
                group_totals.delivered += totals.delivered
                group_totals.viewed += totals.viewed
                group_totals.clicked += totals.clicked

            rows.append([
                str(YEAR),
                month_label,
                group_name,
                str(active_campaigns),
                str(group_totals.sent),
                str(group_totals.delivered),
                str(group_totals.viewed),
                str(group_totals.clicked),
                format_percent(rate(group_totals.delivered, group_totals.sent)),
                format_percent(rate(group_totals.viewed, group_totals.delivered)),
                format_percent(rate(group_totals.clicked, group_totals.viewed)),
            ])

    return rows


def print_table(rows: list[list[str]]) -> None:
    headers = [
        "Year",
        "Month",
        "Journey",
        "No Of Campaigns",
        "Total Sent",
        "Total Delivered",
        "Total Viewed",
        "Total Clicked",
        "Delivery Rate",
        "Viewed Rate",
        "Click Rate",
    ]

    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render_row(values: list[str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print("CONCIERGE")
    print("JAN TO MAY BY JOURNEY")
    print(render_row(headers))
    for row in rows:
        print(render_row(row))


def main() -> None:
    load_config()
    with requests.Session() as session:
        rows = build_rows(session)
    print_table(rows)


if __name__ == "__main__":
    main()