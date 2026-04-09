"""Gmail API client.

Authentication uses an OAuth refresh token (one-time setup): the operator generates
client_id, client_secret, and a refresh_token via Google's OAuth playground (or a
local helper script) and supplies them as env vars. The client then mints
short-lived access tokens on demand and never needs an interactive consent flow.
"""
from __future__ import annotations

import base64
import email
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Iterable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings

log = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass
class InboundEmail:
    message_id: str
    thread_id: str
    sender: str  # raw From header
    sender_email: str  # parsed
    sender_name: str | None
    subject: str
    body_text: str
    attachments: list["Attachment"] = field(default_factory=list)
    label_ids: list[str] = field(default_factory=list)


@dataclass
class Attachment:
    filename: str
    mime_type: str
    data: bytes  # raw bytes


def _build_service():
    s = get_settings()
    creds = Credentials(
        token=None,
        refresh_token=s.gmail_refresh_token,
        client_id=s.gmail_client_id,
        client_secret=s.gmail_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _parse_address(raw: str) -> tuple[str, str | None]:
    name, addr = email.utils.parseaddr(raw or "")
    return (addr or "").lower(), (name or None)


def _walk_parts(parts: list[dict]) -> Iterable[dict]:
    for p in parts or []:
        yield p
        if p.get("parts"):
            yield from _walk_parts(p["parts"])


def _decode_b64url(data: str | None) -> bytes:
    if not data:
        return b""
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def _extract_email(service, message_id: str) -> InboundEmail:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    sender_raw = headers.get("from", "")
    sender_email, sender_name = _parse_address(sender_raw)
    subject = headers.get("subject", "")

    # Walk MIME tree to extract text body and attachments.
    body_parts: list[str] = []
    attachments: list[Attachment] = []
    parts: list[dict] = []
    if payload.get("parts"):
        parts = list(_walk_parts(payload["parts"]))
    else:
        parts = [payload]

    for p in parts:
        mime = p.get("mimeType", "")
        filename = p.get("filename") or ""
        body = p.get("body", {})
        if filename:
            # Attachment
            att_id = body.get("attachmentId")
            if att_id:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=att_id
                ).execute()
                data = _decode_b64url(att.get("data"))
            else:
                data = _decode_b64url(body.get("data"))
            attachments.append(Attachment(filename=filename, mime_type=mime, data=data))
        elif mime == "text/plain" and body.get("data"):
            body_parts.append(_decode_b64url(body["data"]).decode("utf-8", errors="replace"))
        elif mime == "text/html" and body.get("data") and not body_parts:
            # Fallback to HTML stripped of tags only if no plaintext part exists.
            html = _decode_b64url(body["data"]).decode("utf-8", errors="replace")
            from bs4 import BeautifulSoup
            body_parts.append(BeautifulSoup(html, "html.parser").get_text("\n"))

    return InboundEmail(
        message_id=message_id,
        thread_id=msg.get("threadId", ""),
        sender=sender_raw,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body_text="\n".join(body_parts).strip(),
        attachments=attachments,
        label_ids=msg.get("labelIds", []),
    )


def list_unprocessed_messages(processed_label: str | None = None) -> list[str]:
    """Return Gmail message IDs that haven't been processed yet.

    Strategy: query for INBOX messages NOT carrying the processed label.
    """
    s = get_settings()
    label = processed_label or s.gmail_label_processed
    service = _build_service()
    label_id = _ensure_label(service, label)
    q = f"in:inbox -label:{label}"
    ids: list[str] = []
    page_token = None
    while True:
        resp = service.users().messages().list(userId="me", q=q, pageToken=page_token, maxResults=50).execute()
        for m in resp.get("messages", []):
            ids.append(m["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def fetch_email(message_id: str) -> InboundEmail:
    return _extract_email(_build_service(), message_id)


def mark_processed(message_id: str, processed_label: str | None = None) -> None:
    s = get_settings()
    label = processed_label or s.gmail_label_processed
    service = _build_service()
    label_id = _ensure_label(service, label)
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": []},
    ).execute()


def _ensure_label(service, name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"] == name:
            return l["id"]
    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return created["id"]


def send_email(to: str, body_text: str, in_reply_to: str | None = None, thread_id: str | None = None) -> str:
    """Send a reply email and return the Gmail message ID.

    All outbound emails are replies to an existing thread so that they
    land in the same conversation and avoid spam filters.  The subject
    is omitted — Gmail auto-derives ``Re: <original>`` from the thread.
    """
    s = get_settings()
    service = _build_service()
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = s.gmail_address
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    sent = service.users().messages().send(userId="me", body=body).execute()
    return sent.get("id", "")
