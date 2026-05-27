import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by Django under /dashboard with assets at /static/dashboard/.
// The Django view reads dist/index.html verbatim; whitenoise serves the
// hashed bundles. Keep base in sync with STATICFILES_DIRS in settings.py.
export default defineConfig({
  base: "/static/dashboard/",
  plugins: [react()],
  build: {
    outDir: "dist",
    assetsDir: "assets",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    // Local dev proxy: `npm run dev` on :5173 talks to Django on :8000.
    // Production never hits this — Django serves the built bundle.
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
