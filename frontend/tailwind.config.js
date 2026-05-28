/** @type {import('tailwindcss').Config} */
export default {
  // Scans the React SPA (BP reference) AND the Django templates so the
  // rebuilt non-BP pages can use BP's real Tailwind classes/tokens — one
  // config, one source of truth, no parallel bespoke CSS that can drift.
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
    "../stock/templates/**/*.html",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        page: "#030712",
        rail: "#050912",
        card: "#0b111a",
        brand: "#f5a400",
        internal: "#1473ff",
        wholesale: "#7c3aed",
        pos: "#22c55e",
        neg: "#ef4444",
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        mono: ['"DM Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
