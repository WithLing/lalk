import { useEffect } from "react";
import {
  getAgentModePreset,
  type PresetAgentMode,
} from "../demo-agent-modes";

interface AgentModeSnapshotProps {
  mode: PresetAgentMode;
  onClose: () => void;
}

const exhaustedLabels = {
  wait: "继续聆听",
  stop: "关闭语音",
  farewell: "告别后关闭",
};

function SnapshotSwitch({ enabled }: { enabled: boolean }) {
  return (
    <i className={`generation-switch ${enabled ? "enabled" : ""}`} aria-hidden="true">
      <b />
    </i>
  );
}
export function AgentModeSnapshot({ mode, onClose }: AgentModeSnapshotProps) {
  const preset = getAgentModePreset(mode);
  const context = Object.entries(preset.dynamicContext);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div
      className="mode-snapshot-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="configuration-page mode-snapshot-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mode-snapshot-title"
      >
        <div className="mode-snapshot-scroll">
          <div className="mode-snapshot-shell">
            <header className="mode-snapshot-header">
              <div>
                <span>内置示例 · 只读</span>
                <h2 id="mode-snapshot-title">{preset.label}配置参考</h2>
                <p>下面展示当前模式实际使用的配置，你可以参考它在通用模式中创建自己的 Agent。</p>
              </div>
              <button type="button" aria-label="关闭配置参考" onClick={onClose}>×</button>
            </header>

            <div className="agent-layout mode-snapshot-layout">
              <article className="configuration-card mode-snapshot-generation-card">
                <section className="generation-settings" aria-label="生成配置参考">
                  <div className="generation-setting-row">
                    <span>
                      <strong>思考模式</strong>
                      <small>默认开启；关闭时发送 thinking.type=disabled</small>
                    </span>
                    <SnapshotSwitch enabled={preset.thinkingEnabled} />
                  </div>
                  <div className="generation-setting-row">
                    <span>
                      <strong>主动开启对话</strong>
                      <small>开启语音后，Agent 会根据系统提示词主动开始对话</small>
                    </span>
                    <SnapshotSwitch enabled={preset.openingEnabled} />
                  </div>
                  <div className="generation-setting-row">
                    <span>
                      <strong>误打断过滤</strong>
                      <small>Agent 播放时，简短附和词不会中断播放</small>
                    </span>
                    <SnapshotSwitch enabled={preset.backchannelFilterEnabled} />
                  </div>
                  <div className="generation-setting-row">
                    <span>
                      <strong>无响应时主动询问</strong>
                      <small>每次进入聆听后，用户没有回应时，Agent 会主动询问</small>
                    </span>
                    <SnapshotSwitch enabled />
                  </div>
                  <div className="followup-settings">
                    <div className="generation-setting-row followup-setting-row">
                      <span>
                        <strong>询问间隔</strong>
                        <small>Agent 播放结束并重新进入聆听后开始计时</small>
                      </span>
                      <span className="mode-snapshot-value">{preset.inactivityPolicy.timeout_seconds} 秒</span>
                    </div>
                    <div className="generation-setting-row followup-setting-row">
                      <span>
                        <strong>最多询问</strong>
                        <small>连续无回应时最多主动询问的次数</small>
                      </span>
                      <span className="mode-snapshot-value">{preset.inactivityPolicy.max_followups} 次</span>
                    </div>
                    <div className="generation-setting-row followup-setting-row">
                      <span>
                        <strong>达到上限后</strong>
                        <small>完成预设动作后不再继续追问</small>
                      </span>
                      <span className="mode-snapshot-value mode-snapshot-action">
                        {exhaustedLabels[preset.inactivityPolicy.on_exhausted]}
                      </span>
                    </div>
                  </div>
                </section>
              </article>

              <article className={`configuration-card personalization-card ${preset.personalizationEnabled ? "open" : ""}`}>
                <div className="personalization-toggle-row">
                  <div>
                    <h3>个性化配置</h3>
                    <p>设置助手的角色、业务目标和工作方式；默认语音与工具规则会自动保留。</p>
                  </div>
                  <span className="personalization-switch" aria-hidden="true"><i /></span>
                </div>
                {preset.personalizationEnabled && (
                  <div className="personalization-content">
                    <label className="instructions-field">
                      <span>角色与工作要求</span>
                      <textarea
                        aria-label={`${preset.label}角色与工作要求`}
                        value={preset.instructions}
                        readOnly
                      />
                    </label>
                    <section className="context-section">
                      <header>
                        <div>
                          <h3>全局信息</h3>
                          <p>智能体需要长期了解的固定信息，例如服务模式和业务目标。</p>
                        </div>
                        <span className="mode-snapshot-readonly-badge">只读参考</span>
                      </header>
                      <div className="context-labels"><span>信息名称</span><span>信息内容</span><span /></div>
                      <div className="context-editor">
                        {context.map(([name, value]) => (
                          <div className="context-row" key={name}>
                            <input aria-label="信息名称" value={name} readOnly />
                            <input aria-label="信息内容" value={value} readOnly />
                            <span className="mode-snapshot-context-mark">—</span>
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                )}
              </article>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
