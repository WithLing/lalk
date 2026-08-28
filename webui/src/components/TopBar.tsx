import { useState } from "react";
import type { ConnectionState, RuntimeStatus } from "../runtime/contracts";
import { isSessionActive } from "../runtime/status";

export function TopBar({
  connection,
  runtimeState,
  pending,
  hasConversation,
  dark,
  monitorOpen,
  onConnect,
  onConfigure,
  onOpenVoice,
  onToggleMonitor,
  onNewConversation,
  onToggleTheme,
}: {
  connection: ConnectionState;
  runtimeState: RuntimeStatus;
  pending: boolean;
  hasConversation: boolean;
  dark: boolean;
  monitorOpen: boolean;
  onConnect: () => void;
  onConfigure: () => void;
  onOpenVoice: () => void;
  onToggleMonitor: () => void;
  onNewConversation: () => Promise<void>;
  onToggleTheme: () => void;
}) {
  const [confirmNewConversation, setConfirmNewConversation] = useState(false);
  const active = isSessionActive(runtimeState);
  const unavailable = connection !== "ready";
  const label =
    connection === "connecting" || connection === "syncing"
      ? "正在连接"
      : active
        ? pending
          ? "正在结束"
          : "结束语音"
        : pending
          ? "正在启动"
          : "开始语音";

  return (
    <header className="topbar">
      <div aria-hidden="true" />

      <div className="top-actions">
        <div className="new-conversation-anchor">
          <button
            className="configuration-entry"
            type="button"
            disabled={pending}
            aria-haspopup="dialog"
            aria-expanded={confirmNewConversation}
            onClick={() => {
              if (hasConversation) setConfirmNewConversation(true);
              else void onNewConversation().catch(() => undefined);
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            新对话
          </button>
          {confirmNewConversation && (
            <div className="topbar-new-confirm" role="dialog" aria-label="确认开始新对话">
              <span>当前聊天内容将被清除</span>
              <div>
                <button type="button" onClick={() => setConfirmNewConversation(false)}>取消</button>
                <button
                  className="danger"
                  type="button"
                  disabled={pending}
                  onClick={() => void onNewConversation().then(
                    () => setConfirmNewConversation(false),
                    () => undefined,
                  )}
                >
                  开始新对话
                </button>
              </div>
            </div>
          )}
        </div>
        <button className="configuration-entry" type="button" onClick={onOpenVoice}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M9 18V6a3 3 0 0 1 6 0v12a3 3 0 0 1-6 0Z" />
            <path d="M5.5 12.5a6.5 6.5 0 0 0 13 0M12 22v-1" />
          </svg>
          语音界面
        </button>
        <button
          className={`configuration-entry inspector-entry ${monitorOpen ? "active" : ""}`}
          type="button"
          onClick={onToggleMonitor}
          aria-pressed={monitorOpen}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 7h5M15 7h5M4 17h9M19 17h1" />
            <circle cx="12" cy="7" r="2.5" />
            <circle cx="16" cy="17" r="2.5" />
          </svg>
          监控
        </button>
        <button className="configuration-entry" type="button" onClick={onConfigure}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19 13.5v-3l-2-.6-.7-1.6 1-1.9-2.1-2.1-1.9 1-1.6-.7L11 2H8l-.6 2-1.6.7-1.9-1-2.1 2.1 1 1.9-.7 1.6-2 .6v3l2 .6.7 1.6-1 1.9 2.1 2.1 1.9-1 1.6.7.6 2h3l.6-2 1.6-.7 1.9 1 2.1-2.1-1-1.9.7-1.6 2-.6Z" />
          </svg>
          配置
        </button>
        <button className="icon-button" type="button" onClick={onToggleTheme} title="Toggle theme" aria-label="Toggle theme">
          {dark ? (
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z" /></svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.5" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
          )}
        </button>
        <button
          className={`connect-button ${active ? "active" : ""}`}
          type="button"
          disabled={unavailable || pending || runtimeState === "stopping"}
          onClick={onConnect}
        >
          {label}
        </button>
      </div>
    </header>
  );
}
