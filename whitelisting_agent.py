"""
Step 1: Read pending rows from the 'whitelisting' tab and print them.
No clicking, no Selenium yet — just verifying the sheet parsing is correct.

Requires: pip install gspread python-dotenv --break-system-packages
"""

import os
from dotenv import load_dotenv
import gspread

load_dotenv()

SHEET_ID = os.environ["SHEET_ID"]
SERVICE_ACCOUNT_FILE = os.environ["SERVICE_ACCOUNT_FILE"]
TAB_NAME = "whitelisting"

# Column layout (1-indexed, matches your sheet as of 2026-06-30)
COLUMNS = {
    "row_id": 1,
    "date_added": 2,
    "purpose": 3,
    "channel": 4,
    "template_name": 5,
    "category": 6,
    "language": 7,
    "header_type": 8,
    "header_content": 9,
    "body_text": 10,
    "footer_text": 11,
    "button_type": 12,       # always "Visit Website" per your confirmation
    "button_text": 13,
    "button_value": 14,      # URL suffix / phone / offer code depending on type
    "status": 15,
    "vf_template_id": 16,
}

CONCIERGE_PHONE = "2264898899"
GI9_BASE_URL = "https://gi9.in/"


def get_pending_rows():
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)

    all_values = ws.get_all_values()
    header = all_values[0]
    data_rows = all_values[1:]

    pending = []
    for i, row in enumerate(data_rows, start=2):  # row 2 = first data row
        # Pad row in case trailing columns are empty/missing
        row = row + [""] * (len(COLUMNS) - len(row))

        def cell(name):
            idx = COLUMNS[name] - 1
            return row[idx].strip() if idx < len(row) else ""

        row_id = cell("row_id")
        status = cell("status")

        # Skip fully blank rows
        if not row_id and not cell("purpose") and not cell("body_text"):
            continue

        # Only process rows that are blank or "Pending"
        if status not in ("", "Pending"):
            continue

        channel = cell("channel").upper()
        if channel == "RCS":
            # Out of scope for this script — VF/CT WhatsApp flow only
            continue

        purpose = cell("purpose")
        # Button is permanently "Visit Website" with a fixed dynamic URL.
        # Only the button text varies per row — the URL itself never changes.
        button_type = "Visit Website"
        website_url = f"{GI9_BASE_URL}{{{{1}}}}"  # always https://gi9.in/{{1}}

        record = {
            "sheet_row": i,
            "row_id": row_id,
            "date_added": cell("date_added"),
            "purpose": purpose,
            "channel": channel,
            "template_name": cell("template_name"),
            "category": cell("category"),
            "language": cell("language") or "English",
            "header_type": cell("header_type") or "None",
            "header_content": cell("header_content"),
            "body_text": cell("body_text"),
            "footer_text": cell("footer_text"),
            "button_type": button_type,
            "button_text": cell("button_text"),
            "website_url": website_url,
            "status": status,
        }
        pending.append(record)

    return pending


def main():
    rows = get_pending_rows()
    if not rows:
        print("No pending rows found (or all are RCS/already processed).")
        return

    print(f"Found {len(rows)} pending WhatsApp row(s):\n")
    for r in rows:
        print("=" * 60)
        print(f"Sheet Row : {r['sheet_row']}  (Row ID: {r['row_id']})")
        print(f"Purpose   : {r['purpose']}  |  Channel: {r['channel']}")
        print(f"Category  : {r['category']}  |  Language: {r['language']}")
        print(f"Header    : {r['header_type']} -> {r['header_content']!r}")
        print(f"Body      : {r['body_text']!r}")
        print(f"Footer    : {r['footer_text']!r}")
        print(f"Button    : {r['button_type']} | text={r['button_text']!r}")
        print(f"Website URL: {r['website_url']!r}")
        print()


if __name__ == "__main__":
    main()