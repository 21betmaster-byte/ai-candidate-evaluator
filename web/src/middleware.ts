/**
 * Gate every page except /signin behind a valid session.
 *
 * We call `auth()` inside a try/catch rather than using the
 * `auth((req) => …)` wrapper because Auth.js v5 throws `JWTSessionError`
 * when a session cookie is present but can't be decoded (e.g. it was
 * minted under a previous AUTH_SECRET or before we switched to HS256).
 * In that case we self-heal by clearing the stale cookies and bouncing
 * the user to /signin, instead of 500ing on every request.
 */
import { NextResponse, type NextRequest } from "next/server";

import { auth, SESSION_COOKIE_NAMES } from "../auth";

export default async function middleware(req: NextRequest) {
  const { nextUrl } = req;
  const isSignIn = nextUrl.pathname.startsWith("/signin");
  const isAuthRoute = nextUrl.pathname.startsWith("/api/auth");
  if (isSignIn || isAuthRoute) return;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let session: any = null;
  try {
    session = await auth();
  } catch {
    // Stale / undecodable cookie — fall through to the redirect + clear.
  }

  if (!session) {
    const url = new URL("/signin", nextUrl.origin);
    url.searchParams.set("from", nextUrl.pathname);
    const res = NextResponse.redirect(url);
    // Clear both plain and chunked variants (Auth.js splits large cookies
    // into `.0`, `.1`, …) plus any legacy v4 name that might linger.
    const names = [
      ...SESSION_COOKIE_NAMES,
      ...SESSION_COOKIE_NAMES.flatMap((n) => [`${n}.0`, `${n}.1`, `${n}.2`]),
      "next-auth.session-token",
      "__Secure-next-auth.session-token",
    ];
    for (const name of names) {
      res.cookies.set(name, "", { path: "/", maxAge: 0 });
    }
    return res;
  }
}

// Run on every route except Next.js internals and static files.
export const config = {
  matcher: ["/((?!_next|favicon.ico|icons|assets).*)"],
};
