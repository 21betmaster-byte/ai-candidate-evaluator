"""Mint a Gmail refresh token using the client_id/client_secret already in .env.

This eliminates the OAuth Playground "did I paste matching creds in two places"
class of bugs by using the SAME credentials your runtime will use.

Prereq (one-time): in Google Cloud Console, add `http://localhost:8765/` as an
Authorized redirect URI on your OAuth client.

Usage (from backend/):
    python scripts/get_gmail_refresh_token.py

It opens a browser, you sign in as the inbox user, and the new refresh token is
written back into backend/.env (replacing GMAIL_REFRESH_TOKEN=).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
REDIRECT_PORT = 8765
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def update_env_file(refresh_token: str) -> None:
    lines = ENV_PATH.read_text().splitlines()
    out, replaced = [], False
    for ln in lines:
        if ln.startswith("GMAIL_REFRESH_TOKEN="):
            out.append(f"GMAIL_REFRESH_TOKEN={refresh_token}")
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def main() -> int:
    s = get_settings()
    if not s.gmail_client_id or not s.gmail_client_secret:
        print("❌ GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in backend/.env first.")
        return 1

    client_config = {
        "web": {
            "client_id": s.gmail_client_id,
            "client_secret": s.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{REDIRECT_PORT}/"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print(f"→ Opening browser. Sign in as {s.gmail_address or 'the inbox account'}.")
    print("  (If you see 'Google hasn't verified this app', click Advanced → Go to ... unsafe.)")
    creds = flow.run_local_server(
        port=REDIRECT_PORT,
        prompt="consent",   # forces a refresh_token to be returned
        access_type="offline",
        open_browser=True,
    )

    if not creds.refresh_token:
        print("❌ No refresh_token returned. Try again — sometimes Google withholds it on re-consent.")
        return 1

    update_env_file(creds.refresh_token)
    print(f"\n✓ Wrote new GMAIL_REFRESH_TOKEN to {ENV_PATH}")
    print("Now run:  python scripts/test_gmail.py plumbuildersresidency@gmail.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
