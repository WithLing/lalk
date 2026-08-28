import brandConfig from "@desktop-brand";
import brandLogo from "@desktop-brand-logo";

export interface DesktopBrand {
  id: string;
  productName: string;
  displayName: string;
  bundleIdentifier: string;
  description: string;
  microphoneUsageDescription: string;
  logo: string;
  iconsDir: string;
}

export const brand = brandConfig;
export { brandLogo };
