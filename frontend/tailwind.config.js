/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
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
