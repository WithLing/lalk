import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const brandId = process.env.LALK_DESKTOP_BRAND ?? "lalk";
const configDirectory = fileURLToPath(new URL(".", import.meta.url));
const brandDirectory = resolve(configDirectory, "../desktop/brands", brandId);
const brandPath = resolve(brandDirectory, "brand.json");
const brand = JSON.parse(readFileSync(brandPath, "utf8"));
const escapeHtml = (value) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

export default defineConfig({
  base: "./",
  plugins: [
    react(),
    {
      name: "lalk-desktop-brand",
      transformIndexHtml(html) {
        return html
          .replace(
            /<meta name="description" content="[^"]*" \/>/,
            `<meta name="description" content="${escapeHtml(brand.description)}" />`,
          )
          .replace(/<title>[^<]*<\/title>/, `<title>${escapeHtml(brand.productName)}</title>`);
      },
    },
  ],
  resolve: {
    alias: {
      "@desktop-brand": brandPath,
      "@desktop-brand-logo": resolve(brandDirectory, brand.logo),
    },
  },
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 17840,
    strictPort: true,
  },
});
