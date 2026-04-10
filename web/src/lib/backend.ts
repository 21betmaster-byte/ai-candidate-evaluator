/**
 * Typed wrappers around the `/api/backend/*` proxy.
 *
 * Works from both server components (absolute URL built from headers) and
 * client components (relative URL — same-origin). Every call goes through
 * the proxy so auth is attached transparently.
 */
import type {
  CandidateDetail,
  CandidateRow,
  LogEntryWithCandidate,
  SettingsModel,
} from "./types";

type FetchOpts = {
  /** absolute base URL; required on the server, unused in the browser */
  baseUrl?: string;
  /** forward cookies from an inbound server request */
  cookieHeader?: string;
  /** abort signal to cancel the in-flight request */
  signal?: AbortSignal;
};

function url(path: string, opts: FetchOpts = {}) {
  const rel = `/api/backend${path.startsWith("/") ? path : `/${path}`}`;
  if (typeof window !== "undefined") return rel;
  if (!opts.baseUrl) {
    throw new Error("backend.ts: baseUrl is required on the server");
  }
  return `${opts.baseUrl}${rel}`;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  opts: FetchOpts = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (opts.cookieHeader) headers.set("cookie", opts.cookieHeader);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const res = await fetch(url(path, opts), {
    ...init,
    headers,
    cache: "no-store",
    signal: opts.signal,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new BackendError(res.status, text || res.statusText);
  }
  // 204 no content.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class BackendError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(`backend ${status}: ${message}`);
    this.status = status;
  }
}

export const backend = {
  listCandidates(
    params: { status?: string; sort?: string } = {},
    opts?: FetchOpts,
  ) {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.sort) qs.set("sort", params.sort);
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<CandidateRow[]>(`/candidates${suffix}`, {}, opts);
  },

  getCandidate(id: number, opts?: FetchOpts) {
    return request<CandidateDetail>(`/candidates/${id}`, {}, opts);
  },

  manualDecision(id: number, decision: "pass" | "fail", opts?: FetchOpts) {
    return request<{ ok: boolean; status: string }>(
      `/candidates/${id}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
      opts,
    );
  },

  getSettings(opts?: FetchOpts) {
    return request<SettingsModel>(`/settings`, {}, opts);
  },

  updateSettings(body: SettingsModel, opts?: FetchOpts) {
    return request<SettingsModel>(
      `/settings`,
      { method: "PUT", body: JSON.stringify(body) },
      opts,
    );
  },

  getLogs(
    params: { step?: string; level?: string; candidate_id?: number; email?: string; limit?: number; offset?: number } = {},
    opts?: FetchOpts,
  ) {
    const qs = new URLSearchParams();
    if (params.step) qs.set("step", params.step);
    if (params.level) qs.set("level", params.level);
    if (params.candidate_id) qs.set("candidate_id", params.candidate_id.toString());
    if (params.email) qs.set("email", params.email);
    if (params.limit != null) qs.set("limit", params.limit.toString());
    if (params.offset != null) qs.set("offset", params.offset.toString());
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<LogEntryWithCandidate[]>(`/logs${suffix}`, {}, opts);
  },

  pollNow(opts?: FetchOpts) {
    return request<{ new_messages: number }>(
      `/poll`,
      { method: "POST" },
      opts,
    );
  },
};
