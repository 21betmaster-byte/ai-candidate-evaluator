"""Dashboard auth dependency.

Production contract
-------------------
The Next.js dashboard (Auth.js v5, Google provider) forwards the user's
session as a plain HS256-signed JWT in the `Authorization: Bearer <jwt>`
header. The backend verifies the signature with `NEXTAUTH_JWT_SECRET` and
checks the `email` claim against `ALLOWED_EMAILS`.

Auth.js v5 emits a JWE by default, so the dashboard must override
`jwt.encode`/`jwt.decode` to sign with HS256 using the same shared secret
(`AUTH_SECRET` on the dashboard == `NEXTAUTH_JWT_SECRET` here). Example::

    // web/auth.ts
    import { SignJWT, jwtVerify } from "jose"
    const secret = new TextEncoder().encode(process.env.AUTH_SECRET!)
    export const { auth, handlers } = NextAuth({
      providers: [Google],
      session: { strategy: "jwt" },
      jwt: {
        encode: async ({ token }) =>
          new SignJWT(token as any)
            .setProtectedHeader({ alg: "HS256" })
            .setIssuedAt()
            .setExpirationTime("30d")
            .sign(secret),
        decode: async ({ token }) =>
          (await jwtVerify(token!, secret)).payload as any,
      },
    })

Dev mode
--------
If `ALLOWED_EMAILS` is empty, auth is disabled: the `X-User-Email` header
(or `"dev@local"`) is returned without verification.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

from app.config import get_settings

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="not authorized"
)


def require_user(
    authorization: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
) -> str:
    s = get_settings()
    allowed = s.allowed_emails_list

    # Dev mode: no allowlist => no auth.
    if not allowed:
        return x_user_email or "dev@local"

    # Production: require a signed bearer token.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    token = authorization[7:].strip()
    if not token or not s.nextauth_jwt_secret:
        raise _UNAUTHORIZED

    try:
        payload = jwt.decode(
            token, s.nextauth_jwt_secret, algorithms=["HS256"]
        )
    except JWTError:
        raise _UNAUTHORIZED

    email = payload.get("email")
    if not isinstance(email, str):
        raise _UNAUTHORIZED
    email = email.lower()
    if email not in allowed:
        raise _UNAUTHORIZED
    return email
