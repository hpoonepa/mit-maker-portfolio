import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://papercrane.bio",
  base: "/_landing",
  output: "static",
  outDir: "../public/_landing",
  server: {
    host: "127.0.0.1",
    port: 4321,
  },
  vite: {
    build: {
      target: "es2022",
    },
  },
});
