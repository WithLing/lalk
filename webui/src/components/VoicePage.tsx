import { useEffect, useRef, useState } from "react";
import type { LiveTranscript, RuntimeStage, RuntimeStatus } from "../runtime/contracts";
import { isSessionActive } from "../runtime/status";
import { StreamingTranscript } from "./StreamingTranscript";
import { useVoiceAnimation } from "./voice/useVoiceAnimation";

interface VoicePageProps {
  stage: RuntimeStage;
  runtimeState: RuntimeStatus;
  inputLevel: number;
  liveTranscript: LiveTranscript | null;
  acceptedTranscript: string | null;
  interruptionSignal: string | null;
  hasConversation: boolean;
  pending: boolean;
  onToggleSession: () => void;
  onNewConversation: () => Promise<void>;
  onOpenSettings: () => void;
  onOpenWorkbench: () => void;
}

function runtimeLabel(stage: RuntimeStage, runtimeState: RuntimeStatus) {
  if (runtimeState === "starting") return "正在启动";
  if (runtimeState === "stopping") return "正在停止";
  if (runtimeState !== "running") return "点击开始聆听";
  switch (stage) {
    case "user_speaking":
    case "listening": return "正在聆听";
    case "transcribing": return "正在识别";
    case "thinking": return "正在思考";
    case "tool_running": return "正在处理";
    case "synthesizing": return "正在回应";
    case "playing": return "正在回应";
    default: return "已准备好";
  }
}

export function VoicePage({
  stage,
  runtimeState,
  inputLevel,
  liveTranscript,
  acceptedTranscript,
  interruptionSignal,
  hasConversation,
  pending,
  onToggleSession,
  onNewConversation,
  onOpenSettings,
  onOpenWorkbench,
}: VoicePageProps) {
  const previousInterruptionRef = useRef(interruptionSignal);
  const interruptionTimerRef = useRef<number | null>(null);
  const [interruptionVisible, setInterruptionVisible] = useState(false);
  const [displayedTranscript, setDisplayedTranscript] = useState(liveTranscript);
  const [confirmNewConversation, setConfirmNewConversation] = useState(false);
  const canvasRef = useVoiceAnimation(stage, runtimeState, inputLevel);
  const speaking = !interruptionVisible && stage === "playing";
  const sessionActive = isSessionActive(runtimeState);
  const statusLabel = interruptionVisible
    ? "已打断回应"
    : runtimeLabel(stage, runtimeState);

  useEffect(() => {
    if (liveTranscript?.text) {
      setDisplayedTranscript(liveTranscript);
      return;
    }
    if (
      acceptedTranscript
      && runtimeState === "running"
      && stage !== "idle"
      && stage !== "listening"
      && stage !== "user_speaking"
    ) {
      setDisplayedTranscript({
        text: acceptedTranscript,
        is_final: true,
        language: null,
      });
      return;
    }
    if (
      runtimeState !== "running"
      || stage === "idle"
      || stage === "listening"
      || stage === "user_speaking"
    ) {
      setDisplayedTranscript(null);
    }
  }, [acceptedTranscript, liveTranscript, runtimeState, stage]);

  useEffect(() => {
    if (!interruptionSignal || interruptionSignal === previousInterruptionRef.current) return;
    previousInterruptionRef.current = interruptionSignal;
    setInterruptionVisible(true);
    if (interruptionTimerRef.current !== null) {
      window.clearTimeout(interruptionTimerRef.current);
    }
    interruptionTimerRef.current = window.setTimeout(() => {
      interruptionTimerRef.current = null;
      setInterruptionVisible(false);
    }, 2_200);
  }, [interruptionSignal]);

  useEffect(() => () => {
    if (interruptionTimerRef.current !== null) {
      window.clearTimeout(interruptionTimerRef.current);
    }
  }, []);

  return (
    <main className="voice-page">
      <header className="voice-page-header" aria-hidden="true" />

      <section className="voice-page-stage">
        <div className="voice-page-aura" aria-hidden="true" />
        <canvas ref={canvasRef} className="voice-page-canvas" aria-label="彩色方格声音动画" />
        <div
          className={`voice-page-state ${interruptionVisible ? "interrupted" : speaking ? "speaking" : "listening"}`}
          role="status"
          aria-live="polite"
        >
          <span className="voice-page-listen-icon" aria-hidden="true">
            <i /><i /><b />
          </span>
          <span className="voice-page-talk-icon" aria-hidden="true">
            <i /><i /><i /><i /><i />
          </span>
          <span className="voice-page-interrupt-icon" aria-hidden="true">
            <i /><b />
          </span>
          <span key={statusLabel} className="voice-page-state-label">
            {statusLabel}
          </span>
        </div>
        {displayedTranscript?.text && (
          <p className="voice-page-transcript" aria-live="polite">
            <StreamingTranscript
              text={displayedTranscript.text}
              isFinal={displayedTranscript.is_final}
            />
          </p>
        )}
      </section>

      <footer className="voice-page-footer">
        <button className="voice-page-settings" type="button" aria-label="打开设置" title="设置" onClick={onOpenSettings}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 8.75A3.25 3.25 0 1 0 12 15.25 3.25 3.25 0 0 0 12 8.75Z" />
            <path d="M19.1 13.55a7.6 7.6 0 0 0 .05-1.55 7.6 7.6 0 0 0-.05-1.55l1.62-1.27-1.85-3.2-1.92.75a7.9 7.9 0 0 0-2.68-1.55L14 3.15h-4l-.27 2.03a7.9 7.9 0 0 0-2.68 1.55l-1.92-.75-1.85 3.2 1.62 1.27A7.6 7.6 0 0 0 4.85 12c0 .53.02 1.05.05 1.55l-1.62 1.27 1.85 3.2 1.92-.75a7.9 7.9 0 0 0 2.68 1.55L10 20.85h4l.27-2.03a7.9 7.9 0 0 0 2.68-1.55l1.92.75 1.85-3.2-1.62-1.27Z" />
          </svg>
        </button>
        <button
          className={`voice-page-mic ${sessionActive ? "active" : ""} ${pending ? "pending" : ""}`}
          type="button"
          aria-label={sessionActive ? "结束语音" : "开始聆听"}
          title={sessionActive ? "结束语音" : "开始聆听"}
          disabled={pending || runtimeState === "stopping"}
          onClick={onToggleSession}
        >
          <i /><span />
        </button>
        <div className="voice-page-shortcuts">
          {hasConversation && (
            confirmNewConversation ? (
              <div className="voice-page-new-confirm" role="dialog" aria-label="确认开始新对话">
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
            ) : (
              <button
                className="voice-page-new-conversation"
                type="button"
                aria-label="新对话"
                title="新对话"
                disabled={pending}
                onClick={() => setConfirmNewConversation(true)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
            )
          )}
          <button className="voice-page-workbench" type="button" aria-label="切换至工作台" title="切换至工作台" onClick={onOpenWorkbench}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="4" y="4" width="6" height="6" rx="1.4" />
              <rect x="14" y="4" width="6" height="6" rx="1.4" />
              <rect x="4" y="14" width="6" height="6" rx="1.4" />
              <rect x="14" y="14" width="6" height="6" rx="1.4" />
            </svg>
          </button>
        </div>
      </footer>
    </main>
  );
}
