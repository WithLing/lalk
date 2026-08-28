import { CSSProperties, FormEvent, memo, useEffect, useRef, useState } from "react";
import type {
  LiveTranscript,
  RuntimeStage,
  RuntimeStatus,
  Turn,
} from "../runtime/contracts";
import {
  alignPartsToPlayback,
  conversationScrollKey,
} from "../runtime/playback-text";
import { MarkdownMessage } from "./MarkdownMessage";
import { StreamingTranscript } from "./StreamingTranscript";
import { ToolPart } from "./ToolPart";

type StageTone = "idle" | "listening" | "thinking" | "responding" | "interrupted";

const interruptibleStages = new Set<RuntimeStage>([
  "thinking",
  "tool_running",
  "synthesizing",
  "playing",
]);

const ConversationTurn = memo(function ConversationTurn({ turn }: { turn: Turn }) {
  const visibleParts = turn.state === "completed"
    ? turn.assistant.parts
    : alignPartsToPlayback(
        turn.assistant.parts,
        turn.assistant.spoken_text,
      );

  return (
    <section className={`turn-group ${turn.state}`}>
      {(turn.source === "voice" || turn.source === "text") && (
        <article className="message-row user-row" aria-label="用户消息">
          <div className="message-content"><MarkdownMessage>{turn.user_text}</MarkdownMessage></div>
        </article>
      )}
      {visibleParts.map((part, index) =>
        part.type === "tool" ? (
          <ToolPart part={part} key={part.call_id} />
        ) : (
          <article className="message-row assistant-row" aria-label="助手消息" key={`text-${index}`}>
            <div className="message-content">
              <MarkdownMessage>{part.text}</MarkdownMessage>
              <span className={turn.state === "started" && index === visibleParts.length - 1 ? "stream-caret" : ""} />
            </div>
          </article>
        ),
      )}
      {turn.state === "interrupted" && visibleParts.length > 0 && (
        <div className="turn-state"><i /><span>你打断了上一条回复</span><i /></div>
      )}
      {turn.error && (
        <article className="message-row error-row" aria-label="错误">
          <div className="message-content">{turn.error.message}</div>
        </article>
      )}
    </section>
  );
});

export function runtimeStagePresentation(
  stage: RuntimeStage,
  runtimeState: RuntimeStatus,
  interrupted: boolean,
): { label: string; hint: string; tone: StageTone } {
  if (interrupted) {
    return { label: "已打断回复", hint: "已停止本轮语音播放", tone: "interrupted" };
  }
  if (runtimeState === "starting") {
    return { label: "正在启动", hint: "正在准备语音服务", tone: "thinking" };
  }
  if (runtimeState === "stopping") {
    return { label: "正在停止", hint: "正在结束当前会话", tone: "idle" };
  }
  if (runtimeState !== "running") {
    return { label: "语音未开启", hint: "开始语音后可直接说话", tone: "idle" };
  }
  switch (stage) {
    case "user_speaking":
      return { label: "正在聆听", hint: "检测到你正在说话", tone: "listening" };
    case "listening":
      return { label: "正在聆听", hint: "我在听，直接说话", tone: "listening" };
    case "transcribing":
      return { label: "正在识别", hint: "正在整理你的语音", tone: "thinking" };
    case "thinking":
      return { label: "正在思考", hint: "正在组织回复", tone: "thinking" };
    case "tool_running":
      return { label: "正在处理", hint: "正在执行所需操作", tone: "thinking" };
    case "synthesizing":
      return { label: "正在回复", hint: "正在生成语音", tone: "responding" };
    case "playing":
      return { label: "正在回复", hint: "语音正在播放", tone: "responding" };
    default:
      return { label: "已准备好", hint: "等待你开始说话", tone: "idle" };
  }
}

export function ConversationPanel({
  turns,
  liveTranscript,
  runtimeState,
  stage,
  inputLevel,
  interruptionSignal,
  pendingCommand,
  onSubmit,
  onInterrupt,
}: {
  turns: Turn[];
  liveTranscript: LiveTranscript | null;
  runtimeState: RuntimeStatus;
  stage: RuntimeStage;
  inputLevel: number;
  interruptionSignal: string | null;
  pendingCommand: string | null;
  onSubmit: (text: string) => Promise<void>;
  onInterrupt: () => Promise<unknown>;
}) {
  const [text, setText] = useState("");
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [interruptionVisible, setInterruptionVisible] = useState(false);
  const previousInterruptionRef = useRef(interruptionSignal);
  const interruptionTimerRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const stickToBottomRef = useRef(true);
  const inputRef = useRef<HTMLInputElement>(null);
  const running = runtimeState === "running";
  const canInterrupt = running && interruptibleStages.has(stage);
  const showComposer = composerExpanded;
  const scrollKey = `${conversationScrollKey(turns)}:${liveTranscript?.text ?? ""}`;
  const stagePresentation = runtimeStagePresentation(stage, runtimeState, interruptionVisible);
  const decibels = inputLevel > 0 ? 20 * Math.log10(inputLevel) : -60;
  const meter = Math.max(0, Math.min(1, (decibels + 60) / 60));
  const edgeStyle = {
    "--edge-opacity": (0.42 + Math.max(0.18, meter) * 0.58).toFixed(3),
    "--edge-scale": (0.28 + Math.max(0.18, meter) * 0.72).toFixed(3),
  } as CSSProperties;

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const element = scrollRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [scrollKey]);

  useEffect(() => {
    if (running) setComposerExpanded(false);
  }, [running]);

  useEffect(() => {
    if (!running || !composerExpanded) return;
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 180);
    return () => window.clearTimeout(focusTimer);
  }, [composerExpanded, running]);

  useEffect(() => {
    if (!interruptionSignal) {
      previousInterruptionRef.current = null;
      setInterruptionVisible(false);
      if (interruptionTimerRef.current !== null) {
        window.clearTimeout(interruptionTimerRef.current);
        interruptionTimerRef.current = null;
      }
      return;
    }
    if (interruptionSignal === previousInterruptionRef.current) return;
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

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || !running || pendingCommand !== null) return;
    stickToBottomRef.current = true;
    void onSubmit(value).then(
      () => {
        setText("");
        setComposerExpanded(false);
      },
      () => undefined,
    );
  };

  return (
    <section className="conversation-panel">
      <div
        className="conversation-scroll"
        ref={scrollRef}
        onScroll={(event) => {
          const element = event.currentTarget;
          stickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72;
        }}
      >
        {turns.length === 0 && !liveTranscript?.text ? (
          <div className="conversation-empty">
            <strong>{running ? "可以开始了" : "语音尚未开启"}</strong>
            <span>{running ? "直接说话，或在下方输入消息。" : "点击右上角开始语音后查看实时对话。"}</span>
          </div>
        ) : (
          <div className="message-list">
            {turns.map((turn) => (
              <ConversationTurn turn={turn} key={`${turn.session_id}-${turn.turn_id}`} />
            ))}
            {liveTranscript?.text && (
              <article className="message-row user-row live-transcript-row" aria-label="实时语音识别">
                <div className="message-content">
                  <StreamingTranscript
                    text={liveTranscript.text}
                    isFinal={liveTranscript.is_final}
                  />
                </div>
              </article>
            )}
          </div>
        )}
      </div>

      <div className={`conversation-dock ${showComposer ? "expanded" : "collapsed"} ${running ? "voice-active" : "voice-inactive"} ${stagePresentation.tone}`}>
        <div className="conversation-stage" role="status" aria-live="polite">
          <span className="conversation-stage-copy" key={`${stagePresentation.label}:${stagePresentation.hint}`}>
            <strong>{stagePresentation.label}</strong>
            {(!showComposer || !running) && <small>{stagePresentation.hint}</small>}
          </span>
          <span className="conversation-stage-actions">
            <button
              className="composer-toggle"
              type="button"
              onClick={() => setComposerExpanded((value) => !value)}
              aria-expanded={composerExpanded}
              aria-label={composerExpanded ? "收起文字输入" : "展开文字输入"}
            >
              {composerExpanded ? (
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="3.5" y="5.5" width="17" height="13" rx="3" />
                  <path d="M7 9h.01M10.3 9h.01M13.7 9h.01M17 9h.01M7 12.2h.01M10.3 12.2h.01M13.7 12.2h.01M17 12.2h.01M8.5 15.3h7" />
                </svg>
              )}
              <span>{composerExpanded ? "收起" : "输入文字"}</span>
            </button>
            {canInterrupt && (
              <button
                className="conversation-interrupt"
                type="button"
                disabled={pendingCommand !== null}
                onClick={() => void onInterrupt().catch(() => undefined)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8v8M16 8v8" /></svg>
                <span>打断</span>
              </button>
            )}
          </span>
        </div>

        <form className="composer" onSubmit={submit} aria-hidden={!showComposer}>
          <input
            ref={inputRef}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setComposerExpanded(false);
                inputRef.current?.blur();
              }
            }}
            placeholder={running ? "输入消息…" : "请先开始语音"}
            disabled={!running}
            tabIndex={showComposer ? 0 : -1}
            aria-label="Message"
          />
          <button type="submit" disabled={!running || !text.trim() || pendingCommand !== null} tabIndex={showComposer ? 0 : -1} aria-label="Send message">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" /></svg>
          </button>
        </form>

        <span
          className="conversation-ambient-edge"
          style={edgeStyle}
          aria-label={`麦克风输入电平 ${Math.round(meter * 100)}%`}
        >
          <i className="ambient-edge-soft" aria-hidden="true" />
          <i className="ambient-edge-core" aria-hidden="true" />
        </span>
      </div>
    </section>
  );
}
