#!/usr/bin/env python3
"""Quick test to see if CleverTap's public API returns campaign stats.

Usage:
    python test_public_api.py <PASSCODE>

The Account ID is extracted from .env (CT_BASE_URL).
"""
import json
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

ACCOUNT_ID = "W8W-6R9-885Z"
PASSCODE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CT_PASSCODE", "")

if not PASSCODE:
    print("Usage: python test_public_api.py <PASSCODE>")
    print("\nFind your Passcode in CleverTap Dashboard → Settings → Project")
    sys.exit(1)

API_URL = "https://in1.api.clevertap.com/1/targets/result.json"

# Test with campaign ID 5243 (WA_Varca_Day0)
TEST_CAMPAIGN_ID = 5243

headers = {
    "X-CleverTap-Account-Id": ACCOUNT_ID,
    "X-CleverTap-Passcode": PASSCODE,
    "Content-Type": "application/json",
}

payload = {"id": TEST_CAMPAIGN_ID}

print(f"Testing CleverTap public API...")
print(f"Account ID: {ACCOUNT_ID}")
print(f"Campaign ID: {TEST_CAMPAIGN_ID}")
print(f"URL: {API_URL}")
print()

resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
print(f"HTTP Status: {resp.status_code}")
print(f"Response:\n{json.dumps(resp.json(), indent=2)}")
