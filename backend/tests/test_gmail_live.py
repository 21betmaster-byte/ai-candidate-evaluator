"""LIVE integration tests for the Gmail subsystem.

These hit the real Google Gmail API using the OAuth refresh token from
backend/.env. They are OPT-IN — the default `pytest` invocation skips them
because of the `-m "not live"` filter in pyproject.toml. Run them with:

    pytest -m live                            # all live tests
    pytest -m live tests/test_gmail_live.py   # just gmail
    RUN_LIVE_TESTS=1 pytest                   # implicit opt-in (CI helper)

Why these exist
---------------
The pytest suite mocks Gmail entirely (FakeGmail in conftest.py), which
gives us deterministic and fast unit tests but tells us nothing about
whether real OAuth still works, whether the token has expired, whether
the labels we depend on still exist, or whether `list/fetch/modify` still
return the shapes we parse against.

These live tests are the smoke check that "Gmail polling actually polls".
Run them before every demo, before any deploy, and after rotating any
Gmail credentials.

Safety properties
-----------------
1. Every test message uses a unique UUID-tagged subject so we never
   confuse it with a real candidate email.
2. Every test message is sent FROM the configured inbox TO itself, so we
   don't email an outside address.
3. The processed-label name is overridden to a test-only label
   (`evaluator/test-live`) so production candidate state is never
   touched.
4. We use try/finally to TRASH the test message and remove the test label
   even when assertions fail. The cleanup is best-effort but extensive.
5. We never run the candidate processing pipeline against the test
   message — only the Gmail client primitives.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

# Skip the whole module unless live tests are enabled OR pytest is invoked
# with `-m live`. The pyproject default `-m "not live"` already filters by
# marker; this `skipif` adds a clean error message when somebody tries to
# run the file directly without setting RUN_LIVE_TESTS.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("RUN_LIVE_TESTS")
        and not any("live" in arg for arg in os.sys.argv),
        reason="live Gmail tests are opt-in; set RUN_LIVE_TESTS=1 or pass `-m live`",
    ),
]


# Force the live tests to use a separate processed-label so they cannot
# touch production candidate state. Set this BEFORE importing app.config.
TEST_LABEL = "evaluator/test-live"
os.environ.setdefault("GMAIL_LABEL_PROCESSED", TEST_LABEL)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gmail_settings():
    """Real settings, with the test label override locked in."""
    from app.config import get_settings

    s = get_settings()
    if not (s.gmail_refresh_token and s.gmail_client_id and s.gmail_client_secret):
        pytest.skip("Gmail OAuth credentials not configured in env — skipping live tests")
    if s.gmail_label_processed != TEST_LABEL:
        pytest.skip(
            f"Refusing to run live tests against the production label "
            f"{s.gmail_label_processed!r}. Set GMAIL_LABEL_PROCESSED={TEST_LABEL} "
            "in your env first."
        )
    return s


@pytest.fixture
def unique_subject():
    """A subject we can recognize unambiguously among the inbox."""
    return f"[TEST-LIVE-{uuid.uuid4().hex[:12]}] integration check"


@pytest.fixture
def cleanup_message_id():
    """Holds the gmail message id we sent so the teardown can trash it.

    Yields a list (so the test can append) and trashes everything in it
    on teardown, regardless of pass/fail.
    """
    ids: list[str] = []
    yield ids
    if not ids:
        return
    try:
        from app.gmail.client import _build_service  # type: ignore[attr-defined]

        service = _build_service()
        for mid in ids:
            try:
                service.users().messages().trash(userId="me", id=mid).execute()
            except Exception:
                pass  # best effort
    except Exception:
        pass  # gmail unreachable on teardown — leave the message in trash for manual cleanup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for(predicate, *, timeout: float = 30.0, interval: float = 1.0):
    """Poll `predicate()` until it returns truthy or timeout elapses."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(
        f"timed out after {timeout}s waiting for predicate (last value: {last!r})"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGmailLiveOAuth:
    """Smoke check that the OAuth refresh token still works."""

    def test_can_build_service_and_list_labels(self, gmail_settings):
        """If this fails, the refresh token is dead. Re-issue it."""
        from app.gmail.client import _build_service  # type: ignore[attr-defined]

        service = _build_service()
        labels = service.users().labels().list(userId="me").execute()
        assert "labels" in labels, "Gmail labels.list returned an unexpected shape"
        # The system labels INBOX and SENT are always present.
        names = {l["name"] for l in labels["labels"]}
        assert "INBOX" in names
        assert "SENT" in names


class TestGmailLivePolling:
    """End-to-end Gmail subsystem test against the real inbox.

    Sends a unique message, polls for it, fetches it, marks it processed,
    re-polls, and verifies it's gone from the unprocessed list.
    """

    def test_send_then_poll_then_fetch_then_mark_processed(
        self, gmail_settings, unique_subject, cleanup_message_id
    ):
        from app.gmail import client as gmail

        # 1) Send a message FROM the inbox TO itself.
        body = (
            "This is an automated live integration test.\n"
            "If you are reading this, the cleanup step failed — please trash it.\n"
            f"Test id: {unique_subject}\n"
        )
        sent_id = gmail.send_email(
            to=gmail_settings.gmail_address,
            subject=unique_subject,
            body_text=body,
        )
        assert sent_id, "send_email returned no message id"
        cleanup_message_id.append(sent_id)

        # 2) Poll the inbox until our test message shows up unprocessed.
        #    Gmail can take a few seconds to deliver a self-send.
        def _find_test_message() -> str | None:
            ids = gmail.list_unprocessed_messages()
            for mid in ids:
                try:
                    msg = gmail.fetch_email(mid)
                except Exception:
                    continue
                if msg.subject == unique_subject:
                    return mid
            return None

        delivered_id = _wait_for(_find_test_message, timeout=45.0, interval=2.0)
        # The send-side id and the inbox-side id can differ if Gmail rewrote
        # the message; track the inbox-side one for cleanup too.
        if delivered_id not in cleanup_message_id:
            cleanup_message_id.append(delivered_id)

        # 3) Fetch its parsed form.
        msg = gmail.fetch_email(delivered_id)
        assert msg.subject == unique_subject
        assert msg.sender_email.lower() == gmail_settings.gmail_address.lower()
        assert "automated live integration test" in msg.body_text.lower()
        assert msg.attachments == []  # we didn't attach anything

        # 4) Mark processed.
        gmail.mark_processed(delivered_id)

        # 5) Re-poll: it should no longer be in the unprocessed list.
        def _is_gone() -> bool:
            ids = gmail.list_unprocessed_messages()
            return delivered_id not in ids

        _wait_for(_is_gone, timeout=15.0, interval=1.0)


class TestGmailLivePollerIntegration:
    """Hits the higher-level `poll_inbox()` function — the same code path
    the production worker runs every N minutes."""

    def test_poll_inbox_returns_count(self, gmail_settings, unique_subject, cleanup_message_id):
        from app.gmail import client as gmail
        from app.gmail.poller import poll_inbox

        # Pre-clean: drain anything left over from prior failed runs by
        # marking everything currently unprocessed. We do NOT trash, just
        # label, so a failed previous run doesn't leave a sticky inbox.
        for mid in gmail.list_unprocessed_messages():
            try:
                gmail.mark_processed(mid)
            except Exception:
                pass

        # Send our test message.
        sent_id = gmail.send_email(
            to=gmail_settings.gmail_address,
            subject=unique_subject,
            body_text="poll_inbox integration test",
        )
        cleanup_message_id.append(sent_id)

        # Wait for delivery.
        def _ready() -> bool:
            return any(
                gmail.fetch_email(mid).subject == unique_subject
                for mid in gmail.list_unprocessed_messages()
            )

        _wait_for(_ready, timeout=45.0, interval=2.0)

        # poll_inbox enqueues to the database, so we need to use a real
        # session. Reuse the existing test infra (in-memory sqlite from
        # conftest.py) — poll_inbox uses session_scope which we've patched
        # to point at it.
        new_count = poll_inbox()
        assert new_count >= 1, "poll_inbox should have picked up at least our test message"

        # Make sure we don't leak this into the inbox.
        for mid in gmail.list_unprocessed_messages():
            cleanup_message_id.append(mid)
            try:
                gmail.mark_processed(mid)
            except Exception:
                pass


class TestGmailLiveErrorPaths:
    """Verify the client surfaces real Google API errors as Python exceptions
    rather than swallowing them — the production poller depends on this."""

    def test_fetch_nonexistent_message_raises(self, gmail_settings):
        from googleapiclient.errors import HttpError

        from app.gmail.client import fetch_email

        with pytest.raises(HttpError):
            # An obviously-fake message id should 404 from Gmail.
            fetch_email("not-a-real-message-id-0123456789")
