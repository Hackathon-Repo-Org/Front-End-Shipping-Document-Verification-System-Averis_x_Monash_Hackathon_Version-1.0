import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base URL is BUILD-TIME config (VITE_API_BASE_URL) and is never hardcoded.
// Static Web Apps serves a built bundle; there is no server to read an env var at
// request time, so the value has to be baked in at build.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", sourcemap: false },
});
