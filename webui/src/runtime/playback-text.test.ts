import { describe, expect, it } from "vitest";
import type { AssistantPart, Turn } from "./contracts";
import {
  alignPartsToPlayback,
  conversationScrollKey,
  sourcePrefixForPlayback,
} from "./playback-text";

const parts: AssistantPart[] = [
  { type: "text", text: "我来查询一下。" },
  {
    type: "tool",
    call_id: "call-1",
    name: "weather",
    arguments: { city: "上海" },
    state: "succeeded",
    result: "晴",
    elapsed_ms: 20,
  },
  { type: "text", text: "上海今天晴。" },
];

describe("alignPartsToPlayback", () => {
  it("does not expose generated text or its following tool before playback", () => {
    expect(alignPartsToPlayback(parts, "")).toEqual([]);
  });

  it("keeps a tool hidden until all preceding text has played", () => {
    expect(alignPartsToPlayback(parts, "我来查询")).toEqual([
      { type: "text", text: "我来查询" },
    ]);
  });

  it("reveals only text confirmed as played and preserves tool order", () => {
    expect(alignPartsToPlayback(parts, "我来查询一下。上海今")).toEqual([
      { type: "text", text: "我来查询一下。" },
      parts[1],
      { type: "text", text: "上海今" },
    ]);
  });

  it("reveals the complete response after playback finishes", () => {
    expect(alignPartsToPlayback(parts, "我来查询一下。上海今天晴。")).toEqual(parts);
  });

  it("aligns plain TTS subtitles back onto Markdown source text", () => {
    const markdown = "**📄 `demo.py` — 简单的 Python 示例脚本**\n\n- 打印问候语";
    const spoken = "demo.py — 简单的 Python 示例脚本 打印问候语";

    expect(sourcePrefixForPlayback(markdown, spoken)).toBe(markdown.length);
  });

  it("shows a leading tool immediately when no spoken introduction precedes it", () => {
    expect(alignPartsToPlayback([parts[1], parts[2]], "")).toEqual([parts[1]]);
  });

  it("scrolls for visible changes but not unseen model deltas", () => {
    const turn: Turn = {
      session_id: "session",
      turn_id: 1,
      source: "text",
      user_text: "天气",
      state: "started",
      assistant: {
        parts: [{ type: "text", text: "上海" }],
        playback_state: null,
        spoken_text: "",
      },
      metrics: null,
      error: null,
    };
    const initial = conversationScrollKey([turn]);
    const generated = conversationScrollKey([
      {
        ...turn,
        assistant: {
          ...turn.assistant,
          parts: [{ type: "text", text: "上海今天晴。" }],
        },
      },
    ]);
    const played = conversationScrollKey([
      {
        ...turn,
        assistant: { ...turn.assistant, spoken_text: "上海" },
      },
    ]);

    expect(generated).toBe(initial);
    expect(played).not.toBe(initial);
  });
});
