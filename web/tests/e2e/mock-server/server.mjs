/**
 * Tiny in-process mock backend for Playwright.
 *
 * Why this exists: the dashboard pages are React Server Components that call
 * the FastAPI backend from inside the Next.js Node process via BACKEND_URL.
 * Playwright's `page.route(...)` can only intercept BROWSER-side network
 * traffic — it cannot see server-side fetches. So we point BACKEND_URL at
 * this mock HTTP server, and the e2e fixtures push canned responses into
 * it via a `/__mock` control endpoint before each test runs.
 *
 * Lifecycle: Playwright's webServer config launches this with `node` and
 * waits for the /__mock/health endpoint to come up.
 *
 * Storage: mocks are held per-key in an in-process Map. There is no
 * persistence — between tests, the suite calls /__mock/reset.
 *
 * Recording: every non-control request is appended to a calls log so tests
 * can assert "the dashboard called PUT /api/settings with this payload".
 */
import http from "node:http";

const PORT = Number(process.env.MOCK_BACKEND_PORT ?? 8765);

/** mocks: key = `${METHOD} ${pathname}`  →  { status, body, headers? }
 *  Some keys have special handling (see resolveMock). */
const mocks = new Map();
/** calls: array of { method, path, query, body } */
const calls = [];

function key(method, pathname) {
  return `${method} ${pathname}`;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => (data += chunk));
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

function send(res, status, body, contentType = "application/json") {
  res.writeHead(status, { "content-type": contentType });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

/**
 * Resolve the mock for a given (method, pathname). Tries an exact match
 * first, then falls back to pattern keys (e.g. "GET /api/candidates/:id").
 */
function resolveMock(method, pathname) {
  const exact = mocks.get(key(method, pathname));
  if (exact) return exact;

  // Pattern matching: any stored key with a `:param` segment.
  for (const [stored, value] of mocks.entries()) {
    const [storedMethod, storedPath] = stored.split(" ");
    if (storedMethod !== method) continue;
    if (!storedPath.includes(":")) continue;
    const re = new RegExp(
      "^" +
        storedPath
          .split("/")
          .map((seg) =>
            seg.startsWith(":") ? "([^/]+)" : seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
          )
          .join("/") +
        "$",
    );
    if (re.test(pathname)) return value;
  }
  return null;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const method = req.method ?? "GET";
  const pathname = url.pathname;

  // ---- Control plane ------------------------------------------------------
  if (pathname === "/__mock/health") return send(res, 200, { ok: true });

  if (pathname === "/__mock/reset" && method === "POST") {
    mocks.clear();
    calls.length = 0;
    return send(res, 200, { ok: true });
  }

  // POST /__mock/set  body: { "GET /api/settings": { status: 200, body: {...} }, ... }
  if (pathname === "/__mock/set" && method === "POST") {
    try {
      const body = JSON.parse((await readBody(req)) || "{}");
      for (const [k, v] of Object.entries(body)) {
        mocks.set(k, v);
      }
      return send(res, 200, { ok: true, count: mocks.size });
    } catch (err) {
      return send(res, 400, { error: String(err) });
    }
  }

  // GET /__mock/calls  → returns the recorded calls (most recent first)
  if (pathname === "/__mock/calls" && method === "GET") {
    return send(res, 200, calls);
  }

  // ---- Backend mock plane -------------------------------------------------
  const rawBody = method === "GET" || method === "HEAD" ? "" : await readBody(req);
  let parsedBody = null;
  try {
    parsedBody = rawBody ? JSON.parse(rawBody) : null;
  } catch {
    parsedBody = rawBody;
  }
  calls.push({
    method,
    path: pathname,
    query: Object.fromEntries(url.searchParams),
    body: parsedBody,
  });

  const mock = resolveMock(method, pathname);
  if (!mock) {
    return send(res, 404, {
      detail: `mock-server: no canned response for ${method} ${pathname}`,
    });
  }
  return send(res, mock.status ?? 200, mock.body ?? {});
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`[mock-backend] listening on http://localhost:${PORT}`);
});

// Graceful shutdown so Playwright doesn't leave a zombie.
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    server.close(() => process.exit(0));
  });
}
