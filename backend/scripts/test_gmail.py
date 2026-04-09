"""End-to-end Gmail smoke test.

Usage (from backend/):
    python scripts/test_gmail.py you@example.com

Reads GMAIL_* values from backend/.env, lists the 5 most recent inbox messages
to prove READ works, then sends a hello-world email to the address you pass on
the command line to prove SEND works.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.gmail import client as gmail


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_gmail.py recipient@example.com")
        return 1
    recipient = sys.argv[1]

    s = get_settings()
    missing = [
        k for k, v in {
            "GMAIL_CLIENT_ID": s.gmail_client_id,
            "GMAIL_CLIENT_SECRET": s.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": s.gmail_refresh_token,
            "GMAIL_ADDRESS": s.gmail_address,
        }.items()
        if not v
    ]
    if missing:
        print(f"❌ Missing env vars: {', '.join(missing)}")
        print("   Edit backend/.env and try again.")
        return 1

    print(f"✓ Using inbox: {s.gmail_address}")

    # 1. READ test
    print("\n→ Listing up to 5 unprocessed inbox messages...")
    try:
        ids = gmail.list_unprocessed_messages()[:5]
    except Exception as e:
        print(f"❌ READ failed: {e}")
        return 1
    print(f"✓ Found {len(ids)} unprocessed message(s).")
    for mid in ids:
        try:
            email = gmail.fetch_email(mid)
            subj = (email.subject or "(no subject)")[:60]
            print(f"   • {email.sender_email}  —  {subj}")
        except Exception as e:
            print(f"   • {mid}  (fetch failed: {e})")

    # 2. SEND test
    print(f"\n→ Sending hello-world email to {recipient}...")
    try:
        msg_id = gmail.send_email(
            to=recipient,
            subject="Hello from the AI Candidate Evaluator 👋",
            body_text=(
                "If you're reading this, the Gmail integration is wired up correctly.\n\n"
                "— The Hiring Bot 🤖"
            ),
        )
    except Exception as e:
        print(f"❌ SEND failed: {e}")
        return 1
    print(f"✓ Sent. Gmail message id: {msg_id}")
    print("\nAll good. Gmail end-to-end is working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
