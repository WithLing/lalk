import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Turn } from "../runtime/contracts";
import { ConversationPanel, runtimeStagePresentation } from "./ConversationPanel";

function renderTurn(
  source: Turn["source"],
  overrides: Partial<Pick<Turn, "state">> & {
    assistant?: Partial<Turn["assistant"]>;
  } = {},
): string {
  const turn: Turn = {
    session_id: "session-1",
    turn_id: 1,
    source,
    user_text: source === "voice" || source === "text" ? "用户输入" : "",
    state: overrides.state ?? "completed",
    assistant: {
      parts: overrides.assistant?.parts ?? [{ type: "text", text: "助手回复" }],
      playback_state: overrides.assistant?.playback_state ?? "completed",
      spoken_text: overrides.assistant?.spoken_text ?? "助手回复",
    },
    metrics: null,
    error: null,
  };
  return renderToStaticMarkup(createElement(ConversationPanel, {
    turns: [turn],
    liveTranscript: null,
    runtimeState: "running",
    stage: "listening",
    inputLevel: 0,
    interruptionSignal: null,
    pendingCommand: null,
    onSubmit: async () => undefined,
    onInterrupt: async () => undefined,
  }));
}

describe("runtimeStagePresentation", () => {
  it("maps the voice pipeline to user-facing stages", () => {
    expect(runtimeStagePresentation("listening", "running", false)).toMatchObject({
      label: "正在聆听",
      tone: "listening",
    });
    expect(runtimeStagePresentation("thinking", "running", false)).toMatchObject({
      label: "正在思考",
      tone: "thinking",
    });
    expect(runtimeStagePresentation("playing", "running", false)).toMatchObject({
      label: "正在回复",
      tone: "responding",
    });
  });

  it("gives interruption feedback precedence over the pipeline stage", () => {
    expect(runtimeStagePresentation("playing", "running", true)).toEqual({
      label: "已打断回复",
      hint: "已停止本轮语音播放",
      tone: "interrupted",
    });
  });
});

describe("ConversationPanel turn source", () => {
  it("shows user messages only for real user input", () => {
    expect(renderTurn("voice")).toContain("用户输入");
    expect(renderTurn("text")).toContain("用户输入");
    expect(renderTurn("opening")).not.toContain("aria-label=\"用户消息\"");
    expect(renderTurn("proactive")).not.toContain("aria-label=\"用户消息\"");
    expect(renderTurn("followup")).not.toContain("aria-label=\"用户消息\"");
  });

  it("hides interruption copy when the assistant has not replied", () => {
    const markup = renderTurn("voice", {
      state: "interrupted",
      assistant: {
        parts: [],
        playback_state: "interrupted",
        spoken_text: "",
      },
    });

    expect(markup).not.toContain("你打断了上一条回复");
  });

  it("shows interruption copy after part of the reply was played", () => {
    const markup = renderTurn("voice", {
      state: "interrupted",
      assistant: {
        parts: [{ type: "text", text: "已经开始回复" }],
        playback_state: "interrupted",
        spoken_text: "已经开始",
      },
    });

    expect(markup).toContain("你打断了上一条回复");
  });
});
