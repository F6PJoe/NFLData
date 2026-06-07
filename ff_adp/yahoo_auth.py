#!/usr/bin/env python3
"""
One-time Yahoo OAuth2 authorization flow.

Run this once to get a refresh token, which gets saved to .env.
After that, fetch_yahoo_adp.py uses the refresh token automatically.

Usage:
    python yahoo_auth.py

Requires: requests, python-dotenv
"""

import os
import re
import sys
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv, set_key

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_FILE)

CLIENT_ID     = os.environ.get("YAHOO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET", "")
REDIRECT_URI  = "https://localhost:8080"

AUTH_URL    = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL   = "https://api.login.yahoo.com/oauth2/get_token"


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET not found in .env")

    # Step 1: build the authorization URL and open it in the browser
    params = {
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "language":      "en-us",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("\nOpening Yahoo authorization page in your browser...")
    print("If it doesn't open automatically, paste this URL:\n")
    print(auth_url)
    webbrowser.open(auth_url)

    # Step 2: user authorizes, Yahoo redirects to https://localhost:8080?code=...
    # (the redirect will fail in the browser — that's fine, we just need the URL)
    print("\n" + "="*60)
    print("After you click Agree on Yahoo's page, your browser will")
    print("show an error page (can't connect to localhost) — that's OK.")
    print("Copy the FULL URL from your browser's address bar and")
    print("paste it here, then press Enter.")
    print("="*60 + "\n")

    redirect_response = input("Paste the full redirect URL: ").strip()

    # Extract the authorization code from the URL
    parsed = urllib.parse.urlparse(redirect_response)
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        sys.exit("Could not find 'code' in the URL. Make sure you copied the full address bar URL.")

    # Step 3: exchange the code for tokens
    print("\nExchanging authorization code for tokens...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(f"No refresh_token in response: {tokens}")

    # Step 4: save the refresh token to .env
    set_key(ENV_FILE, "YAHOO_REFRESH_TOKEN", refresh_token)
    print("\n✓ Refresh token saved to .env")
    print("You can now run fetch_yahoo_adp.py at any time — no re-auth needed.")


if __name__ == "__main__":
    main()
