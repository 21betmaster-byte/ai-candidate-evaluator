import { defineConfig } from "vitest/config";
import path from "node:path";

// Lightweight Vitest config. We test React components in jsdom — not the
// Next.js runtime — so server-only things (cookies(), next/headers) never
// get imported into these tests. Vitest/esbuild transforms .tsx natively
// with `jsx: "automatic"`, so we don't need @vitejs/plugin-react.
//
// Scope: client-component logic only (SettingsForm, CandidateRow, buttons).
// Pages and layouts that touch server APIs are covered by Playwright instead.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/unit/setup.tsx"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    server: {
      deps: {
        inline: ["@testing-library/user-event"],
      },
    },
  },
  esbuild: {
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
