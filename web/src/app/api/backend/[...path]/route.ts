/**
 * Transparent server-side proxy for the FastAPI backend.
 *
 * Why this exists:
 *   1. The backend expects `Authorization: Bearer <jwt>` where the JWT is the
 *      exact HS256 token Auth.js signed. We don't want to expose that token to
 *      the browser, so we keep it server-side by reading the session cookie
 *      here and attaching it as a bearer header.
 *   2. The browser gets a same-origin endpoint (`/api/backend/...`), which
 *      sidesteps CORS and cookie-domain issues in prod.
 *
 * Any client component can now do:
 *     fetch("/api/backend/candidates?status=manual_review")
 * and get exactly what `GET /api/candidates?status=manual_review` returns
 * from FastAPI.
 */
import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

import { auth, SESSION_COOKIE_NAMES } from "../../../../../auth";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Hop-by-hop headers that must not be forwarded.
const STRIP_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "accept-encoding",
  "cookie",
  "authorization",
]);

const STRIP_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function readSessionToken(): Promise<string | null> {
  const jar = await cookies();
  for (const name of SESSION_COOKIE_NAMES) {
    const v = jar.get(name)?.value;
    if (v) return v;
  }
  return null;
}

async function forward(req: NextRequest, params: { path: string[] }) {
  // Double-check the session is valid before doing any work. Without this an
  // expired-but-present cookie would quietly forward a dead token. `auth()`
  // can throw JWTSessionError when the cookie is present but undecodable
  // (e.g. stale from a prior AUTH_SECRET) — treat that as unauthorized.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let session: any = null;
  let authErr: unknown = null;
  try {
    session = await auth();
  } catch (e) {
    authErr = e;
  }
  if (!session?.user?.email) {
    const jar = await cookies();
    const cookieNames = jar.getAll().map((c) => c.name);
    console.error("[proxy] unauthorized", {
      path: params.path.join("/"),
      hasSession: !!session,
      sessionUser: session?.user,
      authErr: authErr ? String(authErr) : null,
      cookieNames,
    });
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }

  const token = await readSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "missing session token" }, { status: 401 });
  }

  const subpath = params.path.join("/");
  const search = req.nextUrl.search ?? "";
  const target = `${BACKEND_URL}/api/${subpath}${search}`;

  const headers = new Headers();
  for (const [k, v] of req.headers) {
    if (!STRIP_REQUEST_HEADERS.has(k.toLowerCase())) headers.set(k, v);
  }
  headers.set("Authorization", `Bearer ${token}`);
  // Belt-and-braces: also send the email header. In dev mode the backend
  // skips JWT verification and falls back to X-User-Email, so this makes
  // local dev work even without a real Google OAuth client configured.
  headers.set("X-User-Email", session.user.email);

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  const body = hasBody ? await req.arrayBuffer() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: body && body.byteLength > 0 ? new Uint8Array(body) : undefined,
      // Don't let Next cache backend responses; everything here is dynamic.
      cache: "no-store",
      redirect: "manual",
    });
  } catch (err) {
    return NextResponse.json(
      { detail: "backend unreachable", error: String(err) },
      { status: 502 },
    );
  }

  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE_HEADERS.has(key.toLowerCase())) resHeaders.set(key, value);
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function handler(req: NextRequest, ctx: RouteContext) {
  return forward(req, await ctx.params);
}

export {
  handler as GET,
  handler as POST,
  handler as PUT,
  handler as PATCH,
  handler as DELETE,
};
