import type { CSSProperties } from "react";
import type { InputGateMode, InputGateState } from "../../runtime/contracts";

const MIN_DB = -90;
const MAX_DB = 0;

const MODE_LABELS: Record<InputGateMode, string> = {
  bootstrap: "正在适应环境",
  normal: "自动适应环境",
  playback: "播放期",
  speaking: "正在收音",
};

function position(db: number | null) {
  if (db === null) return null;
  return Math.max(0, Math.min(100, ((db - MIN_DB) / (MAX_DB - MIN_DB)) * 100));
}

function markerStyle(db: number | null) {
  const left = position(db);
  return left === null ? undefined : ({ "--gate-position": `${left}%` } as CSSProperties);
}

export function AdaptiveGateCard({
  gate,
  speechDetected,
}: {
  gate: InputGateState;
  speechDetected: boolean;
}) {
  const inputPosition = position(gate.level_db) ?? 0;
  const calibrating = gate.mode === "bootstrap";
  const visualState = calibrating
    ? "calibrating"
    : speechDetected
      ? "speech"
      : gate.passed
        ? "checking"
        : "listening";
  const stateCopy = calibrating
    ? { title: "正在适应环境", subtitle: "稍后就可以开始说话" }
    : speechDetected
      ? { title: "听到你了", subtitle: "已确认是人声" }
      : gate.passed
        ? { title: "正在确认…", subtitle: "听到声音，正在辨别人声" }
        : gate.mode === "playback"
          ? { title: "随时可以打断", subtitle: "直接开始说话" }
          : { title: "正在聆听", subtitle: "等待你开始说话" };

  return (
    <section className={`adaptive-gate-card ${visualState}`} aria-label="麦克风实时状态">
      <header>
        <span>麦克风</span>
        <b>{MODE_LABELS[gate.mode]}</b>
      </header>

      <div className="adaptive-gate-status" aria-live="polite">
        <div>
          <strong>{stateCopy.title}</strong>
          <span>{stateCopy.subtitle}</span>
        </div>
      </div>

      <div className="adaptive-gate-plot">
        <div className={`adaptive-gate-meter ${gate.passed && !calibrating ? "passed" : ""}`}>
          <i className="input-fill" style={{ width: `${inputPosition}%` }} />
          {gate.threshold_db != null && (
            <span className="threshold-marker" style={markerStyle(gate.threshold_db)} title="识别门槛" />
          )}
        </div>
      </div>
    </section>
  );
}
