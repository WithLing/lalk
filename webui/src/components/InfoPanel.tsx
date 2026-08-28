import { brand } from "../brand";
import type {
  ConnectionState,
  RuntimeStage,
  RuntimeStatus,
} from "../runtime/contracts";

export function InfoPanel({
  connection,
  runtimeState,
  stage,
  sessionId,
  inputLevel,
}: {
  connection: ConnectionState;
  runtimeState: RuntimeStatus;
  stage: RuntimeStage;
  sessionId: string | null;
  inputLevel: number;
}) {
  const connected = connection === "ready";
  const agentReady = runtimeState === "running";
  const decibels = inputLevel > 0 ? 20 * Math.log10(inputLevel) : -60;
  const meter = Math.max(0, Math.min(1, (decibels + 60) / 60));
  return (
    <aside className="info-column">
      <section className="info-panel">
        <header className="panel-header"><h2>Status</h2></header>
        <section className="info-section status-section">
          <dl>
            <dt>Client</dt><dd><span className={`state-dot ${connected ? "online" : ""}`}>{connected ? "connected" : connection}</span></dd>
            <dt>Agent</dt><dd><span className={`state-dot ${agentReady ? "online" : ""}`}>{agentReady ? "ready" : "—"}</span></dd>
            <dt>Stage</dt><dd>{stage}</dd>
          </dl>
        </section>

        <section className="devices-section">
          <h2>Devices</h2>
          <div
            className={`microphone-control ${runtimeState === "running" ? "active" : ""}`}
            title="Live microphone input level"
          >
            <span className="microphone-icon">♪</span>
            <i className="input-level-meter" aria-label={`Input level ${Math.round(meter * 100)}%`}>
              {Array.from({ length: 12 }, (_, index) => (
                <b className={meter >= (index + 1) / 12 ? "active" : ""} key={index} />
              ))}
            </i>
          </div>
        </section>

        <section className="info-section session-section">
          <h2>Session</h2>
          <dl>
            <dt>Transport</dt><dd>Local WebSocket</dd>
            <dt>Session ID</dt><dd title={sessionId ?? "—"}>{sessionId ?? "—"}</dd>
            <dt>Participant ID</dt><dd>local-user</dd>
            <dt>Client</dt><dd>{brand.displayName} UI</dd>
            <dt>Server</dt><dd>v0.1.0</dd>
          </dl>
        </section>
      </section>
    </aside>
  );
}
