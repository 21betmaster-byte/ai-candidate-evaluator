/**
 * Global test setup — runs once before every Vitest suite.
 *
 * - Wires `@testing-library/jest-dom` matchers into Vitest's expect.
 * - Stubs next/navigation (useRouter, usePathname) since our client
 *   components touch those but jsdom has no Next runtime.
 * - Stubs next/link so we can assert on href without loading Next.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import React from "react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

// ---- next/navigation stub ---------------------------------------------------
// Exposes a mutable `mockRouter` object each test can inspect.
export const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  back: vi.fn(),
  prefetch: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => "/candidates",
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  },
}));

// ---- next/link stub ---------------------------------------------------------
// Renders children wrapped in a plain <a>. Keeps href assertable.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [k: string]: unknown;
  }) =>
    React.createElement("a", { href, ...(rest as Record<string, unknown>) }, children),
}));
