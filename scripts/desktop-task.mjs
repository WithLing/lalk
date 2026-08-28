import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const tauriRoot = path.join(projectRoot, "desktop", "src-tauri");
const arguments_ = process.argv.slice(2);
let brandId = process.env.LALK_DESKTOP_BRAND ?? "lalk";

for (let index = 0; index < arguments_.length; index += 1) {
  const argument = arguments_[index];
  if (argument === "--brand") {
    const value = arguments_[index + 1];
    if (!value || value.startsWith("--")) {
      console.error("--brand requires a brand id");
      process.exit(2);
    }
    brandId = value;
    arguments_.splice(index, 2);
    index -= 1;
  } else if (argument.startsWith("--brand=")) {
    brandId = argument.slice("--brand=".length);
    arguments_.splice(index, 1);
    index -= 1;
  }
}

if (!/^[a-z0-9][a-z0-9-]*$/.test(brandId)) {
  console.error(`Invalid desktop brand id: ${brandId}`);
  process.exit(2);
}

const brandDirectory = path.join(projectRoot, "desktop", "brands", brandId);
const brandPath = path.join(brandDirectory, "brand.json");
if (!existsSync(brandPath)) {
  console.error(`Desktop brand does not exist: ${brandId}`);
  process.exit(2);
}

const brand = JSON.parse(readFileSync(brandPath, "utf8"));
for (const field of [
  "id",
  "productName",
  "displayName",
  "bundleIdentifier",
  "description",
  "microphoneUsageDescription",
  "logo",
  "iconsDir",
]) {
  if (typeof brand[field] !== "string" || brand[field].trim() === "") {
    console.error(`Desktop brand ${brandId} has an invalid ${field}`);
    process.exit(2);
  }
}
if (brand.id !== brandId) {
  console.error(`Desktop brand id mismatch: expected ${brandId}, got ${brand.id}`);
  process.exit(2);
}

const iconsDirectory = path.resolve(brandDirectory, brand.iconsDir);
const iconFiles = [
  "icon.png",
  "32x32.png",
  "128x128.png",
  "128x128@2x.png",
  "icon.icns",
  "icon.ico",
];
for (const icon of iconFiles) {
  if (!existsSync(path.join(iconsDirectory, icon))) {
    console.error(`Desktop brand ${brandId} is missing icons/${icon}`);
    process.exit(2);
  }
}
if (!existsSync(path.resolve(brandDirectory, brand.logo))) {
  console.error(`Desktop brand ${brandId} is missing its logo`);
  process.exit(2);
}

const baseConfig = JSON.parse(
  readFileSync(path.join(tauriRoot, "tauri.conf.json"), "utf8"),
);
const relativeIconsDirectory = path
  .relative(tauriRoot, iconsDirectory)
  .split(path.sep)
  .join("/");
const flavorConfig = {
  productName: brand.productName,
  identifier: brand.bundleIdentifier,
  app: {
    windows: baseConfig.app.windows.map((window, index) => (
      index === 0 ? { ...window, title: brand.displayName } : window
    )),
  },
  bundle: {
    icon: iconFiles.map((icon) => `${relativeIconsDirectory}/${icon}`),
  },
};

const escapeXml = (value) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&apos;");
writeFileSync(
  path.join(tauriRoot, "Info.plist"),
  `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>NSMicrophoneUsageDescription</key>
    <string>${escapeXml(brand.microphoneUsageDescription)}</string>
</dict>
</plist>
`,
  "utf8",
);

arguments_.push("--config", JSON.stringify(flavorConfig));

const child = spawn(
  "pnpm",
  ["--dir", "desktop", "tauri", ...arguments_],
  {
    cwd: projectRoot,
    env: {
      ...process.env,
      LALK_DESKTOP_BRAND: brandId,
    },
    stdio: "inherit",
  },
);

child.on("error", (error) => {
  console.error(`Unable to start the Tauri CLI: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
