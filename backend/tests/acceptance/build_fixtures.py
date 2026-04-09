"""Generate .eml fixtures from scenarios.json.

Reads scenarios.json, renders each scenario's attachment(s) into real PDF /
DOCX / raw bytes, wraps everything in an RFC 5322 message, and writes one
.eml file per scenario under ./out/emails/. ingest_gmail.py consumes these
and pushes them via users.messages.insert.

Usage:
    python build_fixtures.py                 # generate all
    python build_fixtures.py --only A01,B14  # generate a subset

Dependencies already in backend/pyproject.toml: pymupdf. DOCX is hand-rolled
(zip + hardcoded XML) so no extra deps.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import zipfile
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from io import BytesIO
from pathlib import Path

import fitz  # pymupdf

HERE = Path(__file__).parent
SCENARIOS_PATH = HERE / "scenarios.json"
OUT_DIR = HERE / "out" / "emails"
FIXTURES_DIR = HERE / "fixtures"


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def _new_pdf() -> fitz.Document:
    return fitz.open()


def _layout_text(page: fitz.Page, text: str, rect: fitz.Rect, fontsize: int = 10, color=(0, 0, 0)) -> None:
    page.insert_textbox(rect, text, fontsize=fontsize, fontname="helv", color=color, align=0)


def render_pdf_single(text: str) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 800))
    return doc.tobytes()


def render_pdf_two_column(text: str) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    mid = "\n--- COLUMN BREAK ---\n"
    if mid in text:
        left, right = text.split(mid, 1)
    else:
        half = len(text) // 2
        left, right = text[:half], text[half:]
    _layout_text(page, left, fitz.Rect(40, 50, 290, 800))
    _layout_text(page, right, fitz.Rect(310, 50, 560, 800))
    return doc.tobytes()


def render_pdf_long(text: str, pages: int) -> bytes:
    doc = _new_pdf()
    for i in range(pages):
        page = doc.new_page()
        _layout_text(page, f"(page {i + 1}/{pages})\n\n{text}", fitz.Rect(50, 50, 550, 800))
    return doc.tobytes()


def render_pdf_tables(text: str) -> bytes:
    return render_pdf_single(text)  # text already contains table characters


def render_pdf_hidden_text(text: str, hidden: str) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 500))
    _layout_text(page, hidden, fitz.Rect(50, 520, 550, 780), fontsize=8, color=(1, 1, 1))
    return doc.tobytes()


def render_pdf_annot_links(text: str, links: list[dict]) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 500))
    y = 560
    for entry in links:
        anchor_text = entry["text"]
        uri = entry["uri"]
        rect = fitz.Rect(50, y, 550, y + 20)
        _layout_text(page, anchor_text, rect, fontsize=11, color=(0, 0, 0.8))
        page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": uri})
        y += 40
    return doc.tobytes()


def render_pdf_injection_metadata(text: str, author_injection: str) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 800))
    doc.set_metadata({
        "author": author_injection,
        "title": "Resume",
        "subject": "Application",
        "keywords": "",
        "creator": "build_fixtures.py",
        "producer": "build_fixtures.py",
    })
    return doc.tobytes()


def render_pdf_encrypted(text: str, password: str) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 800))
    buf = BytesIO()
    doc.save(
        buf,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password,
        permissions=fitz.PDF_PERM_ACCESSIBILITY,
    )
    return buf.getvalue()


def render_pdf_corrupted() -> bytes:
    good = render_pdf_single("Cory Corrupt\nThis will be mangled.")
    # Zero out a chunk in the middle of the xref region.
    mid = len(good) // 2
    return good[:mid] + b"\x00" * 128 + good[mid + 200 :]


def render_pdf_huge(text: str, target_bytes: int) -> bytes:
    doc = _new_pdf()
    page = doc.new_page()
    _layout_text(page, text, fitz.Rect(50, 50, 550, 800))
    # Embed a large random blob as an attached file — valid PDF, inflates size.
    rng = random.Random(0xC0FFEE)
    blob = bytes(rng.getrandbits(8) for _ in range(target_bytes))
    doc.embfile_add("padding.bin", blob, desc="padding to reach target size")
    return doc.tobytes()


# ---------------------------------------------------------------------------
# DOCX rendering (hand-rolled minimal Office Open XML)
# ---------------------------------------------------------------------------

_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)

_DOCX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def _docx_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_docx(text: str) -> bytes:
    paragraphs = text.split("\n")
    body_xml = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{_docx_escape(p)}</w:t></w:r></w:p>'
        for p in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body_xml}</w:body>"
        "</w:document>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Other attachment kinds
# ---------------------------------------------------------------------------

def build_zip_with_pdf(pdf_bytes: bytes, inner_name: str = "resume.pdf") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner_name, pdf_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Attachment dispatcher
# ---------------------------------------------------------------------------

def _resume_text(manifest: dict, key: str) -> str:
    content = manifest["resume_content"]
    if key not in content:
        raise KeyError(f"Unknown resume_key: {key}")
    return content[key]


def build_attachment(att: dict, manifest: dict) -> tuple[str, str, bytes] | None:
    """Return (filename, mime_type, bytes) for an attachment spec, or None
    for attachments handled via fixture files the user must supply."""
    kind = att["kind"]
    filename = att["filename"]

    if kind == "pdf":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_single(text)

    if kind == "pdf_two_column":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_two_column(text)

    if kind == "pdf_long":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_long(text, att.get("pages", 24))

    if kind == "pdf_tables":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_tables(text)

    if kind == "pdf_hidden_text":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_hidden_text(text, att["hidden_text"])

    if kind == "pdf_annot_links":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_annot_links(text, att["annot_links"])

    if kind == "pdf_injection_metadata":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_injection_metadata(text, att["metadata_author"])

    if kind == "pdf_encrypted":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_encrypted(text, att["password"])

    if kind == "pdf_corrupted":
        return filename, "application/pdf", render_pdf_corrupted()

    if kind == "pdf_huge":
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_pdf_huge(text, att["target_bytes"])

    if kind == "pdf_raw_bytes":
        return filename, "application/pdf", bytes.fromhex(att.get("bytes_hex", ""))

    if kind == "pdf_wrong_ext":
        # File named .pdf but content is actually DOCX bytes.
        text = _resume_text(manifest, att["resume_key"])
        return filename, "application/pdf", render_docx(text)

    if kind == "docx":
        text = _resume_text(manifest, att["resume_key"])
        return (
            filename,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            render_docx(text),
        )

    if kind == "file_raw":
        return filename, att["mime_type"], bytes.fromhex(att.get("bytes_hex", ""))

    if kind == "zip_with_pdf":
        inner_text = _resume_text(manifest, att["inner_pdf_resume_key"])
        pdf_bytes = render_pdf_single(inner_text)
        return filename, "application/zip", build_zip_with_pdf(pdf_bytes)

    if kind == "fixture":
        path = HERE / att["fixture_path"]
        if not path.exists():
            if att.get("needs_user_fixture"):
                print(f"  SKIP: missing user-supplied fixture: {path}", file=sys.stderr)
                return None
            raise FileNotFoundError(f"Missing fixture: {path}")
        return filename, "application/pdf", path.read_bytes()

    raise ValueError(f"Unknown attachment kind: {kind}")


# ---------------------------------------------------------------------------
# EML assembly
# ---------------------------------------------------------------------------

MIME_MAIN = {
    "application/pdf": ("application", "pdf"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "application",
        "vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "application/zip": ("application", "zip"),
    "application/vnd.apple.pages": ("application", "vnd.apple.pages"),
    "application/rtf": ("application", "rtf"),
    "text/plain": ("text", "plain"),
    "application/vnd.oasis.opendocument.text": (
        "application",
        "vnd.oasis.opendocument.text",
    ),
}


def build_eml(scenario: dict, manifest: dict) -> bytes:
    msg = EmailMessage()
    defaults = manifest["defaults"]
    sender = formataddr((scenario["from"]["name"], scenario["from"]["email"]))
    recipient = formataddr((defaults["to_name"], defaults["to_email"]))
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = scenario["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="plumbuilders.example")
    msg["X-Scenario-Id"] = scenario["id"]
    msg["X-Scenario-Group"] = scenario["group"]
    msg.set_content(scenario["body"])

    for att in scenario.get("attachments", []):
        built = build_attachment(att, manifest)
        if built is None:
            continue
        filename, mime_type, data = built
        maintype, subtype = MIME_MAIN.get(mime_type, ("application", "octet-stream"))
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    return bytes(msg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated scenario id prefixes to generate (e.g. A01,B14)")
    args = parser.parse_args()

    manifest = json.loads(SCENARIOS_PATH.read_text())
    only = set(args.only.split(",")) if args.only else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    for scenario in manifest["scenarios"]:
        sid = scenario["id"]
        if only and not any(sid.startswith(p) for p in only):
            continue
        try:
            eml_bytes = build_eml(scenario, manifest)
        except Exception as e:
            print(f"  ERROR {sid}: {e}", file=sys.stderr)
            skipped += 1
            continue
        out_path = OUT_DIR / f"{sid}.eml"
        out_path.write_bytes(eml_bytes)
        print(f"  wrote {out_path.relative_to(HERE)}  ({len(eml_bytes):>8} bytes)")
        generated += 1

    print(f"\nGenerated {generated} .eml file(s); {skipped} skipped.")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
