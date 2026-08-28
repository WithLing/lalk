/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LALK_SERVER_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  __LALK_SERVER_URL__?: string;
}

declare module "@desktop-brand" {
  const brand: import("./brand").DesktopBrand;
  export default brand;
}

declare module "@desktop-brand-logo" {
  const source: string;
  export default source;
}
