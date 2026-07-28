"""
CleverTap June 2026 resort-wise totals for Day0 / Day5 / Day15.

Computes totals from 2026-06-01 to a target end date (default: today)
for Sent, Delivered, Viewed, and Clicked, grouped by resort.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

CT_COOKIE = ""
CT_CSRF_TOKEN = ""
CT_BASE_URL = ""
CT_REFERER_URL = ""

DEFAULT_FROM_DATE = "20260601"
DAY_GROUPS = ("Day0", "Day5", "Day15")

JOURNEYS = {
    "Day0": [
        ("WA_Varca_Day0", 5243),
        ("WA_Virajpet_Day0", 5256),
        ("WA_Sherwood_Day0", 5269),
        ("WA_Madikeri_Day0", 5282),
        ("WA_Ashtamudi_Day0", 5295),
        ("WA_Assonora_Day0", 5308),
        ("WA_Kandaghat_Day0", 5512),
        ("WA_Munnar_Day0", 5525),
        ("WA_Naldehra_Day0", 5538),
        ("WA_Tungi_Day0", 5551),
        ("WA_Udaipur_Day0", 5564),
        ("WA_Arookutty_Day0", 4629),
        ("WA_Puducherry_Day0", 4680),
        ("WA_Cherai_Day0", 6231),
        ("WA_Binsar_Valley_Day0", 6244),
        ("WA_Chumbi_Day0", 13387),
        ("WA_Acacia_Day0", 13399),
        ("WA_Emerald_Day0", 13411),
    ],
    "Day5": [
        ("WA_Varca_Day5", 4533),
        ("WA_Virajpet_Day5", 4546),
        ("WA_Sherwood_Day5", 4559),
        ("WA_Madikeri_Day5", 4572),
        ("WA_Ashtamudi_Day5", 4585),
        ("WA_Assonora_Day5", 4598),
        ("WA_Kandaghat_Day5", 4456),
        ("WA_Munnar_Day5", 4469),
        ("WA_Naldhera_Day5", 4482),
        ("WA_Tungi_Day5", 4495),
        ("WA_Udaipur_Day5", 4508),
        ("WA_Puducherry_Day5", 4714),
        ("WA_Arookutty_Day5", 4663),
        ("WA_Cherai_Day5", 6265),
        ("WA_Binsar_Valley_Day5", 6278),
        ("WA_Chumbi_Day5", 13460),
        ("WA_Acacia_Day5", 13472),
        ("WA_Emerald_Day5", 13485),
        ("WA_Varca_Day3", 10919),
    ],
    "Day15": [
        ("WA_Varca_Day15", 4295),
        ("WA_Virajpet_Day15", 4308),
        ("WA_Sherwood_Day15", 4321),
        ("WA_Madikeri_Day15", 4334),
        ("WA_Ashtamudi_Day15", 4347),
        ("WA_Assonora_Day15", 4360),
        ("WA_Kandaghat_Day15", 4380),
        ("WA_Munnar_Day15", 4393),
        ("WA_Naldera_Day15", 4406),
        ("WA_Tungi_Day15", 4419),
        ("WA_Udaipur_Day15", 4432),
        ("WA_Puducherry_Day15", 4697),
        ("WA_Arookutty_Day15", 4646),
        ("WA_Cherai_Day15", 6299),
        ("WA_Binsar_Valley_Day15", 6312),
        ("WA_Chumbi_Day15", 13535),
        ("WA_Acacia_Day15", 13548),
        ("WA_Emerald_Day15", 13561),
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


def normalize_resort_name(node_name: str, expected_day: str) -> str:
    base = re.sub(r"^WA_", "", node_name)
    base = re.sub(rf"_{expected_day}$", "", base)
    base = base.replace("_", " ").strip()
    return " ".join(part.capitalize() for part in base.split())


def fetch_range_totals(campaign_id: int, from_date: str, to_date: str) -> Totals:
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
    data = {"id": campaign_id, "from": from_date, "to": to_date}

    response = requests.post(url, headers=headers, data=data, params={"uc": "1"}, timeout=30)
    if response.status_code in {401, 403}:
        raise RuntimeError("Session expired (HTTP 401/403). Refresh CT_COOKIE and CT_CSRF_TOKEN.")

    response.raise_for_status()
    payload = response.json()

    if payload.get("success") is False:
        err = payload.get("error", "CleverTap API returned success=false")
        raise RuntimeError(str(err))

    all_days = payload.get("All")
    if not isinstance(all_days, dict):
        raise RuntimeError("CleverTap response missing 'All' object")

    totals = Totals()
    for date_key, day in all_days.items():
        if not isinstance(date_key, str) or not from_date <= date_key <= to_date:
            continue
        if not isinstance(day, dict):
            continue

        totals.sent += int(day.get("sent", 0) or 0)
        totals.delivered += int(day.get("delivered", 0) or 0)
        totals.viewed += int(day.get("viewed", 0) or 0)
        totals.clicked += int(day.get("clicked", 0) or 0)

    return totals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Date-range totals for Day0/Day5/Day15 by resort.")
    parser.add_argument(
        "--from-date",
        default=DEFAULT_FROM_DATE,
        help="Range start date in YYYYMMDD (default: 20260601).",
    )
    parser.add_argument(
        "--to-date",
        default=datetime.now().strftime("%Y%m%d"),
        help="Range end date in YYYYMMDD (default: today).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from_date = args.from_date.strip()
    to_date = args.to_date.strip()

    if not re.match(r"^\d{8}$", from_date):
        raise ValueError("--from-date must be in YYYYMMDD format")
    if not re.match(r"^\d{8}$", to_date):
        raise ValueError("--to-date must be in YYYYMMDD format")

    if to_date < from_date:
        raise ValueError("--to-date must be on/after --from-date")

    load_config()

    month_label = datetime.strptime(from_date, "%Y%m%d").strftime("%b").upper()
    print("YEAR\tMONTH\tDAY\tRESORT NAME\tTOTAL SENT\tTOTAL DELIVERED\tTOTAL VIEWED\tTOTAL CLICKED")

    for day_group in DAY_GROUPS:
        for node_name, campaign_id in JOURNEYS[day_group]:
            expected_suffix = day_group
            if not node_name.endswith(f"_{expected_suffix}"):
                # Skips known outlier WA_Varca_Day3 under the Day5 list.
                continue

            resort = normalize_resort_name(node_name, expected_suffix)
            totals = fetch_range_totals(campaign_id, from_date, to_date)
            print(
                "2026\t{month}\t{day}\t{resort}\t{sent}\t{delivered}\t{viewed}\t{clicked}".format(
                    day=day_group.upper(),
                    month=month_label,
                    resort=resort,
                    sent=totals.sent,
                    delivered=totals.delivered,
                    viewed=totals.viewed,
                    clicked=totals.clicked,
                )
            )


if __name__ == "__main__":
    main()
