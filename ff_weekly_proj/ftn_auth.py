"""
Login helper for ftnfantasy.com.

FTN's tools (tools.ftnfantasy.com) call api.ftnfantasy.com for auth and
ls.ftnfantasy.com for data, using a short-lived JWT access token obtained via:

    POST https://api.ftnfantasy.com/users/login
    {"email": ..., "password": ...}
    -> {"status": "success", "access_token": ..., "refresh_token": ..., "user_id": ...}

Credentials are read from environment variables FTN_EMAIL / FTN_PASSWORD,
loaded from a local .env file (never committed).
"""

import os

LOGIN_URL = "https://api.ftnfantasy.com/users/login"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (personal projections tool)"}


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def get_access_token():
    """Log in with FTN_EMAIL / FTN_PASSWORD and return an access token."""
    import requests

    _load_dotenv()
    email = os.environ.get("FTN_EMAIL")
    password = os.environ.get("FTN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set FTN_EMAIL and FTN_PASSWORD (e.g. in a local .env file) to log in to FTN."
        )

    resp = requests.post(LOGIN_URL, json={"email": email, "password": password},
                          headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success" or not data.get("access_token"):
        raise RuntimeError(f"FTN login failed: {data}")
    return data["access_token"]
