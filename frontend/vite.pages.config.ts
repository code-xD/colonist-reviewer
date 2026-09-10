import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/colonist-reviewer/",
  plugins: [react()],
  root: "static-app",
  build: {
    outDir: "../pages-dist",
    emptyOutDir: true,
  },
  publicDir: false,
});
