"""
One-off CleverTap May 2026 WhatsApp summary -> Google Sheets.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from requests import Response
from requests.exceptions import RequestException


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

MAY_FROM_DATE = "20260501"
MAY_TO_DATE = "20260531"
TAB_NAME = "May_2026"
REQUEST_TIMEOUT = 30
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
OUTPUT_HEADER = [
    "Journey",
    "Node Name",
    "Campaign ID",
    "Sent",
    "Delivered",
    "Viewed",
    "Clicked",
    "Errors",
    "Converted",
    "Conversion%",
]
METRIC_FIELDS = ["sent", "delivered", "viewed", "clicked", "error", "converted"]
PAYLOAD_FIELD_ALIASES = {
    "sent": ("sent",),
    "delivered": ("delivered",),
    "viewed": ("viewed",),
    "clicked": ("clicked",),
    "error": ("error", "errors"),
    "converted": ("converted",),
}

JOURNEYS = {
    "Day0": [
        ("WA_Varca_Day0", 5243), ("WA_Virajpet_Day0", 5256), ("WA_Sherwood_Day0", 5269),
        ("WA_Madikeri_Day0", 5282), ("WA_Ashtamudi_Day0", 5295), ("WA_Assonora_Day0", 5308),
        ("WA_Kandaghat_Day0", 5512), ("WA_Munnar_Day0", 5525), ("WA_Naldehra_Day0", 5538),
        ("WA_Tungi_Day0", 5551), ("WA_Udaipur_Day0", 5564), ("WA_Cherai_Day0", 6231),
        ("WA_Binsar_Valley_Day0", 6244), ("WA_Chumbi_Day0", 13387), ("WA_Acacia_Day0", 13399),
        ("WA_Emerald_Day0", 13411), ("WA_Puducherry_Day0", 4680), ("WA_Arookutty_Day0", 4629),
    ],
    "Day5": [
        ("WA_Varca_Day5", 4533), ("WA_Virajpet_Day5", 4546), ("WA_Sherwood_Day5", 4559),
        ("WA_Madikeri_Day5", 4572), ("WA_Ashtamudi_Day5", 4585), ("WA_Assonora_Day5", 4598),
        ("WA_Kandaghat_Day5", 4456), ("WA_Munnar_Day5", 4469), ("WA_Naldhera_Day5", 4482),
        ("WA_Tungi_Day5", 4495), ("WA_Udaipur_Day5", 4508), ("WA_Arookutty_Day5", 4663),
        ("WA_Puducherry_Day5", 4714), ("WA_Cherai_Day5", 6265), ("WA_Binsar_Valley_Day5", 6278),
        ("WA_Chumbi_Day5", 13460), ("WA_Acacia_Day5", 13472), ("WA_Emerald_Day5", 13485),
        ("WA_Varca_Day3", 10919),
    ],
    "Day15": [
        ("WA_Varca_Day15", 4295), ("WA_Virajpet_Day15", 4308), ("WA_Sherwood_Day15", 4321),
        ("WA_Madikeri_Day15", 4334), ("WA_Ashtamudi_Day15", 4347), ("WA_Assonora_Day15", 4360),
        ("WA_Kandaghat_Day15", 4380), ("WA_Munnar_Day15", 4393), ("WA_Naldera_Day15", 4406),
        ("WA_Tungi_Day15", 4419), ("WA_Udaipur_Day15", 4432), ("WA_Arookutty_Day15", 4646),
        ("WA_Puducherry_Day15", 4697), ("WA_Cherai_Day15", 6299), ("WA_Binsar_Valley_Day15", 6312),
        ("WA_Chumbi_Day15", 13535), ("WA_Acacia_Day15", 13548), ("WA_Emerald_Day15", 13561),
    ],
    "Day05_Segments": [
        ("WA_Day05_SameState", 4140), ("WA_Day05_DifferentState", 4153),
        ("WA_Day05_International", 4166),
    ],
    "Day20_Segments": [
        ("WA_Day20_SameState", 4105), ("WA_Day20_DifferentState", 4118),
    ],
    "Day30_Segments": [
        ("WA_Day30_SameState", 3980), ("WA_Day30_DifferentState", 3993),
    ],
    "Day60_Segments": [
        ("WA_Day60_SameState", 3934), ("WA_Day60_DifferentState", 3947),
        ("WA_Day60_International", 3960),
    ],
}


load_dotenv(ENV_FILE)

SHEET_ID = os.getenv("SHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
CT_BASE_URL = os.getenv("CT_BASE_URL", "https://in1.dashboard.clevertap.com/W8W-6R9-885Z")
CT_COOKIE = os.getenv("CT_COOKIE", "")
CT_CSRF_TOKEN = os.getenv("CT_CSRF_TOKEN", "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull CleverTap May 2026 campaign totals.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and build rows, but do not write anything to Google Sheets.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N campaigns. Useful for quick live validation.",
    )
    return parser.parse_args()


def validate_config() -> Path:
    missing = []

    if not SHEET_ID:
        missing.append("SHEET_ID")
    if not CT_BASE_URL:
        missing.append("CT_BASE_URL")
    if not CT_COOKIE:
        missing.append("CT_COOKIE")
    if not CT_CSRF_TOKEN:
        missing.append("CT_CSRF_TOKEN")

    if missing:
        raise ValueError(
            "Missing required config: "
            f"{', '.join(missing)}. Add them to {ENV_FILE.name}."
        )

    service_account_path = BASE_DIR / SERVICE_ACCOUNT_FILE
    if not service_account_path.exists():
        raise FileNotFoundError(f"Service account file not found: {service_account_path}")

    return service_account_path


def build_headers() -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "cookie": CT_COOKIE,
        "origin": "https://in1.dashboard.clevertap.com",
        "x-clevertap-csrf-token": CT_CSRF_TOKEN,
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }


def fetch_campaign_response(session: requests.Session, campaign_id: int) -> Response:
    url = f"{CT_BASE_URL}/json/notification/calculateTrend.html"
    return session.post(
        url,
        params={"uc": "1"},
        headers=build_headers(),
        data={"id": campaign_id, "from": MAY_FROM_DATE, "to": MAY_TO_DATE},
        timeout=REQUEST_TIMEOUT,
    )


def summarize_payload(payload: dict[str, Any]) -> dict[str, int]:
    daily_data = payload.get("All")
    if not isinstance(daily_data, dict):
        raise ValueError("CleverTap response did not include an 'All' object.")

    totals = {field: 0 for field in METRIC_FIELDS}
    for date_key, day_entry in daily_data.items():
        if not isinstance(date_key, str) or not MAY_FROM_DATE <= date_key <= MAY_TO_DATE:
            continue
        if not isinstance(day_entry, dict):
            continue

        for field in METRIC_FIELDS:
            value = 0
            for payload_field in PAYLOAD_FIELD_ALIASES[field]:
                if payload_field not in day_entry:
                    continue

                candidate = day_entry[payload_field]
                if isinstance(candidate, (int, float)):
                    value = int(candidate)
                    break
            totals[field] += value

    return totals


def fetch_campaign_totals(
    session: requests.Session,
    campaign_id: int,
) -> tuple[dict[str, int] | None, dict[str, Any] | None, str | None]:
    try:
        response = fetch_campaign_response(session, campaign_id)
        if response.status_code in {401, 403}:
            return None, None, f"session expired (HTTP {response.status_code})"

        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            preview = response.text.strip().replace("\n", " ")[:200]
            return None, None, f"non-JSON response: {preview}"

        if not isinstance(payload, dict):
            return None, None, "response JSON was not an object"

        if payload.get("success") is False:
            return None, payload, str(payload.get("error", "CleverTap API returned success=false"))

        totals = summarize_payload(payload)
        return totals, payload, None
    except (RequestException, ValueError) as exc:
        return None, None, str(exc)


def conversion_rate(sent: int, converted: int) -> float:
    if sent == 0:
        return 0.0
    return round((converted / sent) * 100, 1)


def error_row(journey_name: str, node_name: str, campaign_id: int) -> list[Any]:
    return [journey_name, node_name, campaign_id, "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", "ERROR"]


def success_row(
    journey_name: str,
    node_name: str,
    campaign_id: int,
    totals: dict[str, int],
) -> list[Any]:
    return [
        journey_name,
        node_name,
        campaign_id,
        totals["sent"],
        totals["delivered"],
        totals["viewed"],
        totals["clicked"],
        totals["error"],
        totals["converted"],
        conversion_rate(totals["sent"], totals["converted"]),
    ]


def open_google_sheet(service_account_path: Path) -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(service_account_path, scopes=GOOGLE_SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def get_or_reset_tab(sheet: gspread.Spreadsheet, row_count: int) -> gspread.Worksheet:
    try:
        worksheet = sheet.worksheet(TAB_NAME)
        worksheet.clear()
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=TAB_NAME, rows=max(row_count, 100), cols=len(OUTPUT_HEADER) + 2)

    worksheet.resize(rows=max(row_count, 100), cols=len(OUTPUT_HEADER))
    return worksheet


def format_tab(sheet: gspread.Spreadsheet, worksheet: gspread.Worksheet, row_count: int) -> None:
    sheet.batch_update(
        {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": worksheet.id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(OUTPUT_HEADER),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.08, "green": 0.11, "blue": 0.17},
                                "textFormat": {
                                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                    "bold": True,
                                },
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": 2,
                            "endColumnIndex": 9,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "CENTER",
                                "numberFormat": {"type": "NUMBER", "pattern": "0"},
                            }
                        },
                        "fields": "userEnteredFormat(horizontalAlignment,numberFormat)",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": 9,
                            "endColumnIndex": 10,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "CENTER",
                                "numberFormat": {"type": "NUMBER", "pattern": "0.0"},
                            }
                        },
                        "fields": "userEnteredFormat(horizontalAlignment,numberFormat)",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": worksheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": len(OUTPUT_HEADER),
                        },
                        "properties": {"pixelSize": 130},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": worksheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": 1,
                            "endIndex": 2,
                        },
                        "properties": {"pixelSize": 260},
                        "fields": "pixelSize",
                    }
                },
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": worksheet.id,
                                "startRowIndex": 0,
                                "startColumnIndex": 0,
                                "endRowIndex": row_count,
                                "endColumnIndex": len(OUTPUT_HEADER),
                            }
                        }
                    }
                },
            ]
        }
    )


def build_totals_row(metric_totals: dict[str, int]) -> list[Any]:
    total_sent = metric_totals["sent"]
    total_converted = metric_totals["converted"]
    return [
        "TOTALS",
        "",
        "",
        total_sent,
        metric_totals["delivered"],
        metric_totals["viewed"],
        metric_totals["clicked"],
        metric_totals["error"],
        total_converted,
        conversion_rate(total_sent, total_converted),
    ]


def run(dry_run: bool = False, limit: int = 0) -> None:
    service_account_path = validate_config()
    total_campaigns = sum(len(nodes) for nodes in JOURNEYS.values())
    if limit > 0:
        total_campaigns = min(total_campaigns, limit)

    print(f"Pulling CleverTap May 2026 summary for {total_campaigns} campaign(s)")

    rows: list[list[Any]] = []
    metric_totals = {field: 0 for field in METRIC_FIELDS}
    first_payload_printed = False

    with requests.Session() as session:
        processed_count = 0
        for journey_name, campaigns in JOURNEYS.items():
            for node_name, campaign_id in campaigns:
                if limit > 0 and processed_count >= limit:
                    break

                processed_count += 1
                print(
                    f"[{processed_count}/{total_campaigns}] Fetching {journey_name} / "
                    f"{node_name} (Campaign ID: {campaign_id})"
                )

                totals, payload, error = fetch_campaign_totals(session, campaign_id)

                if not first_payload_printed:
                    print("\nRaw JSON response for first campaign:\n")
                    if payload is not None:
                        print(json.dumps(payload, indent=2, sort_keys=True))
                    else:
                        print(f"Unable to print JSON for first campaign: {error}")
                    print()
                    first_payload_printed = True

                if error or totals is None:
                    print(f"  Error: {error}")
                    rows.append(error_row(journey_name, node_name, campaign_id))
                    continue

                for field in METRIC_FIELDS:
                    metric_totals[field] += totals[field]

                rows.append(success_row(journey_name, node_name, campaign_id, totals))
                print(
                    "  Sent={sent} Delivered={delivered} Viewed={viewed} Clicked={clicked} "
                    "Errors={error} Converted={converted}".format(**totals)
                )
            if limit > 0 and processed_count >= limit:
                break

    rows.append(build_totals_row(metric_totals))

    if dry_run:
        print(f"Dry run complete. Generated {len(rows)} row(s) including totals.")
        return

    print(f"Writing {len(rows)} rows to Google Sheet tab '{TAB_NAME}'")
    sheet = open_google_sheet(service_account_path)
    worksheet = get_or_reset_tab(sheet, len(rows) + 5)
    worksheet.update("A1", [OUTPUT_HEADER] + rows, value_input_option="USER_ENTERED")
    format_tab(sheet, worksheet, len(rows) + 1)
    print("Done. Google Sheet updated successfully.")


if __name__ == "__main__":
    args = parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
