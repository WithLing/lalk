import { useCallback, useEffect, useState } from "react";
import { getConfig, saveConfig } from "../api/http";
import type { AppConfig, ConfigResponse, ConnectionState } from "./contracts";

export const CONFIG_CONNECTION_TIMEOUT_MS = 3_000;
const CONFIG_CONNECTION_ERROR = "无法连接本地服务，请确认服务已启动后重新读取。";

export function useConfiguration(connection: ConnectionState) {
  const [response, setResponse] = useState<ConfigResponse | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const waitingForConnection = connection !== "ready" && response === null;

  useEffect(() => {
    if (!waitingForConnection) return;
    const timeout = window.setTimeout(() => {
      setRequestError(CONFIG_CONNECTION_ERROR);
    }, CONFIG_CONNECTION_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, [waitingForConnection, reloadVersion]);

  useEffect(() => {
    if (connection !== "ready") return;
    let active = true;
    setRequestError(null);
    void getConfig()
      .then((next) => {
        if (active) setResponse(next);
      })
      .catch((error) => {
        if (!active) return;
        setRequestError(
          error instanceof Error ? error.message : "Failed to load configuration",
        );
      });
    return () => { active = false; };
  }, [connection, reloadVersion]);

  const save = useCallback(async (config: AppConfig) => {
    const next = await saveConfig(config);
    setResponse(next);
    setRequestError(null);
  }, []);

  const retry = useCallback(() => {
    setRequestError(null);
    setReloadVersion((version) => version + 1);
  }, []);

  const clearResponseError = useCallback(() => {
    setResponse((current) =>
      current?.error ? { ...current, error: null } : current,
    );
  }, []);

  return {
    response,
    requestError,
    loading: response === null && requestError === null,
    save,
    retry,
    clearResponseError,
  };
}
