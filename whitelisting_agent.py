"""
Step 1: Read pending rows from the 'whitelisting' tab and print them.
No clicking, no Selenium yet — just verifying the sheet parsing is correct.

Requires: pip install gspread python-dotenv playwright --break-system-packages
"""

import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import gspread
from playwright.sync_api import sync_playwright

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

BASE_DIR = Path(__file__).resolve().parent

# Value First Credentials by purpose
VF_CREDENTIALS = {
    "concierge": {"username": "cmwaconcierge", "password": "PEqIU'xE3>"},
    "emi": {"username": "cmwaemi", "password": "v'\\|\\|p-\"6G14KzC"},
    "fit": {"username": "cmwafit", "password": "H\"J7\\|5}~bth"},
    "collections": {"username": "cmwafitbusiness", "password": "vg#52rE7*"},
    "occupancyfhp": {"username": "clubmahdrawa", "password": "7%-C9~eZ8}"},
    "brand": {"username": "cmwabrand", "password": "v'\\|\\|p-\"6G14KzC"},
    "prospect": {"username": "cmwaprospect1", "password": "f-J<NEqO2*"},
    "referral_wa": {"username": "cmwareferal", "password": "jiZG%IcF5\""},
    "experience": {"username": "clubmahdrawa", "password": "7%-C9~eZ8}"},
    "bradcomm": {"username": "clubmahdrawa", "password": "7%-C9~eZ8}"},
}

# CleverTap Provider URLs by purpose
CT_PROVIDER_URLS = {
    "experience":   "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1776151055/template",
    "prospect":     "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1756206833/template",
    "concierge":    "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1755499424/template",
    "emi":          "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1759299990/template",
    "fit":          "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1759298451/template",
    "brand":        "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1753791574/template",
    "bradcomm":     "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1754305840/template",
    "collections":  "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1754306192/template",
    "occupancyfhp": "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1752212615/template",
    "referral_wa":  "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/account-setup/campaigns-journeys/channels/whatsapp/providers/1754305468/template",
}


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


def get_existing_template_names(ws):
    """
    Scans the entire sheet (Column E / 5) to collect all used template names.
    """
    all_values = ws.get_all_values()
    existing_names = set()
    for row in all_values[1:]:
        if len(row) >= 5:
            name = row[4].strip()
            if name:
                existing_names.add(name)
    return existing_names


def generate_template_name(purpose, date_added_str, existing_names):
    """
    Generates a collision-free template name formatted as purpose_YYYYMMDD.
    If it collides with existing_names, it appends _2, _3, etc.
    """
    date_str = None
    if date_added_str:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(date_added_str.strip(), fmt)
                date_str = dt.strftime("%Y%m%d")
                break
            except ValueError:
                continue
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    base_name = f"{purpose.lower().strip()}_{date_str}"
    candidate = base_name
    counter = 2
    while candidate in existing_names:
        candidate = f"{base_name}_{counter}"
        counter += 1
    existing_names.add(candidate)
    return candidate


def update_sheet_row(ws, sheet_row, col_name, value):
    """
    Updates a single cell in the sheet given the column key.
    """
    col_idx = COLUMNS[col_name]
    ws.update_cell(sheet_row, col_idx, str(value))


def select_angular_dropdown(page, dropdown_selector, option_text):
    """
    Selects an option from a custom Angular dropdown.
    """
    page.wait_for_selector(dropdown_selector, timeout=10000)
    page.click(dropdown_selector)
    page.wait_for_timeout(1000)

    menu_selectors = [
        f'.menu text:has-text("{option_text}")',
        f'.menu span:has-text("{option_text}")',
        f'.menu div:has-text("{option_text}")',
        f'.menu p:has-text("{option_text}")',
        f'.menu a:has-text("{option_text}")',
        f'text="{option_text}"'
    ]
    for selector in menu_selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.click()
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass

    # Final fallback
    try:
        page.click(f'text="{option_text}"')
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"Warning: Could not select option '{option_text}' via fallback: {e}", flush=True)


def fill_vf_login_form(page, username, password):
    """
    Fills and submits the Value First login form with multiple fallback selectors.
    """
    # User ID
    user_selectors = [
        'input[name="username"]',
        'input[placeholder="Your User ID"]',
        'input[type="text"]'
    ]
    user_filled = False
    for selector in user_selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.fill(username)
                user_filled = True
                break
        except Exception:
            pass
    if not user_filled:
        page.fill('input', username)

    # Password
    pwd_selectors = [
        'input[name="password"]',
        'input[placeholder="Your Password"]',
        'input[type="password"]'
    ]
    pwd_filled = False
    for selector in pwd_selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.fill(password)
                pwd_filled = True
                break
        except Exception:
            pass
    if not pwd_filled:
        page.fill('input[type="password"]', password)

    # Submit login form - using unique input#Login ID identified in diagnostics
    login_btn_selectors = [
        'input#Login',
        '#Login',
        'input[type="submit"]',
        'input[type="button"]',
        '.btn-login',
        'button:has-text("Login")'
    ]
    btn_clicked = False
    for selector in login_btn_selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.click()
                btn_clicked = True
                break
        except Exception:
            pass
    if not btn_clicked:
        try:
            page.click('input#Login')
        except Exception as e:
            print(f"Warning submitting login form: {e}", flush=True)


def fill_vf_form(page, row, template_name):
    """
    Fills and submits the Value First template creation form.
    """
    page.fill('input[formcontrolname="name"]', template_name)

    category = row["category"].upper().strip()
    select_angular_dropdown(
        page,
        'app-custom-select-with-create[formcontrolname="category"] span.placeholder-color',
        category
    )

    language = row["language"].strip()
    if language.lower() != "english":
        select_angular_dropdown(
            page,
            'app-custom-select-with-create[formcontrolname="language"] span.placeholder-color',
            language
        )

    header_type = row["header_type"].lower().strip()
    header_content = row["header_content"]

    if header_type == "none" or not header_type:
        try:
            page.click('mat-radio-button input[value="1"]', force=True)
        except Exception:
            page.click('text="None"')
    elif header_type == "text":
        try:
            page.click('mat-radio-button input[value="2"]', force=True)
        except Exception:
            page.click('text="Text"')
        page.wait_for_selector('input[formcontrolname="header_text"]', timeout=5000)
        page.fill('input[formcontrolname="header_text"]', header_content)
    elif header_type == "media":
        try:
            page.click('mat-radio-button input[value="3"]', force=True)
        except Exception:
            page.click('text="Media"')
        page.wait_for_selector('button:has-text("Image")', timeout=5000)
        page.click('button:has-text("Image")')
        input(f"\n[ACTION REQUIRED] Header is Media/Image for template '{template_name}'.\n"
              "Please upload the image manually in the browser, then press Enter here to continue...")

    page.wait_for_selector('textarea[formcontrolname="body"], #whatsappText', timeout=5000)
    try:
        page.fill('textarea[formcontrolname="body"]', row["body_text"])
    except Exception:
        page.fill('#whatsappText', row["body_text"])

    footer_text = row["footer_text"]
    if footer_text:
        page.fill('input[formcontrolname="footer_text"]', footer_text)

    # Add button
    page.click('span:has-text("+ Add a button")')
    page.wait_for_selector('.menu-transaction span:has-text("Visit Website")', timeout=5000)
    page.click('.menu-transaction span:has-text("Visit Website")')

    page.wait_for_selector('input[formcontrolname="text"]', timeout=5000)
    button_text = row["button_text"] or "Visit Website"
    page.fill('input[formcontrolname="text"]', button_text)

    page.fill('input[formcontrolname="url"]', 'https://gi9.in/{{1}}')

    page.wait_for_selector('span:has-text("Select"):near(label:has-text("URL Type"))', timeout=5000)
    page.click('span:has-text("Select"):near(label:has-text("URL Type"))')
    page.wait_for_timeout(500)

    try:
        page.click('span:has-text("dynamic")')
    except Exception:
        page.click('.menu span:has-text("dynamic")')

    page.click('button[type="submit"]')
    page.wait_for_timeout(3000)


def poll_vf_for_approval(page, template_name, timeout_minutes=15):
    """
    Polls the Value First template list until Status is APPROVED, then returns VF Template Id.
    """
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        try:
            page.wait_for_selector('input[placeholder="Search By TemplateName"]', timeout=15000)
            page.fill('input[placeholder="Search By TemplateName"]', template_name)
            page.click('button:has-text("Search")')
            page.wait_for_timeout(3000)

            # Find the row — table columns: Vf Template Id, Whatsapp Id, Template Name, Status
            rows = page.query_selector_all('table tbody tr')
            for row in rows:
                cells = row.query_selector_all('td')
                if len(cells) >= 4:
                    row_template_name = cells[2].inner_text().strip()
                    row_status = cells[3].inner_text().strip()
                    row_vf_id = cells[0].inner_text().strip()
                    if row_template_name == template_name:
                        if row_status == "APPROVED":
                            return row_vf_id
                        elif row_status == "REJECTED":
                            raise Exception(f"Template '{template_name}' was REJECTED by WhatsApp")
        except Exception as e:
            # If search or table querying fails (e.g. temporary network/session issue), print warning
            print(f"  Warning during polling search check: {e}", flush=True)

        # Check if we were logged out during polling
        if "login" in page.url:
            print("  Session expired during polling. Re-login is required.", flush=True)
            raise Exception("Value First session expired during polling.")

        print(f"  Status not APPROVED yet, waiting 60s... ({template_name})", flush=True)
        time.sleep(60)

    raise TimeoutError(f"Template '{template_name}' not approved within {timeout_minutes} minutes")


def check_ct_checkbox(page, label_text):
    """
    Robustly checks a checkbox on CleverTap page near or matching the label_text.
    """
    try:
        page.check(f'input[type="checkbox"]:near(text="{label_text}")')
    except Exception:
        try:
            page.click(f'label:has-text("{label_text}")')
        except Exception as e:
            print(f"Warning: Could not check checkbox for '{label_text}': {e}", flush=True)


def create_ct_template(ct_page, purpose, vf_template_id, body_text, footer_text, button_text, header_type, header_content):
    """
    Navigates to CleverTap, fills, and submits the template creation form.
    """
    provider_url = CT_PROVIDER_URLS[purpose.lower()]
    ct_page.goto(provider_url)
    ct_page.wait_for_load_state("networkidle")

    # Click "+ Template" button
    ct_page.wait_for_selector('button:has-text("+ Template")', timeout=15000)
    ct_page.click('button:has-text("+ Template")')

    # Select template type: Basic
    ct_page.wait_for_selector('text=Basic', timeout=10000)
    ct_page.click('text=Basic')

    # Wait for create template fields
    ct_page.wait_for_selector('input[placeholder="Enter template name"]', timeout=10000)

    # Template Name = VF Template ID
    ct_page.fill('input[placeholder="Enter template name"]', str(vf_template_id))

    # Header
    if header_type.lower() != "none":
        check_ct_checkbox(ct_page, "Header")
        if header_type.lower() == "text":
            ct_page.fill('input[placeholder="Enter header text"]', header_content)
        elif header_type.lower() == "media":
            input(f"\n[ACTION REQUIRED] Please upload the header image manually in CleverTap, then press Enter here...")

    # Body
    ct_page.fill('textarea[placeholder="Enter the text for your message..."]', body_text)

    # Footer
    if footer_text:
        check_ct_checkbox(ct_page, "Footer")
        ct_page.fill('input[placeholder="Enter footer text"]', footer_text)

    # Button
    if button_text:
        check_ct_checkbox(ct_page, "Button")
        ct_page.wait_for_timeout(500)
        ct_page.fill('input[placeholder="Button text"]', button_text)

    # Submit
    ct_page.click('button:has-text("Submit")')
    ct_page.wait_for_timeout(2000)
    print(f"  CleverTap template created with name: {vf_template_id}", flush=True)


def main():
    print("Connecting to Google Sheets...", flush=True)
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)

    rows = get_pending_rows()
    if not rows:
        print("No pending rows found (or all are RCS/already processed).", flush=True)
        return

    print(f"Found {len(rows)} pending WhatsApp row(s) to process.", flush=True)

    print("Fetching existing template names from sheet to avoid name collisions...", flush=True)
    existing_names = get_existing_template_names(ws)
    print(f"Loaded {len(existing_names)} existing template names.", flush=True)

    with sync_playwright() as p:
        # Separate persistent context for CleverTap
        print("Launching persistent browser context for CleverTap...", flush=True)
        ct_profile_dir = BASE_DIR / ".playwright_ct_profile"
        ct_context = p.chromium.launch_persistent_context(
            user_data_dir=str(ct_profile_dir),
            headless=False,
            args=["--start-maximized"]
        )
        ct_page = ct_context.new_page()

        # Check CleverTap login
        print("Checking CleverTap dashboard session...", flush=True)
        ct_page.goto("https://in1.dashboard.clevertap.com/W8W-6R9-885Z")
        ct_page.wait_for_timeout(2000)
        if "login" in ct_page.url or "accounts.google.com" in ct_page.url:
            print("\n" + "="*80, flush=True)
            print("[ACTION REQUIRED] CleverTap login required.", flush=True)
            print("Please log in to CleverTap in the browser window.", flush=True)
            print("Press Enter in this terminal after landing on the dashboard...", flush=True)
            print("="*80 + "\n", flush=True)
            input()

        # Keep track of active VF browsers to avoid repetitive logins
        vf_contexts = {}

        for row in rows:
            purpose = row["purpose"].lower().strip()
            sheet_row = row["sheet_row"]

            if purpose not in VF_CREDENTIALS:
                print(f"ERROR: No Value First credentials configured for purpose '{purpose}' (row {sheet_row}). Skipping.", flush=True)
                update_sheet_row(ws, sheet_row, "status", f"Error: No credentials for purpose '{purpose}'")
                continue

            print(f"\nProcessing Row {sheet_row} (Purpose: {purpose})", flush=True)

            # Generate template name
            template_name = generate_template_name(purpose, row["date_added"], existing_names)
            print(f"Generated template name: {template_name}", flush=True)

            # Get or launch VF session
            if purpose not in vf_contexts:
                creds = VF_CREDENTIALS[purpose]
                user_data_dir = BASE_DIR / f".playwright_vf_profile_{purpose}"
                print(f"Launching persistent browser context for Value First ({creds['username']})...", flush=True)
                vf_ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=False,
                    args=["--start-maximized"]
                )
                vf_pg = vf_ctx.new_page()
                print("Navigating to Value First home...", flush=True)
                vf_pg.goto("https://mis.myvaluefirst.com/vmpreport/home.jsp#noback")
                vf_pg.wait_for_timeout(4000)

                # Check if we are on login screen by looking for username input field or placeholder
                is_login_page = False
                try:
                    vf_pg.wait_for_selector('input[placeholder="Your User ID"], input[name="username"]', timeout=5000)
                    is_login_page = True
                except Exception:
                    pass

                print(f"Value First login page detected: {is_login_page} (URL: {vf_pg.url})", flush=True)

                if is_login_page or "login" in vf_pg.url:
                    print(f"Logging in to Value First account: {creds['username']}...", flush=True)
                    fill_vf_login_form(vf_pg, creds["username"], creds["password"])

                    print("\n" + "="*80, flush=True)
                    print(f"[ACTION REQUIRED] OTP sent to manager's phone for Value First ({creds['username']}).", flush=True)
                    print("Please enter the OTP in the browser window to complete login,", flush=True)
                    print("then press Enter in this terminal to continue...", flush=True)
                    print("="*80 + "\n", flush=True)
                    input()

                    print("Waiting for Value First redirect...", flush=True)
                    try:
                        vf_pg.wait_for_url("**/home.jsp**", timeout=120000)
                    except Exception as e:
                        print(f"Warning: wait_for_url timed out or failed: {e}", flush=True)

                vf_contexts[purpose] = (vf_ctx, vf_pg)

            _, vf_page = vf_contexts[purpose]

            try:
                print("Navigating to Create Message Template on Value First...", flush=True)
                vf_page.goto("https://mis.myvaluefirst.com/vmpreport/home.jsp#noback")
                vf_page.wait_for_timeout(2000)

                vf_page.wait_for_selector('text=Whatsapp Template Management', timeout=15000)
                vf_page.click('text=Whatsapp Template Management')

                vf_page.wait_for_selector('button:has-text("Create Message Template")', timeout=15000)
                vf_page.click('button:has-text("Create Message Template")')

                # Fill and submit form
                print("Filling out Create Message Template form...", flush=True)
                fill_vf_form(vf_page, row, template_name)

                # Update sheet immediately to Submitted to VF
                print("Updating sheet status to 'Submitted to VF'...", flush=True)
                update_sheet_row(ws, sheet_row, "template_name", template_name)
                update_sheet_row(ws, sheet_row, "status", "Submitted to VF")

                # Navigate back to template list
                print("Navigating back to templates list for polling...", flush=True)
                vf_page.goto("https://mis.myvaluefirst.com/vmpreport/home.jsp#noback")
                vf_page.wait_for_selector('text=Whatsapp Template Management', timeout=15000)
                vf_page.click('text=Whatsapp Template Management')

                # Poll until status is APPROVED
                vf_template_id = poll_vf_for_approval(vf_page, template_name)
                print(f"APPROVED! VF Template ID: {vf_template_id}", flush=True)

                # Create template in CleverTap
                print(f"Creating template in CleverTap with name: {vf_template_id}...", flush=True)
                create_ct_template(
                    ct_page,
                    purpose,
                    vf_template_id,
                    row["body_text"],
                    row["footer_text"],
                    row["button_text"],
                    row["header_type"],
                    row["header_content"]
                )

                # Write back VF ID and Done status to sheet
                print("Writing final status and VF ID to sheet...", flush=True)
                update_sheet_row(ws, sheet_row, "vf_template_id", vf_template_id)
                update_sheet_row(ws, sheet_row, "status", "Done")
                print(f"Successfully completed row {sheet_row}!", flush=True)

            except Exception as e:
                print(f"ERROR processing row {sheet_row}: {e}", flush=True)
                # Take screenshot of failure
                try:
                    screenshot_path = BASE_DIR / f"failure_row_{sheet_row}.png"
                    vf_page.screenshot(path=str(screenshot_path))
                    print(f"Saved failure screenshot to: {screenshot_path}", flush=True)
                except Exception as se:
                    print(f"Could not save failure screenshot: {se}", flush=True)

                err_msg = f"Error: {str(e)[:100]}"
                update_sheet_row(ws, sheet_row, "status", err_msg)
                # Proceed to next row
                continue

        # Clean close all Playwright contexts
        print("\nAll pending rows processed. Closing browser contexts...", flush=True)
        for ctx, _ in vf_contexts.values():
            try:
                ctx.close()
            except Exception:
                pass
        try:
            ct_context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()