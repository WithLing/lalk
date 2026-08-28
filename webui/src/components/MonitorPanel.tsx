import { useState } from "react";
import type { InputGateState, RuntimeStage, Turn } from "../runtime/contracts";
import { MetricsPanel } from "./MetricsPanel";
import { AdaptiveGateCard } from "./voice/AdaptiveGateCard";

type MonitorTab = "gate" | "metrics";

export function MonitorPanel({
  inputGate,
  stage,
  turns,
}: {
  inputGate: InputGateState | null;
  stage: RuntimeStage;
  turns: Turn[];
}) {
  const [tab, setTab] = useState<MonitorTab>("metrics");

  return (
    <>
      <header className="metrics-inspector-header">
        <h2>监控</h2>
        <nav className="monitor-tabs" aria-label="监控内容">
          <button
            className={tab === "metrics" ? "active" : ""}
            type="button"
            aria-pressed={tab === "metrics"}
            onClick={() => setTab("metrics")}
          >
            性能指标
          </button>
          <button
            className={tab === "gate" ? "active" : ""}
            type="button"
            aria-pressed={tab === "gate"}
            onClick={() => setTab("gate")}
          >
            实时检测
          </button>
        </nav>
      </header>

      {tab === "gate" ? (
        <div className="gate-monitor-view">
          {inputGate === null ? (
            <div className="monitor-empty">
              <strong>暂无实时检测数据</strong>
              <span>开始语音后，这里会显示麦克风输入、噪声底和门槛。</span>
            </div>
          ) : (
            <AdaptiveGateCard
              gate={inputGate}
              speechDetected={stage === "user_speaking"}
            />
          )}
        </div>
      ) : (
        <MetricsPanel turns={turns} />
      )}
    </>
  );
}
