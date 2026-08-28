const configuredUrl =
  window.__LALK_SERVER_URL__ ??
  import.meta.env.VITE_LALK_SERVER_URL ??
  "http://127.0.0.1:17841";

export const SERVER_URL = configuredUrl.replace(/\/$/, "");
export const SERVER_WS_URL = SERVER_URL.replace(/^http:/, "ws:").replace(
  /^https:/,
  "wss:",
);
