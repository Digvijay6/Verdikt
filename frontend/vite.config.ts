import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tailwind v4 is a Vite plugin rather than a PostCSS step, and its config lives
// in CSS (`@theme` in app.css) rather than a tailwind.config.js. There is
// deliberately no config file to look for.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
});
