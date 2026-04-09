"""Upload generated .eml fixtures into a Gmail inbox.

Uses users.messages.insert with internalDateSource=dateHeader so the messages
appear in the target inbox exactly as if they had been delivered, letting the
existing poller pick them up. No SMTP send, no bounces, no external traffic.

Prereq:
  1. `python build_fixtures.py` has been run (or pass --rebuild).
  2. Gmail OAuth credentials are already configured for the backend
     (same ones app/gmail/client.py uses via _build_service()).

Usage:
  python ingest_gmail.py                    # insert all .eml files in out/emails/
  python ingest_gmail.py --only A01,B14     # insert a subset
  python ingest_gmail.py --label acceptance # also apply a Gmail label for easy cleanup
  python ingest_gmail.py --dry-run          # list what would be uploaded
  python ingest_gmail.py --rebuild          # run build_fixtures first

Cleanup: messages tagged with the label can be bulk-trashed from Gmail UI, or
run `ingest_gmail.py --purge-label acceptance` to move them all to Trash.
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
from pathlib import Path

from app.gmail.client import _build_service, _ensure_label  # type: ignore

HERE = Path(__file__).parent
EMAILS_DIR = HERE / "out" / "emails"


def _eml_files(only: set[str] | None) -> list[Path]:
    if not EMAILS_DIR.exists():
        return []
    files = sorted(EMAILS_DIR.glob("*.eml"))
    if only:
        files = [p for p in files if any(p.stem.startswith(prefix) for prefix in only)]
    return files


def _insert(service, eml_bytes: bytes, label_ids: list[str]) -> str:
    raw = base64.urlsafe_b64encode(eml_bytes).decode("ascii")
    body = {"raw": raw, "labelIds": ["INBOX", "UNREAD", *label_ids]}
    resp = (
        service.users()
        .messages()
        .insert(userId="me", internalDateSource="dateHeader", body=body)
        .execute()
    )
    return resp["id"]


def _purge(service, label_id: str) -> int:
    page_token = None
    trashed = 0
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], pageToken=page_token, maxResults=100)
            .execute()
        )
        for msg in resp.get("messages", []):
            service.users().messages().trash(userId="me", id=msg["id"]).execute()
            trashed += 1
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return trashed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated id prefixes (e.g. A01,B14)")
    parser.add_argument("--label", default="acceptance", help="Gmail label to apply (default: acceptance)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true", help="Run build_fixtures.py first")
    parser.add_argument("--purge-label", metavar="LABEL", help="Trash every message carrying LABEL and exit")
    args = parser.parse_args()

    if args.rebuild:
        rc = subprocess.call([sys.executable, str(HERE / "build_fixtures.py")])
        if rc != 0:
            print("build_fixtures.py failed", file=sys.stderr)
            return rc

    service = _build_service()

    if args.purge_label:
        label_id = _ensure_label(service, args.purge_label)
        n = _purge(service, label_id)
        print(f"Trashed {n} message(s) with label '{args.purge_label}'.")
        return 0

    only = set(args.only.split(",")) if args.only else None
    files = _eml_files(only)
    if not files:
        print(f"No .eml files found under {EMAILS_DIR}. Run build_fixtures.py first.", file=sys.stderr)
        return 1

    label_ids: list[str] = []
    if args.label:
        label_ids.append(_ensure_label(service, args.label))

    for path in files:
        if args.dry_run:
            print(f"  DRY  {path.name}")
            continue
        mid = _insert(service, path.read_bytes(), label_ids)
        print(f"  inserted {path.name}  ->  {mid}")

    print(f"\n{'Would upload' if args.dry_run else 'Uploaded'} {len(files)} message(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
