import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/colonist-reviewer/",
  plugins: [react()],
  root: "pages",
  build: {
    outDir: "../pages-dist",
    emptyOutDir: true,
  },
  publicDir: false,
});
