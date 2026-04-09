from __future__ import annotations

import pytest
from fastapi import HTTPException
from jose import jwt

from app import auth as auth_mod


class _S:
    def __init__(self, allowed: list[str], secret: str = "testsecret"):
        self._allowed = allowed
        self.nextauth_jwt_secret = secret

    @property
    def allowed_emails_list(self) -> list[str]:
        return self._allowed


def _patch(monkeypatch, allowed, secret="testsecret"):
    monkeypatch.setattr(auth_mod, "get_settings", lambda: _S(allowed, secret))


def _tok(email: str, secret: str = "testsecret") -> str:
    return jwt.encode({"email": email}, secret, algorithm="HS256")


def test_dev_mode_empty_allowlist_returns_header(monkeypatch):
    _patch(monkeypatch, [])
    assert auth_mod.require_user(authorization=None, x_user_email="a@b.com") == "a@b.com"


def test_dev_mode_empty_allowlist_default(monkeypatch):
    _patch(monkeypatch, [])
    assert auth_mod.require_user(authorization=None, x_user_email=None) == "dev@local"


def test_prod_missing_authorization_header(monkeypatch):
    _patch(monkeypatch, ["you@x.com"])
    with pytest.raises(HTTPException) as e:
        auth_mod.require_user(authorization=None, x_user_email="you@x.com")
    assert e.value.status_code == 401


def test_prod_malformed_bearer(monkeypatch):
    _patch(monkeypatch, ["you@x.com"])
    with pytest.raises(HTTPException):
        auth_mod.require_user(authorization="Token abc", x_user_email=None)


def test_prod_wrong_secret(monkeypatch):
    _patch(monkeypatch, ["you@x.com"], secret="right")
    bad = _tok("you@x.com", secret="wrong")
    with pytest.raises(HTTPException):
        auth_mod.require_user(authorization=f"Bearer {bad}", x_user_email=None)


def test_prod_email_not_in_allowlist(monkeypatch):
    _patch(monkeypatch, ["you@x.com"])
    t = _tok("someone@else.com")
    with pytest.raises(HTTPException):
        auth_mod.require_user(authorization=f"Bearer {t}", x_user_email=None)


def test_prod_missing_email_claim(monkeypatch):
    _patch(monkeypatch, ["you@x.com"])
    t = jwt.encode({"sub": "123"}, "testsecret", algorithm="HS256")
    with pytest.raises(HTTPException):
        auth_mod.require_user(authorization=f"Bearer {t}", x_user_email=None)


def test_prod_happy_path_returns_lowercased_email(monkeypatch):
    _patch(monkeypatch, ["you@x.com"])
    t = _tok("YOU@X.com")
    assert auth_mod.require_user(authorization=f"Bearer {t}", x_user_email=None) == "you@x.com"


def test_prod_empty_secret_rejects(monkeypatch):
    _patch(monkeypatch, ["you@x.com"], secret="")
    t = _tok("you@x.com", secret="anything")
    with pytest.raises(HTTPException):
        auth_mod.require_user(authorization=f"Bearer {t}", x_user_email=None)
