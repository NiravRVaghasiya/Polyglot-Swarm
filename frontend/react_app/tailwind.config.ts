import type { Config } from "tailwindcss";

// Semantic colour tokens. The values live in globals.css as RGB channels so
// one class (`bg-surface`, `text-muted`, ...) works in light and dark mode
// and still supports Tailwind's opacity modifier (`bg-brand/10`).
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        surface2: token("surface-2"),
        fg: token("fg"),
        muted: token("muted"),
        line: token("line"),
        brand: token("brand"),
        "brand-fg": token("brand-fg"),
        "brand-soft": token("brand-soft"),
        link: token("link"),
        accent: token("accent"),
        "accent-soft": token("accent-soft"),
        danger: token("danger"),
        "danger-soft": token("danger-soft"),
        warn: token("warn"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        card: "0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -4px rgb(15 23 42 / 0.08)",
        lift: "0 2px 4px rgb(15 23 42 / 0.06), 0 12px 32px -8px rgb(79 70 229 / 0.25)",
        glow: "0 0 0 4px rgb(79 70 229 / 0.15)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "typing-dot": {
          "0%, 60%, 100%": { transform: "translateY(0)", opacity: "0.4" },
          "30%": { transform: "translateY(-4px)", opacity: "1" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(1)", opacity: "0.55" },
          "100%": { transform: "scale(1.6)", opacity: "0" },
        },
        "eq-bar": {
          "0%, 100%": { transform: "scaleY(0.3)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        "typing-dot": "typing-dot 1.2s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.4s cubic-bezier(0.2, 0.6, 0.4, 1) infinite",
        "eq-bar": "eq-bar 0.9s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
