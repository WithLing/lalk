import type { RuntimeStatus } from "./contracts";

const sessionStates = new Set<RuntimeStatus>([
  "starting",
  "running",
  "stopping",
]);

export const isSessionActive = (status: RuntimeStatus) =>
  sessionStates.has(status);
