"""
CleverTap Daily Stats -> Google Sheets
Uses CleverTap's internal dashboard API (calculateTrend.html)

Writes daily resort tabs for Day0, Day5, and Day15 and also writes selected
prospect campaign counts into separate WhatsApp and SMS tabs.
"""

from __future__ import annotations

print(
    "Loading CleverTap Stats script, please wait (this can take 30-60s on macOS)...",
    flush=True,
)

import argparse
import atexit
import sys
import concurrent.futures
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import gspread
import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _load_groups(filename: str) -> dict[str, list[tuple[str, int]]]:
    path = BASE_DIR / filename
    if not path.exists():
        # Case-insensitive fallback for strictly case-sensitive filesystems like Linux/GitHub Actions
        found = False
        if BASE_DIR.exists():
            for p in BASE_DIR.iterdir():
                if p.name.lower() == filename.lower():
                    path = p
                    found = True
                    break
        if not found:
            raise FileNotFoundError(f"Data file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {group: [tuple(pair) for pair in entries] for group, entries in raw.items()}


JOURNEYS = _load_groups("journeys.json")

DAY_GROUPS = ("Day0", "Day5", "Day15")


PROSPECT_GROUPS = {
    "WhatsApp": [
        ("Prospect01_WA_PRO_Consent_AUTO", 1770366987),
        ("Prospect02_WA_HFRP_Consent_AUTO", 1770359003),
        ("Prospect03_WA_HFRP_Member_AUTO", 1770359258),
        ("Prospect04_WA_Welcome_AUTO", 1770361107),
        ("Prospect05_WA_MissedYou_AUTO", 1770361924),
        ("Prospect06_WA_Confirmation_AUTO", 1770362059),
        ("Prospect07_WA_MeetingReminder_AUTO", 1782130745),
        ("Prospect08_WA_SaleConfirmation_AUTO", 1770362424),
        ("Prospect09_WA_Rescheduled_AUTO", 1782133303),
        ("Prospect10_WA_FollowUp_AUTO", 1770363126),
        ("Prospect11_WA_NotIntrested_AUTO", 1771825803),
        ("Prospect12_WA_NotQualified_AUTO", 1770363503),
        ("Prospect13_WA_Welcome_consenttrue_AUTO", 1778758056),
    ],
    "SMS": [
        ("Prospect02_SMS_HFRP_Consent_FB_AUTO", 1782297003),
        ("Prospect03_SMS_HFRP_Member_FB_AUTO", 1782297172),
        ("Prospect04_SMS_Welcome_AUTO", 1779860939),
        ("Prospect05_SMS_MissedYou_FB_AUTO", 1782297422),
        ("Prospect06_SMS_Confirmation_FB_AUTO", 1782297552),
        ("Prospect07_SMS_MeetingReminder_FB_AUTO", 1783498729),
        ("Prospect08_SMS_SaleConfirmation_FB_AUTO", 1782297976),
        ("Prospect09_SMS_Rescheduled_FB_AUTO", 1782298110),
        ("Prospect10_SMS_FollowUp_FB_AUTO", 1782298313),
        ("Prospect11_SMS_NotIntrested_FB_AUTO", 1782298443),
        ("Prospect13_SMS_Welcome_consenttrue_FB_AUTO", 1782298649),
    ],
}

CONCIERGE_GROUPS: dict[str, list[tuple[str, int]]] = {
    "Concierge": [
        ("WA_Day05_SameState", 4140),
        ("WA_Day05_DifferentState", 4153),
        ("WA_Day05_International", 4166),
        ("WA_Day20_SameState", 4105),
        ("WA_Day20_DifferentState", 4118),
        ("WA_Day30_SameState", 3980),
        ("WA_Day30_DifferentState", 3993),
        ("WA_Day60_SameState", 3934),
        ("WA_Day60_DifferentState", 3947),
        ("WA_Day60_International", 3960),
    ]
}

SHEET_HEADER = [
    "Date",
    "Node Name",
    "Campaign ID",
    "Sent",
    "Delivered",
    "Viewed",
    "Clicked",
]
TAB_COLORS = {
    "Day0": "#2563EB",
    "Day5": "#0F766E",
    "Day15": "#7C3AED",
    "WhatsApp": "#B91C1C",
    "SMS": "#0F766E",
    "Concierge": "#D97706",
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


load_env_file(ENV_FILE)

SHEET_ID = os.getenv("SHEET_ID", "")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
CT_COOKIE = os.getenv("CT_COOKIE", "")
CT_CSRF_TOKEN = os.getenv("CT_CSRF_TOKEN", "")
CT_BASE_URL = os.getenv(
    "CT_BASE_URL", "https://in1.dashboard.clevertap.com/W8W-6R9-885Z"
)
CT_REFERER_URL = os.getenv(
    "CT_REFERER_URL",
    "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/journeys/journey/239/report/node-stats",
)
CT_FROM_DATE = os.getenv("CT_FROM_DATE", "20260419")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

API_MAX_RETRIES = 3
SHEETS_MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2
SHEETS_CONNECT_TIMEOUT_SECONDS = float(
    os.getenv("SHEETS_CONNECT_TIMEOUT_SECONDS", "10")
)
SHEETS_READ_TIMEOUT_SECONDS = float(os.getenv("SHEETS_READ_TIMEOUT_SECONDS", "20"))


HEADED_MODE = False
session_client = requests.Session()
playwright_instance = None
context_instance = None
page_instance = None


def close_browser_at_exit() -> None:
    global playwright_instance, context_instance
    try:
        if context_instance:
            context_instance.close()
        if playwright_instance:
            playwright_instance.stop()
    except Exception:
        pass


atexit.register(close_browser_at_exit)


def init_requests_session() -> None:
    global CT_COOKIE, CT_CSRF_TOKEN, session_client

    jar = requests.cookies.RequestsCookieJar()
    if CT_COOKIE:
        for cookie_part in CT_COOKIE.split(";"):
            cookie_part = cookie_part.strip()
            if not cookie_part or "=" not in cookie_part:
                continue
            name, val = cookie_part.split("=", 1)
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            jar.set(name, val, domain="in1.dashboard.clevertap.com")

    session_client.cookies = jar
    print("Initialized requests session with current cookies.")


class CleverTapAuthError(Exception):
    """Raised when CleverTap authentication fails critically (e.g. session expired, MFA required, timeout)."""



def get_totp_token(secret: str) -> str:
    import base64
    import hashlib
    import hmac
    import struct
    import time

    secret = secret.replace(" ", "").upper()
    missing_padding = len(secret) % 8
    if missing_padding:
        secret += "=" * (8 - missing_padding)

    key = base64.b32decode(secret)
    intervals_no = int(time.time()) // 30
    msg = struct.pack(">Q", intervals_no)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[19] & 15
    token = (struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{token:06d}"


def refresh_clevertap_session(
    headed: bool = False, skip_logout: bool = False, manual: bool = False
) -> None:
    global \
        CT_COOKIE, \
        CT_CSRF_TOKEN, \
        playwright_instance, \
        context_instance, \
        page_instance

    print("Starting CleverTap session refresh...", flush=True)
    print(f"Headed mode: {headed}", flush=True)

    try:
        print("Loading Playwright libraries...", flush=True)
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise CleverTapAuthError(
            "Playwright is not installed. Please run: pip install playwright && playwright install chromium"
        ) from e

    try:
        if not playwright_instance:
            print("Initializing Playwright driver...", flush=True)
            playwright_instance = sync_playwright().start()

        user_data_dir = BASE_DIR / ".playwright_user_data"
        launch_args = {
            "user_data_dir": str(user_data_dir),
            "headless": not headed,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        # Do not use system Chrome channel on macOS to avoid AppleEvents automation permission prompt hangs
        # if headed:
        #     launch_args["channel"] = "chrome"

        if context_instance:
            try:
                context_instance.close()
            except Exception:
                pass

        print("Launching Chromium browser...", flush=True)
        context_instance = playwright_instance.chromium.launch_persistent_context(
            **launch_args
        )
        context = context_instance
        context.set_default_timeout(3000)
        context.set_default_navigation_timeout(30000)

        # Clear only CleverTap cookies to preserve Google's device trust footprint
        if not skip_logout:
            try:
                all_cookies = context.cookies()
                google_cookies = [
                    c
                    for c in all_cookies
                    if "clevertap" not in c.get("domain", "").lower()
                ]
                context.clear_cookies()
                if google_cookies:
                    context.add_cookies(google_cookies)
            except Exception:
                pass

        page_instance = context.pages[0] if context.pages else context.new_page()
        page = page_instance
        page.set_viewport_size({"width": 1280, "height": 720})

        captured_csrf = None

        def handle_request(request):
            nonlocal captured_csrf
            csrf = request.headers.get("x-clevertap-csrf-token")
            if csrf:
                captured_csrf = csrf

        page.on("request", handle_request)

        url = "https://in1.dashboard.clevertap.com/W8W-6R9-885Z/"

        if not skip_logout:
            print(
                "Force-signing out of Google account to show the complete login flow to the manager..."
            )
            page.goto("https://accounts.google.com/Logout")
            page.wait_for_timeout(3000)

        print(f"Navigating to dashboard: {url}")
        page.goto(url)
        page.wait_for_timeout(3000)

        current_url = page.url
        print(f"Current browser URL: {current_url}")

        if "sso.clevertap.com" in current_url or "google.com" in current_url:
            if manual:
                print("\n" + "=" * 80)
                print("[MANUAL LOGIN MODE]")
                print(
                    "Please log in to CleverTap/Google SSO manually in the browser window."
                )
                print("Once you successfully land on the CleverTap dashboard page,")
                print("return to this terminal and press ENTER to continue...")
                print("=" * 80 + "\n")
                try:
                    input("Press ENTER when you have successfully logged in: ")
                except (KeyboardInterrupt, SystemExit):
                    context.close()
                    raise
                logged_in = True
            else:
                print(
                    "CleverTap login or Google SSO required. Starting automated login..."
                )

                email = os.getenv("CLEVERTAP_EMAIL", "dev@attributics.com")
                password = os.getenv("CLEVERTAP_PASSWORD")
                totp_secret = os.getenv("CLEVERTAP_TOTP_SECRET")

                if not password or password == "PASTE_YOUR_PASSWORD_HERE":
                    if not headed:
                        context.close()
                        raise CleverTapAuthError(
                            "CLEVERTAP_PASSWORD is not configured in .env. Please fill in your password to enable headless login."
                        )
                    else:
                        print(
                            "CLEVERTAP_PASSWORD is not configured in .env. Proceeding with manual login in headed browser window..."
                        )

                logged_in = False

            selection_clicked_try_another = False
            last_logged_url = ""
            for attempt in range(120):  # Up to 2 minutes timeout
                if manual:
                    break
                page.wait_for_timeout(1000)
                curr_url = page.url
                if curr_url != last_logged_url:
                    print(f"Current browser URL: {curr_url}")
                    last_logged_url = curr_url

                if (
                    "in1.dashboard.clevertap.com" in curr_url
                    and "google" not in curr_url
                    and "accounts.youtube" not in curr_url
                    and "error" not in curr_url.lower()
                ):
                    print("Redirect to CleverTap dashboard detected! Login successful.")
                    logged_in = True
                    break

                # Check for wrong password warning on Google page
                try:
                    body_text = page.locator("body").inner_text()
                    if (
                        "Wrong password" in body_text
                        or "Contraseña incorrecta" in body_text
                    ):
                        print(
                            "\n[WARNING] Google reported: Wrong password. Please check CLEVERTAP_PASSWORD in your .env file.\n"
                        )
                except Exception:
                    pass

                # If headed and automated login is blocked or taking too long, fallback to manual login
                if headed:
                    try:
                        body_text = page.locator("body").inner_text()
                        is_blocked = (
                            "not be secure" in body_text
                            or "browser or app may not be secure" in body_text
                        )
                    except Exception:
                        is_blocked = False

                    if is_blocked or attempt >= 20:
                        print("\n" + "=" * 80)
                        print("[MANUAL FALLBACK DETECTED]")
                        if is_blocked:
                            print(
                                "Google blocked automated login ('This browser or app may not be secure')."
                            )
                        else:
                            print(
                                "Automated login is taking longer than expected / requires verification."
                            )
                        print(
                            "Please complete the login/verification manually in the headed browser window."
                        )
                        print(
                            "Once you successfully land on the CleverTap dashboard page,"
                        )
                        print("return to this terminal and press ENTER to continue...")
                        print("=" * 80 + "\n")
                        try:
                            input("Press ENTER when you have successfully logged in: ")
                            curr_url = page.url
                            if (
                                "in1.dashboard.clevertap.com" in curr_url
                                and "google" not in curr_url
                                and "accounts.youtube" not in curr_url
                                and "error" not in curr_url.lower()
                            ):
                                print(
                                    "Redirect to CleverTap dashboard detected! Login successful."
                                )
                                logged_in = True
                                break
                        except (KeyboardInterrupt, SystemExit):
                            context.close()
                            raise

                # 1. Click "Continue with Google" on SSO page
                if "sso.clevertap.com" in curr_url:
                    try:
                        google_btn = page.locator('text="Continue with Google"')
                        if google_btn.is_visible(timeout=1000):
                            google_btn.click()
                            print("Auto-clicked 'Continue with Google' button.")
                            page.wait_for_timeout(2000)
                    except Exception:
                        pass

                # 1.5 Click Google Account Chooser if visible
                if "accountchooser" in curr_url:
                    try:
                        account_item = page.locator(f'text="{email}"')
                        if account_item.is_visible(timeout=1000):
                            account_item.click()
                            print(f"Auto-clicked Google account chooser item: {email}")
                            page.wait_for_timeout(2000)
                            continue
                    except Exception:
                        pass

                # 2. Fill Google Email screen
                try:
                    email_input = page.locator(
                        'input[type="email"], input[name="identifier"]'
                    ).first
                    if email_input.is_visible(timeout=1000):
                        email_input.click()
                        email_input.fill("")
                        email_input.press_sequentially(email, delay=100)
                        page.locator(
                            '#identifierNext, button:has-text("Next"), button:has-text("Siguiente")'
                        ).first.click()
                        print("Filled email and clicked next.")
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

                # 3. Fill Google Password screen
                try:
                    pwd_input = page.locator('input[type="password"]').first
                    if pwd_input.is_visible(timeout=1000) and password and password != "PASTE_YOUR_PASSWORD_HERE":
                        pwd_input.click()
                        pwd_input.fill("")
                        pwd_input.press_sequentially(password, delay=100)
                        page.locator(
                            '#passwordNext, button:has-text("Next"), button:has-text("Siguiente")'
                        ).first.click()
                        print("Filled password and clicked next.")
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

                # 3.5 Handle Google Challenge Selection screen (e.g. Choose how you want to sign in)
                if "challenge/selection" in curr_url:
                    try:
                        # Check for authenticator option
                        authenticator_option = page.locator(
                            'div[role="link"]:has-text("Authenticator"), div[role="button"]:has-text("Authenticator"), span:has-text("Authenticator"), li:has-text("Authenticator")'
                        ).first
                        if authenticator_option.is_visible(timeout=1000):
                            authenticator_option.click()
                            print("Clicked Authenticator app option.")
                            page.wait_for_timeout(2000)
                            continue

                        # Prioritize phone option ending in 91 to send SMS (since 61 is locked out)
                        phone_option_91 = page.locator(
                            'div[role="link"]:has-text("91"), div[role="button"]:has-text("91"), span:has-text("91"), li:has-text("91")'
                        ).first
                        if phone_option_91.is_visible(timeout=1000):
                            phone_option_91.click()
                            print(
                                "Clicked phone option ending in 91 to bypass rate-limited option..."
                            )
                            page.wait_for_timeout(2000)
                            continue

                        # If we haven't clicked Try another way yet, try it once
                        if not selection_clicked_try_another:
                            try_another = page.locator(
                                'button:has-text("Try another way"), a:has-text("Try another way"), div[role="button"]:has-text("Try another way"), span:has-text("Try another way")'
                            ).first
                            if try_another.is_visible(timeout=1000):
                                try_another.click()
                                print(
                                    "Clicked 'Try another way' to show other verification methods."
                                )
                                selection_clicked_try_another = True
                                page.wait_for_timeout(2000)
                                continue

                        # Fallback if only 61 is available (e.g. if we need to let the user manually deal with Google locks)
                        phone_option_61 = page.locator(
                            'div[role="link"]:has-text("61"), div[role="button"]:has-text("61"), span:has-text("61"), li:has-text("61")'
                        ).first
                        if phone_option_61.is_visible(timeout=1000):
                            phone_option_61.click()
                            print(
                                "Only phone option ending in 61 available. Clicked it to proceed..."
                            )
                            page.wait_for_timeout(2000)
                            continue
                    except Exception as e:
                        print(f"Debug exception in selection block: {e}")

                # 3.8 Handle Google Phone Number Confirmation screen (challenge/ipp/collect)
                if "challenge/ipp/collect" in curr_url:
                    try:
                        page_text = page.locator("body").inner_text()
                        # If Google is asking to confirm the blocked 61 number, click 'Try another way' to go back
                        if "61" in page_text or "ending in 61" in page_text:
                            try_another = page.locator(
                                'button:has-text("Try another way"), a:has-text("Try another way"), div[role="button"]:has-text("Try another way"), span:has-text("Try another way")'
                            ).first
                            if try_another.is_visible(timeout=1000):
                                try_another.click()
                                print(
                                    "Detected rate-limited 61 confirmation page. Clicked 'Try another way' to return to selection..."
                                )
                                page.wait_for_timeout(2000)
                                continue
                    except Exception as e:
                        print(f"Debug exception in collect block: {e}")

                    print(
                        "\n[ACTION REQUIRED] Google is asking to confirm your registered phone number."
                    )
                    print(
                        "Please type the registered phone number in the headed browser window to continue."
                    )
                    page.wait_for_timeout(3000)
                    continue

                # 4. Fill Google TOTP MFA screen (Authenticator app only)
                try:
                    totp_input = page.locator('input[type="tel"], input#totpPin').first
                    if totp_input.is_visible(timeout=1000):
                        page_text = page.locator("body").inner_text()
                        is_sms_page = "challenge/ipp/verify" in curr_url or (
                            "text message" in page_text.lower()
                            and (
                                "sent" in page_text.lower()
                                or "code" in page_text.lower()
                            )
                        )
                        if is_sms_page:
                            print(
                                "\n[ACTION REQUIRED] Google is forcing SMS verification to your manager's number."
                            )
                            try:
                                sms_code = input(
                                    "Please type the 6-digit SMS verification code here: "
                                ).strip()
                            except (KeyboardInterrupt, SystemExit):
                                raise
                            except Exception:
                                sms_code = ""

                            if sms_code:
                                totp_input.click()
                                totp_input.fill("")
                                totp_input.press_sequentially(sms_code, delay=100)
                                page.locator(
                                    '#totpNext, button:has-text("Next"), button:has-text("Siguiente")'
                                ).first.click()
                                print("Submitted manually entered SMS code.")
                                page.wait_for_timeout(3000)
                            continue

                        if totp_secret:
                            code = get_totp_token(totp_secret)
                            current_val = totp_input.input_value()
                            if current_val != code:
                                totp_input.click()
                                totp_input.fill("")
                                totp_input.press_sequentially(code, delay=100)
                                page.locator(
                                    '#totpNext, button:has-text("Next"), button:has-text("Siguiente")'
                                ).first.click()
                                print(f"Filled TOTP MFA code: {code} and clicked next.")
                                page.wait_for_timeout(2000)
                except Exception:
                    pass

            if not logged_in:
                context.close()
                raise CleverTapAuthError(
                    "SSO login automation timed out. Please run with --headed and verify credentials in .env."
                )

        page.wait_for_timeout(3000)
        cookies = context.cookies()

    except Exception as e:
        if isinstance(e, CleverTapAuthError):
            raise
        raise CleverTapAuthError(f"Playwright automation failed: {e}") from e

    cookie_parts = []
    csrf_cookie_val = None

    # Only keep cookies belonging to clevertap.com or subdomains
    clevertap_cookies = [c for c in cookies if "clevertap.com" in c.get("domain", "")]
    cookie_names = [c["name"] for c in clevertap_cookies]
    print(f"Debug: Found CleverTap cookies in browser context: {cookie_names}")

    for c in clevertap_cookies:
        cookie_parts.append(f"{c['name']}={c['value']}")
        if c["name"] == "csrf":
            csrf_cookie_val = c["value"]

    if not csrf_cookie_val:
        csrf_cookie_val = captured_csrf
        print(
            f"Debug: csrf cookie not found. Captured CSRF header value: {captured_csrf}"
        )

    if not csrf_cookie_val:
        raise CleverTapAuthError(
            "Failed to extract CSRF token (csrf cookie/header not found). "
            f"Available CleverTap cookies: {cookie_names}"
        )

    cookie_str = "; ".join(cookie_parts)

    CT_COOKIE = cookie_str
    CT_CSRF_TOKEN = csrf_cookie_val

    # Save refreshed session cookies and CSRF token back to .env
    try:
        if ENV_FILE.exists():
            env_content = ENV_FILE.read_text()
            lines = env_content.splitlines()
            cookie_replaced = False
            csrf_replaced = False
            for i, line in enumerate(lines):
                if line.strip().startswith("CT_COOKIE="):
                    lines[i] = f'CT_COOKIE="{cookie_str}"'
                    cookie_replaced = True
                elif line.strip().startswith("CT_CSRF_TOKEN="):
                    lines[i] = f'CT_CSRF_TOKEN="{csrf_cookie_val}"'
                    csrf_replaced = True
            if not cookie_replaced:
                lines.append(f'CT_COOKIE="{cookie_str}"')
            if not csrf_replaced:
                lines.append(f'CT_CSRF_TOKEN="{csrf_cookie_val}"')
            ENV_FILE.write_text("\n".join(lines) + "\n")
            print("Saved refreshed CleverTap session cookies to .env file.")
        else:
            ENV_FILE.write_text(
                f'CT_COOKIE="{cookie_str}"\nCT_CSRF_TOKEN="{csrf_cookie_val}"\n'
            )
            print("Created new .env file with refreshed CleverTap session cookies.")
    except Exception as e:
        print(f"Warning: Could not save refreshed cookies to .env: {e}")

    init_requests_session()
    print("CleverTap session refreshed successfully!")


session_lock = threading.Lock()


def safe_refresh_session(old_csrf: str) -> None:
    with session_lock:
        current_csrf = session_client.cookies.get("csrf", default="")
        if current_csrf and current_csrf != old_csrf:
            return
        refresh_clevertap_session(headed=HEADED_MODE)


def validate_config() -> None:
    missing = []

    if not SHEET_ID:
        missing.append("SHEET_ID")

    if missing:
        raise ValueError(
            "Missing required config: "
            f"{', '.join(missing)}. Add them to environment variables or {ENV_FILE.name}."
        )

    service_account_path = BASE_DIR / SERVICE_ACCOUNT_FILE
    if not service_account_path.exists():
        raise FileNotFoundError(f"'{SERVICE_ACCOUNT_FILE}' not found in {BASE_DIR}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull CleverTap daily stats into Google Sheets."
    )
    parser.add_argument(
        "--date",
        help="Date to pull in YYYY-MM-DD or YYYYMMDD format. Defaults to today.",
    )
    parser.add_argument(
        "--tabs",
        help=(
            "Comma-separated tabs to run: Day0, Day5, Day15, Concierge, WhatsApp, SMS. "
            "If omitted, all tabs run."
        ),
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright browser in headed mode to log in manually.",
    )
    parser.add_argument(
        "--skip-logout",
        action="store_true",
        help="Skip Google sign-out and use the active, authenticated session directly.",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Launch headed browser and pause to let user log in manually in the browser window.",
    )
    return parser.parse_args()


def parse_run_dates(date_value: str | None) -> list[tuple[str, str]]:
    """
    Parses a single date or a range of dates.
    Supported range formats: YYYY-MM-DD:YYYY-MM-DD, YYYY-MM-DD to YYYY-MM-DD, YYYYMMDD:YYYYMMDD
    Returns a list of (sheet_date, api_date) tuples.
    """
    from datetime import datetime, timedelta

    if not date_value:
        run_date = datetime.now()
        return [(run_date.strftime("%Y-%m-%d"), run_date.strftime("%Y%m%d"))]

    date_value = date_value.strip()

    # Check for date range separators
    sep_used = None
    for sep in [":", "to", "_", "/"]:
        if sep in date_value:
            sep_used = sep
            break

    if sep_used:
        parts = date_value.split(sep_used)
        if len(parts) != 2:
            raise ValueError(f"Invalid date range format: {date_value}. Expected e.g. YYYY-MM-DD:YYYY-MM-DD")
        
        start_str = parts[0].strip()
        end_str = parts[1].strip()

        start_format = "%Y%m%d" if start_str.isdigit() else "%Y-%m-%d"
        end_format = "%Y%m%d" if end_str.isdigit() else "%Y-%m-%d"

        start_date = datetime.strptime(start_str, start_format)
        end_date = datetime.strptime(end_str, end_format)

        if start_date > end_date:
            raise ValueError(f"Start date ({start_str}) cannot be after end date ({end_str})")

        dates = []
        curr = start_date
        while curr <= end_date:
            dates.append((curr.strftime("%Y-%m-%d"), curr.strftime("%Y%m%d")))
            curr += timedelta(days=1)
        return dates
    else:
        date_format = "%Y%m%d" if date_value.isdigit() else "%Y-%m-%d"
        run_date = datetime.strptime(date_value, date_format)
        return [(run_date.strftime("%Y-%m-%d"), run_date.strftime("%Y%m%d"))]


def retry_delay(attempt: int) -> float:
    return RETRY_BASE_DELAY_SECONDS * (2**attempt)


def append_rows_with_retry(
    worksheet: gspread.Worksheet, rows: list[list[object]], tab_name: str
) -> bool:
    for attempt in range(SHEETS_MAX_RETRIES):
        try:
            worksheet.append_rows(rows, value_input_option="USER_ENTERED")
            return True
        except requests.exceptions.RequestException as exc:
            if attempt == SHEETS_MAX_RETRIES - 1:
                print(
                    f"  Error: Failed writing to '{tab_name}' after {SHEETS_MAX_RETRIES} attempts: {exc}"
                )
                return False

            delay = retry_delay(attempt)
            print(
                f"  Warning: Failed writing to '{tab_name}' (attempt {attempt + 1}/{SHEETS_MAX_RETRIES}): {exc}. "
                f"Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)

    return False


def preflight_session_check(api_date: str) -> None:
    """Validate CleverTap session on the main thread before spawning workers.

    Makes a single lightweight API call. If the session is expired (403),
    refreshes it via Playwright *on the main thread* so that worker threads
    never need to touch Playwright (which is not thread-safe).
    """
    url = f"{CT_BASE_URL}/json/notification/calculateTrend.html"
    # Use the first Day0 campaign as a cheap probe
    probe_id = JOURNEYS.get("Day0", [[("probe", 0)]])[0][1] if JOURNEYS.get("Day0") else 5243
    data = {"id": probe_id, "from": CT_FROM_DATE, "to": api_date}

    current_csrf = session_client.cookies.get("csrf", default=CT_CSRF_TOKEN)
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://in1.dashboard.clevertap.com",
        "referer": CT_REFERER_URL,
        "x-clevertap-csrf-token": current_csrf,
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
    }

    needs_refresh = False
    refresh_reason = ""

    try:
        resp = session_client.post(
            url, headers=headers, data=data, params={"uc": "1"}, timeout=15
        )
        if resp.status_code in [401, 403]:
            needs_refresh = True
            refresh_reason = f"session expired (HTTP {resp.status_code})"
        else:
            try:
                payload = resp.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                needs_refresh = True
                refresh_reason = "response not valid JSON"

            if not needs_refresh and payload.get("success") is False:
                needs_refresh = True
                refresh_reason = f"API returned success=false ({payload.get('error')})"

    except requests.exceptions.RequestException as exc:
        needs_refresh = True
        refresh_reason = f"network error ({exc})"

    if not needs_refresh:
        print("Pre-flight: session is valid.")
        return

    print(
        f"Pre-flight: {refresh_reason}. "
        "Refreshing session on main thread before starting workers..."
    )
    try:
        refresh_clevertap_session(headed=HEADED_MODE)
    except CleverTapAuthError as exc:
        print(
            f"\nFATAL: Pre-flight session refresh failed: {exc}\n"
            "\nThe CleverTap session cookies are expired and automatic login failed.\n"
            "To fix this:\n"
            "  1. Run locally: python clevertap_stats.py --headed\n"
            "  2. Log in manually in the browser window\n"
            "  3. Copy the refreshed CT_COOKIE and CT_CSRF_TOKEN from your .env file\n"
            "  4. Update the GitHub repository secrets with the new values\n"
        )
        sys.exit(1)


def get_todays_stats(campaign_id: int, today_str: str | list[str]) -> dict[str, dict[str, int | str]]:
    global page_instance
    if isinstance(today_str, str):
        api_dates = [today_str]
    else:
        api_dates = today_str

    if HEADED_MODE and page_instance:
        try:
            report_url = f"{CT_BASE_URL}/notification/reports.html?id={campaign_id}"
            page_instance.goto(report_url)
            page_instance.wait_for_timeout(2000)

            # If the page got redirected to login, log back in automatically!
            curr_url = page_instance.url
            if "sso.clevertap.com" in curr_url or "google.com" in curr_url:
                print(
                    "Browser session expired/logged out in headed window. Re-authenticating automatically..."
                )
                refresh_clevertap_session(headed=HEADED_MODE, skip_logout=True)
                page_instance.goto(report_url)
                page_instance.wait_for_timeout(2000)
        except Exception:
            pass

    url = f"{CT_BASE_URL}/json/notification/calculateTrend.html"
    data = {"id": campaign_id, "from": min(api_dates), "to": max(api_dates)}
    session_refreshed = False

    for attempt in range(API_MAX_RETRIES):
        try:
            current_csrf = session_client.cookies.get("csrf", default=CT_CSRF_TOKEN)
            headers = {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://in1.dashboard.clevertap.com",
                "referer": CT_REFERER_URL,
                "x-clevertap-csrf-token": current_csrf,
                "user-agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
            }
            resp = session_client.post(
                url, headers=headers, data=data, params={"uc": "1"}, timeout=30
            )
            if resp.status_code in [401, 403]:
                if not session_refreshed:
                    print(
                        f"    Warning: CleverTap session expired (HTTP {resp.status_code}). Attempting to refresh session..."
                    )
                    safe_refresh_session(current_csrf)
                    session_refreshed = True
                    continue
                else:
                    raise CleverTapAuthError(
                        f"Session expired (HTTP {resp.status_code}) even after session refresh."
                    )
            resp.raise_for_status()

            try:
                payload = resp.json()
            except (ValueError, requests.exceptions.JSONDecodeError) as exc:
                if not session_refreshed:
                    print(
                        f"    Warning: CleverTap response is not valid JSON. Attempting to refresh session... (Error: {exc})"
                    )
                    safe_refresh_session(current_csrf)
                    session_refreshed = True
                    continue
                else:
                    raise CleverTapAuthError(
                        "CleverTap response is not valid JSON even after session refresh. "
                        f"Status: {resp.status_code}, Content: {resp.text[:500]}"
                    )

            if payload.get("success") is False:
                if not session_refreshed:
                    print(
                        f"    Warning: CleverTap API returned success=false ({payload.get('error')}). Attempting to refresh session..."
                    )
                    safe_refresh_session(current_csrf)
                    session_refreshed = True
                    continue
                else:
                    raise CleverTapAuthError(
                        f"CleverTap API returned success=false ({payload.get('error')}) even after session refresh."
                    )

            daily_data = payload.get("All")
            if not isinstance(daily_data, dict):
                raise Exception(
                    "CleverTap response did not include the expected 'All' date data."
                )

            res = {}
            for api_date in api_dates:
                entry = daily_data.get(api_date)
                if not isinstance(entry, dict):
                    res[api_date] = {
                        "sent": 0,
                        "delivered": 0,
                        "viewed": 0,
                        "clicked": 0,
                    }
                else:
                    res[api_date] = {
                        "sent": entry.get("sent", 0),
                        "delivered": entry.get("delivered", 0),
                        "viewed": entry.get("viewed", 0),
                        "clicked": entry.get("clicked", 0),
                    }
            return res
        except CleverTapAuthError:
            # Propagate critical authentication errors to terminate the script
            raise
        except requests.exceptions.RequestException as exc:
            if attempt == API_MAX_RETRIES - 1:
                print(f"    Warning: Error fetching campaign {campaign_id}: {exc}")
                return {
                    api_date: {
                        "sent": "ERROR",
                        "delivered": "ERROR",
                        "viewed": "ERROR",
                        "clicked": "ERROR",
                    }
                    for api_date in api_dates
                }

            delay = retry_delay(attempt)
            print(
                f"    Warning: Network error for campaign {campaign_id} "
                f"(attempt {attempt + 1}/{API_MAX_RETRIES}): {exc}. Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)
        except Exception as exc:
            print(f"    Warning: Error fetching campaign {campaign_id}: {exc}")
            return {
                api_date: {
                    "sent": "ERROR",
                    "delivered": "ERROR",
                    "viewed": "ERROR",
                    "clicked": "ERROR",
                }
                for api_date in api_dates
            }

    return {
        api_date: {
            "sent": "ERROR",
            "delivered": "ERROR",
            "viewed": "ERROR",
            "clicked": "ERROR",
        }
        for api_date in api_dates
    }


def get_or_create_tab(sheet: gspread.Spreadsheet, tab_name: str) -> gspread.Worksheet:
    try:
        ws = sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=tab_name, rows=2000, cols=20)
        ws.append_row(SHEET_HEADER)
        print(f"  Created new tab: '{tab_name}'")
        return ws

    first_row = ws.row_values(1)
    if first_row[: len(SHEET_HEADER)] != SHEET_HEADER:
        ws.update("A1:G1", [SHEET_HEADER])

    return ws


def hex_to_rgb(color: str) -> dict[str, float]:
    color = color.lstrip("#")
    return {
        "red": int(color[0:2], 16) / 255,
        "green": int(color[2:4], 16) / 255,
        "blue": int(color[4:6], 16) / 255,
    }


def format_tab(sheet: gspread.Spreadsheet, worksheet: gspread.Worksheet) -> None:
    sheet_id = worksheet.id
    tab_color = hex_to_rgb(TAB_COLORS.get(worksheet.title, "#334155"))
    requests_body = {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "tabColor": tab_color,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "tabColor,gridProperties.frozenRowCount",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(SHEET_HEADER),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": 0.08,
                                "green": 0.11,
                                "blue": 0.17,
                            },
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
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 2,
                        "endColumnIndex": len(SHEET_HEADER),
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
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": len(SHEET_HEADER),
                    },
                    "properties": {"pixelSize": 120},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 1,
                        "endIndex": 2,
                    },
                    "properties": {"pixelSize": 240},
                    "fields": "pixelSize",
                }
            },
            {
                "setBasicFilter": {
                    "filter": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(SHEET_HEADER),
                        }
                    }
                }
            },
        ]
    }

    try:
        sheet.batch_update(requests_body)
    except Exception as exc:
        print(f"  Warning: Could not format '{worksheet.title}': {exc}")


def open_google_sheet() -> gspread.Spreadsheet:
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        BASE_DIR / SERVICE_ACCOUNT_FILE,
        scopes=GOOGLE_SCOPES,
    )

    for attempt in range(SHEETS_MAX_RETRIES):
        try:
            client = gspread.authorize(creds)
            client.set_timeout(
                (SHEETS_CONNECT_TIMEOUT_SECONDS, SHEETS_READ_TIMEOUT_SECONDS)
            )
            return client.open_by_key(SHEET_ID)
        except (
            requests.exceptions.RequestException,
            gspread.exceptions.GSpreadException,
        ) as exc:
            if attempt == SHEETS_MAX_RETRIES - 1:
                raise RuntimeError(
                    "Failed connecting to Google Sheets after "
                    f"{SHEETS_MAX_RETRIES} attempts: {exc}"
                ) from exc

            delay = retry_delay(attempt)
            print(
                "Warning: Google Sheets connection failed "
                f"(attempt {attempt + 1}/{SHEETS_MAX_RETRIES}): {exc}. "
                f"Retrying in {delay:.0f}s..."
            )
            time.sleep(delay)


def write_daily_tab(
    sheet: gspread.Spreadsheet,
    tab_name: str,
    campaigns: list[tuple[str, int]],
    dates: list[tuple[str, str]],
) -> bool:
    """Fetch stats and write to sheet. Returns True on success, False on failure."""
    print(f"Journey: {tab_name} ({len(campaigns)} nodes)")
    worksheet = get_or_create_tab(sheet, tab_name)
    rows: list[list[object]] = []
    api_dates = [d[1] for d in dates]

    def fetch_one(node_name: str, campaign_id: int):
        print(f"  Fetching {node_name} (Campaign ID: {campaign_id})...")
        stats = get_todays_stats(campaign_id, api_dates)
        return node_name, campaign_id, stats

    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_one, name, cid): (name, cid)
            for name, cid in campaigns
        }
        for future in concurrent.futures.as_completed(futures):
            name, cid = futures[future]
            try:
                name, cid, stats = future.result()
                results_map[(name, cid)] = stats
            except Exception as exc:
                print(f"  Error fetching {name} ({cid}): {exc}")
                results_map[(name, cid)] = {
                    api_date: {
                        "sent": "ERROR",
                        "delivered": "ERROR",
                        "viewed": "ERROR",
                        "clicked": "ERROR",
                    }
                    for api_date in api_dates
                }

    for sheet_date, api_date in dates:
        for node_name, campaign_id in campaigns:
            stats = (results_map.get((node_name, campaign_id)) or {}).get(api_date) or {
                "sent": "ERROR",
                "delivered": "ERROR",
                "viewed": "ERROR",
                "clicked": "ERROR",
            }
            rows.append(
                [
                    sheet_date,
                    node_name,
                    campaign_id,
                    stats["sent"],
                    stats["delivered"],
                    stats["viewed"],
                    stats["clicked"],
                ]
            )

    if any("ERROR" in row[3:] for row in rows):
        print(
            f"  Skipped writing to '{tab_name}' because one or more API calls failed\n"
        )
        return False

    if not append_rows_with_retry(worksheet, rows, tab_name):
        print(
            f"  Skipped writing to '{tab_name}' due to repeated Google Sheets write failures\n"
        )
        return False

    format_tab(sheet, worksheet)
    print(f"  Done: {len(rows)} rows written to '{tab_name}' tab\n")
    return True


def write_prospect_tab(
    sheet: gspread.Spreadsheet,
    tab_name: str,
    campaigns: list[tuple[str, int]],
    dates: list[tuple[str, str]],
) -> bool:
    """Fetch stats and write to sheet. Returns True on success, False on failure."""
    print(f"Tab: {tab_name} ({len(campaigns)} selected campaigns)")
    worksheet = get_or_create_tab(sheet, tab_name)
    rows: list[list[object]] = []
    api_dates = [d[1] for d in dates]

    def fetch_one(campaign_name: str, campaign_id: int):
        print(f"  Fetching {campaign_name} (Campaign ID: {campaign_id})...")
        stats = get_todays_stats(campaign_id, api_dates)
        return campaign_name, campaign_id, stats

    results_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_one, name, cid): (name, cid)
            for name, cid in campaigns
        }
        for future in concurrent.futures.as_completed(futures):
            name, cid = futures[future]
            try:
                name, cid, stats = future.result()
                results_map[(name, cid)] = stats
            except Exception as exc:
                print(f"  Error fetching {name} ({cid}): {exc}")
                results_map[(name, cid)] = {
                    api_date: {
                        "sent": "ERROR",
                        "delivered": "ERROR",
                        "viewed": "ERROR",
                        "clicked": "ERROR",
                    }
                    for api_date in api_dates
                }

    for sheet_date, api_date in dates:
        for campaign_name, campaign_id in campaigns:
            stats = (results_map.get((campaign_name, campaign_id)) or {}).get(api_date) or {
                "sent": "ERROR",
                "delivered": "ERROR",
                "viewed": "ERROR",
                "clicked": "ERROR",
            }
            rows.append(
                [
                    sheet_date,
                    campaign_name,
                    campaign_id,
                    stats["sent"],
                    stats["delivered"],
                    stats["viewed"],
                    stats["clicked"],
                ]
            )

    if any("ERROR" in row[3:] for row in rows):
        print(
            f"  Skipped writing to '{tab_name}' because one or more API calls failed\n"
        )
        return False

    if not append_rows_with_retry(worksheet, rows, tab_name):
        print(
            f"  Skipped writing to '{tab_name}' due to repeated Google Sheets write failures\n"
        )
        return False

    format_tab(sheet, worksheet)
    print(f"  Done: {len(rows)} rows written to '{tab_name}' tab\n")
    return True


def parse_tabs_filter(tabs_value: str | None) -> list[str]:
    if not tabs_value:
        return []

    requested = [tab.strip() for tab in tabs_value.split(",") if tab.strip()]
    valid_tabs = set(DAY_GROUPS) | set(CONCIERGE_GROUPS) | set(PROSPECT_GROUPS)
    unknown = [tab for tab in requested if tab not in valid_tabs]

    if unknown:
        available = ", ".join(sorted(valid_tabs))
        raise ValueError(
            f"Unknown tab(s): {', '.join(unknown)}. Available tabs: {available}"
        )

    return requested


def run(
    date_value: str | None = None,
    tabs_value: str | None = None,
    headed: bool = False,
    skip_logout: bool = False,
    manual: bool = False,
) -> None:
    global HEADED_MODE, CT_COOKIE, CT_CSRF_TOKEN
    HEADED_MODE = headed or manual

    validate_config()

    if not CT_COOKIE or headed or manual:
        # Always refresh session via browser automation if forced by headed/manual flags or if cookies are missing
        refresh_clevertap_session(
            headed=HEADED_MODE, skip_logout=skip_logout, manual=manual
        )
    else:
        init_requests_session()

    dates_to_run = parse_run_dates(date_value)
    requested_tabs = parse_tabs_filter(tabs_value)

    start_sheet, start_api = dates_to_run[0]
    end_sheet, end_api = dates_to_run[-1]
    if start_api == end_api:
        print(f"\nCleverTap Daily Stats Pull - {start_sheet}\n")
    else:
        print(f"\nCleverTap Stats Pull - Range: {start_sheet} to {end_sheet}\n")

    print("Connecting to Google Sheets...")
    try:
        sheet = open_google_sheet()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return

    print("Connected to Google Sheets\n")

    # Validate session on the main thread before spawning any workers.
    # This prevents the Playwright greenlet crash from concurrent refresh attempts.
    print("Running pre-flight session check...")
    preflight_session_check(end_api)

    tabs_to_run = requested_tabs or list(DAY_GROUPS) + list(CONCIERGE_GROUPS) + list(
        PROSPECT_GROUPS
    )

    failed_tabs: list[str] = []

    for tab_name in tabs_to_run:
        success = False
        if tab_name in DAY_GROUPS:
            success = write_daily_tab(sheet, tab_name, JOURNEYS[tab_name], dates_to_run)
        elif tab_name in CONCIERGE_GROUPS:
            success = write_daily_tab(sheet, tab_name, CONCIERGE_GROUPS[tab_name], dates_to_run)
        elif tab_name in PROSPECT_GROUPS:
            success = write_prospect_tab(sheet, tab_name, PROSPECT_GROUPS[tab_name], dates_to_run)

        if not success:
            failed_tabs.append(tab_name)

    if not requested_tabs and not CONCIERGE_GROUPS:
        print(
            "Concierge campaigns are not configured yet. Add their campaign IDs to CONCIERGE_GROUPS.\n"
        )

    if failed_tabs:
        print(
            f"\nFAILED: The following tabs had errors and were NOT written: "
            f"{', '.join(failed_tabs)}\n"
        )
        sys.exit(1)

    print("All done! Check your Google Sheet.")


if __name__ == "__main__":
    args = parse_args()
    run(args.date, args.tabs, args.headed, args.skip_logout, args.manual)
