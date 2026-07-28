"""
CleverTap prospects summary -> Google Sheets.

Pulls today's counts for the selected WhatsApp and SMS prospect campaigns
and writes them into separate sheets.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

CT_COOKIE = ""
CT_CSRF_TOKEN = ""
CT_BASE_URL = ""
CT_REFERER_URL = ""
CT_FROM_DATE = "20260419"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

OUTPUT_HEADER = [
    "Campaign Name",
    "Campaign ID",
    "Sent",
    "Delivered",
    "Viewed",
    "Clicked",
    "Errors",
    "Converted",
    "Conversion%",
]

TAB_COLORS = {
    "WhatsApp": "#2563EB",
    "SMS": "#0F766E",
}

SELECTED_CAMPAIGNS = {
    "WhatsApp": [
        ("Prospect09_WA_Rescheduled_AUTO", 1782133303),
        ("Prospect07_WA_MeetingReminder_AUTO", 1782130745),
        ("Prospect13_WA_Welcome_consenttrue_AUTO", 1778758056),
        ("Prospect11_WA_NotIntrested_AUTO", 1771825803),
        ("Prospect01_WA_PRO_Consent_AUTO", 1770366987),
        ("Prospect12_WA_NotQualified_AUTO", 1770363503),
        ("Prospect10_WA_FollowUp_AUTO", 1770363126),
        ("Prospect08_WA_SaleConfirmation_AUTO", 1770362424),
        ("Prospect06_WA_Confirmation_AUTO", 1770362059),
        ("Prospect05_WA_MissedYou_AUTO", 1770361924),
        ("Prospect04_WA_Welcome_AUTO", 1770361107),
        ("Prospect03_WA_HFRP_Member_AUTO", 1770359258),
        ("Prospect02_WA_HFRP_Consent_AUTO", 1770359003),
    ],
    "SMS": [
        ("Prospect13_SMS_Welcome_consenttrue_FB_AUTO", 1782298649),
        ("Prospect11_SMS_NotIntrested_FB_AUTO", 1782298443),
        ("Prospect10_SMS_FollowUp_FB_AUTO", 1782298313),
        ("Prospect09_SMS_Rescheduled_FB_AUTO", 1782298110),
        ("Prospect08_SMS_SaleConfirmation_FB_AUTO", 1782297976),
        ("Prospect07_SMS_MeetingReminder_FB_AUTO", 1782297830),
        ("Prospect06_SMS_Confirmation_FB_AUTO", 1782297552),
        ("Prospect05_SMS_MissedYou_FB_AUTO", 1782297422),
        ("Prospect03_SMS_HFRP_Member_FB_AUTO", 1782297172),
        ("Prospect02_SMS_HFRP_Consent_FB_AUTO", 1782297003),
        ("Prospect04_SMS_Welcome_AUTO", 1779860939),
    ],
}


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull selected CleverTap prospect campaign counts.")
    parser.add_argument(
        "--date",
        help="Date to pull in YYYY-MM-DD or YYYYMMDD format. Defaults to today.",
    )
    return parser.parse_args()


def parse_run_date(date_value: str | None) -> tuple[str, str]:
    if not date_value:
        run_date = datetime.now()
    else:
        normalized = date_value.strip()
        date_format = "%Y%m%d" if normalized.isdigit() else "%Y-%m-%d"
        run_date = datetime.strptime(normalized, date_format)

    return run_date.strftime("%Y-%m-%d"), run_date.strftime("%Y%m%d")


def int_value(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def extract_today_totals(today_entry: dict[str, object]) -> dict[str, int]:
    return {
        "sent": int_value(today_entry.get("sent", 0)),
        "delivered": int_value(today_entry.get("delivered", 0)),
        "viewed": int_value(today_entry.get("viewed", 0)),
        "clicked": int_value(today_entry.get("clicked", 0)),
        "error": int_value(today_entry.get("error", today_entry.get("errors", 0))),
        "converted": int_value(today_entry.get("converted", 0)),
    }


def fetch_campaign_stats(campaign_id: int, today_str: str) -> dict[str, int] | None:
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
    data = {"id": campaign_id, "from": CT_FROM_DATE, "to": today_str}

    try:
        response = requests.post(url, headers=headers, data=data, params={"uc": "1"}, timeout=30)
        if response.status_code in {401, 403}:
            raise RuntimeError(
                f"Session expired (HTTP {response.status_code}). Refresh CT_COOKIE and CT_CSRF_TOKEN in .env."
            )

        response.raise_for_status()
        payload = response.json()

        if payload.get("success") is False:
            raise RuntimeError(str(payload.get("error", "CleverTap API returned success=false.")))

        daily_data = payload.get("All")
        if not isinstance(daily_data, dict):
            raise RuntimeError("CleverTap response did not include the expected 'All' date data.")

        if today_str not in daily_data:
            raise RuntimeError(f"CleverTap response did not include data for {today_str}.")

        today_entry = daily_data[today_str]
        if not isinstance(today_entry, dict):
            raise RuntimeError("CleverTap response for today was not a JSON object.")

        return extract_today_totals(today_entry)
    except Exception as exc:
        print(f"    Warning: Error fetching campaign {campaign_id}: {exc}")
        return None


def conversion_rate(sent: int, converted: int) -> float:
    if sent == 0:
        return 0.0
    return round((converted / sent) * 100, 1)


def build_row(campaign_name: str, campaign_id: int, stats: dict[str, int]) -> list[object]:
    return [
        campaign_name,
        campaign_id,
        stats["sent"],
        stats["delivered"],
        stats["viewed"],
        stats["clicked"],
        stats["error"],
        stats["converted"],
        conversion_rate(stats["sent"], stats["converted"]),
    ]


def build_totals_row(metric_totals: dict[str, int]) -> list[object]:
    total_sent = metric_totals["sent"]
    total_converted = metric_totals["converted"]
    return [
        "TOTALS",
        "",
        total_sent,
        metric_totals["delivered"],
        metric_totals["viewed"],
        metric_totals["clicked"],
        metric_totals["error"],
        total_converted,
        conversion_rate(total_sent, total_converted),
    ]


def get_or_reset_tab(sheet: gspread.Spreadsheet, tab_name: str, row_count: int) -> gspread.Worksheet:
    try:
        worksheet = sheet.worksheet(tab_name)
        worksheet.clear()
    except gspread.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=tab_name, rows=max(row_count, 100), cols=len(OUTPUT_HEADER))

    worksheet.resize(rows=max(row_count, 100), cols=len(OUTPUT_HEADER))
    return worksheet


def hex_to_rgb(color: str) -> dict[str, float]:
    color = color.lstrip("#")
    return {
        "red": int(color[0:2], 16) / 255,
        "green": int(color[2:4], 16) / 255,
        "blue": int(color[4:6], 16) / 255,
    }


def format_tab(sheet: gspread.Spreadsheet, worksheet: gspread.Worksheet, row_count: int) -> None:
    sheet.batch_update(
        {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": worksheet.id,
                            "tabColor": hex_to_rgb(TAB_COLORS.get(worksheet.title, "#334155")),
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "tabColor,gridProperties.frozenRowCount",
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
                                "horizontalAlignment": "CENTER",
                                "textFormat": {
                                    "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                    "bold": True,
                                },
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
                            "startColumnIndex": 1,
                            "endColumnIndex": len(OUTPUT_HEADER),
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
                            "startColumnIndex": len(OUTPUT_HEADER) - 1,
                            "endColumnIndex": len(OUTPUT_HEADER),
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
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"pixelSize": 300},
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


def open_google_sheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(
        BASE_DIR / os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json"),
        scopes=GOOGLE_SCOPES,
    )
    client = gspread.authorize(creds)
    return client.open_by_key(os.getenv("SHEET_ID", ""))


def validate_config() -> None:
    missing = []

    if not os.getenv("SHEET_ID", ""):
        missing.append("SHEET_ID")
    if not CT_COOKIE:
        missing.append("CT_COOKIE")
    if not CT_CSRF_TOKEN:
        missing.append("CT_CSRF_TOKEN")

    if missing:
        raise ValueError(
            "Missing required config in .env: "
            f"{', '.join(missing)}"
        )


def run(date_value: str | None = None) -> None:
    validate_config()
    sheet_date, api_date = parse_run_date(date_value)
    load_config()

    print(f"\nCleverTap Prospects Pull - {sheet_date}\n")
    sheet = open_google_sheet()
    print("Connected to Google Sheets\n")

    with requests.Session() as session:
        for tab_name, campaigns in SELECTED_CAMPAIGNS.items():
            print(f"Tab: {tab_name} ({len(campaigns)} selected campaigns)")
            rows: list[list[object]] = []
            totals = {"sent": 0, "delivered": 0, "viewed": 0, "clicked": 0, "error": 0, "converted": 0}

            for campaign_name, campaign_id in campaigns:
                print(f"  Fetching {campaign_name} (Campaign ID: {campaign_id})...")
                stats = fetch_campaign_stats(campaign_id, api_date)

                if stats is None:
                    rows.append([campaign_name, campaign_id, "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", "ERROR"])
                    continue

                for field in totals:
                    totals[field] += stats[field]

                rows.append(build_row(campaign_name, campaign_id, stats))
                print(
                    "    Sent={sent} | Delivered={delivered} | Viewed={viewed} | Clicked={clicked} | "
                    "Errors={error} | Converted={converted}".format(**stats)
                )

            rows.append(build_totals_row(totals))

            worksheet = get_or_reset_tab(sheet, tab_name, len(rows) + 1)
            worksheet.update("A1", [OUTPUT_HEADER] + rows, value_input_option="USER_ENTERED")
            format_tab(sheet, worksheet, len(rows) + 1)
            print(f"  Done: {len(rows)} rows written to '{tab_name}' tab\n")

    print("All done! Check your Google Sheet.")


if __name__ == "__main__":
    args = parse_args()
    run(args.date)