import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";

// Design tokens copied verbatim from the stitch/ mockups so screens render
// identically to the static HTML. Do not invent new tokens here — if a
// component needs a shade that isn't in the mock, add it to the mock first.
const config: Config = {
  darkMode: "class",
  content: [
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#FF4757",
        "on-primary": "#ffffff",
        "primary-fixed": "#ffd9de",
        "primary-fixed-dim": "#ffb2be",
        "primary-container": "#dd2561",
        "on-primary-fixed": "#3f0015",
        "on-primary-fixed-variant": "#900039",
        "on-primary-container": "#fffbff",
        "inverse-primary": "#ffb2be",
        secondary: "#5c5988",
        "on-secondary": "#ffffff",
        "secondary-fixed": "#e3dfff",
        "secondary-fixed-dim": "#c5c1f7",
        "secondary-container": "#cec9ff",
        "on-secondary-container": "#565381",
        "on-secondary-fixed": "#191541",
        "on-secondary-fixed-variant": "#45426f",
        tertiary: "#95442d",
        "on-tertiary": "#ffffff",
        "tertiary-container": "#b35c43",
        "on-tertiary-container": "#fffbff",
        "tertiary-fixed": "#ffdbd1",
        "tertiary-fixed-dim": "#ffb5a0",
        "on-tertiary-fixed": "#3b0900",
        "on-tertiary-fixed-variant": "#79301a",
        error: "#ba1a1a",
        "on-error": "#ffffff",
        "error-container": "#ffdad6",
        "on-error-container": "#93000a",
        background: "#fff8f9",
        "on-background": "#2b1423",
        surface: "#fff8f9",
        "on-surface": "#2b1423",
        "surface-bright": "#fff8f9",
        "surface-dim": "#f7cfe4",
        "surface-variant": "#ffd8ec",
        "on-surface-variant": "#5a4044",
        "surface-container-lowest": "#ffffff",
        "surface-container-low": "#fff0f5",
        "surface-container": "#ffe8f2",
        "surface-container-high": "#ffe0ef",
        "surface-container-highest": "#ffd8ec",
        "inverse-surface": "#422838",
        "inverse-on-surface": "#ffecf4",
        outline: "#8e6f73",
        "outline-variant": "#e3bdc2",
        "surface-tint": "#bc004c",
      },
      borderRadius: {
        DEFAULT: "0.125rem",
        lg: "0.25rem",
        xl: "0.5rem",
        full: "9999px",
      },
      fontFamily: {
        headline: ["var(--font-epilogue)", "sans-serif"],
        body: ["var(--font-inter)", "sans-serif"],
        label: ["var(--font-jakarta)", "sans-serif"],
      },
      boxShadow: {
        editorial: "0px 12px 32px rgba(43,20,35,0.06)",
        "editorial-soft": "0px 12px 32px rgba(43,20,35,0.04)",
      },
    },
  },
  plugins: [forms],
};

export default config;
