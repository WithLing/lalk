import { useEffect, useRef, useState } from "react";
import type { AgentMode, PresetAgentMode } from "../demo-agent-modes";
import { AgentModeSnapshot } from "./AgentModeSnapshot";

interface AgentModeMenuProps {
  mode: AgentMode;
  pending: boolean;
  error: string | null;
  onChange: (mode: AgentMode) => void;
}

const modes: Array<{ id: AgentMode; label: string; description: string }> = [
  { id: "general", label: "通用助手", description: "使用你自己的个性化配置" },
  { id: "sales", label: "销售顾问", description: "了解需求并推动下一步" },
  { id: "support", label: "客服专员", description: "理解问题并协助解决" },
];

const modeLabels: Record<AgentMode, string> = {
  general: "通用模式",
  sales: "销售模式",
  support: "客服模式",
};

export function AgentModeMenu({ mode, pending, error, onChange }: AgentModeMenuProps) {
  const [open, setOpen] = useState(false);
  const [snapshotMode, setSnapshotMode] = useState<PresetAgentMode | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="agent-mode-menu-anchor" ref={anchorRef}>
      <button
        className="agent-mode-trigger"
        type="button"
        disabled={pending}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <strong>{modeLabels[mode]}</strong>
        <i className="agent-mode-chevron" aria-hidden="true" />
      </button>

      {open && (
        <div className="agent-mode-popover" role="menu" aria-label="选择 Agent 模式">
          <header><strong>选择 Agent 模式</strong><small>切换后会开始一段新对话</small></header>
          <div className="agent-mode-options">
            {modes.map((item) => (
              <div className={`agent-mode-option ${item.id === mode ? "active" : ""}`} key={item.id}>
                <button
                  className="agent-mode-option-main"
                  type="button"
                  role="menuitemradio"
                  aria-checked={item.id === mode}
                  onClick={() => {
                    setOpen(false);
                    onChange(item.id);
                  }}
                >
                  <i aria-hidden="true">{item.id === mode ? "✓" : ""}</i>
                  <span><strong>{item.label}</strong><small>{item.description}</small></span>
                </button>
                {item.id !== "general" && (
                  <button
                    className="agent-mode-option-snapshot"
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      setSnapshotMode(item.id as PresetAgentMode);
                    }}
                  >
                    查看配置
                  </button>
                )}
              </div>
            ))}
          </div>
          {error && <p className="agent-mode-menu-error" role="alert">{error}</p>}
        </div>
      )}

      {snapshotMode && (
        <AgentModeSnapshot mode={snapshotMode} onClose={() => setSnapshotMode(null)} />
      )}
    </div>
  );
}
