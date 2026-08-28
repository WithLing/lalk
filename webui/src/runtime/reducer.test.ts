import { describe, expect, it } from "vitest";
import { initialRuntimeState, runtimeReducer } from "./reducer";
import type { RuntimeEventMessage, RuntimeSnapshot } from "./contracts";

const snapshot: RuntimeSnapshot = {
  runtime_state: "idle",
  stage: "idle",
  stage_started_at: null,
  session_id: null,
  sequence: 0,
  components: {},
  input_level: 0,
  live_transcript: null,
  turns: [],
  error: null,
  proactive_offer: null,
};

const event = (
  seq: number,
  type: RuntimeEventMessage["type"],
  data: Record<string, unknown>,
): RuntimeEventMessage => ({
  seq,
  type,
  stage: "thinking",
  stage_started_at: 1,
  timestamp: 1,
  data,
});

describe("runtimeReducer", () => {
  it("uses snapshots as the authoritative runtime view", () => {
    const state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot: { ...snapshot, sequence: 9, runtime_state: "running" },
    });
    expect(state.connection).toBe("ready");
    expect(state.runtimeState).toBe("running");
    expect(state.sequence).toBe(9);
  });

  it("projects ordered assistant text and tool parts", () => {
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(1, "turn.input", {
        session_id: "session",
        turn_id: 1,
        source: "text",
        text: "weather",
      }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(2, "assistant.text.delta", { turn_id: 1, delta: "Checking." }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(3, "tool.started", {
        turn_id: 1,
        call_id: "call-1",
        name: "weather",
        arguments: { city: "Shanghai" },
      }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(4, "tool.finished", {
        turn_id: 1,
        call_id: "call-1",
        name: "weather",
        result: "Sunny",
        succeeded: true,
        elapsed_ms: 25,
        file_changes: [
          {
            path: "sale_agent.md",
            added: 1,
            deleted: 1,
            unified_diff:
              "--- sale_agent.md\n+++ sale_agent.md\n@@ -4 +4 @@\n-旧价格话术\n+新价格话术",
          },
        ],
      }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(5, "assistant.text.delta", {
        turn_id: 1,
        delta: "It is sunny.",
      }),
    });

    expect(state.turns[0].assistant.parts).toEqual([
      { type: "text", text: "Checking." },
      {
        type: "tool",
        call_id: "call-1",
        name: "weather",
        arguments: { city: "Shanghai" },
        state: "succeeded",
        result: "Sunny",
        elapsed_ms: 25,
        file_changes: [
          {
            path: "sale_agent.md",
            added: 1,
            deleted: 1,
            unified_diff:
              "--- sale_agent.md\n+++ sale_agent.md\n@@ -4 +4 @@\n-旧价格话术\n+新价格话术",
          },
        ],
      },
      { type: "text", text: "It is sunny." },
    ]);
    expect(state.logs.map((entry) => entry.type)).toEqual([
      "snapshot",
      "turn.input",
      "tool.started",
      "tool.finished",
    ]);
  });

  it("updates only the matching session when turn ids repeat", () => {
    const repeatedTurn = (sessionId: string) => ({
      session_id: sessionId,
      turn_id: 1,
      source: "voice" as const,
      user_text: "你能做啥？",
      state: "started" as const,
      assistant: { parts: [], playback_state: null, spoken_text: "" },
      metrics: null,
      error: null,
    });
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot: {
        ...snapshot,
        turns: [repeatedTurn("session-a"), repeatedTurn("session-b")],
      },
    });

    state = runtimeReducer(state, {
      type: "event",
      event: event(1, "assistant.text.delta", {
        session_id: "session-b",
        turn_id: 1,
        delta: "帮你处理代码，改文件，验证。",
      }),
    });

    expect(state.turns[0].assistant.parts).toEqual([]);
    expect(state.turns[1].assistant.parts).toEqual([
      { type: "text", text: "帮你处理代码，改文件，验证。" },
    ]);
  });

  it("ignores already applied event sequences", () => {
    const synchronized = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot: { ...snapshot, sequence: 3 },
    });
    const unchanged = runtimeReducer(synchronized, {
      type: "event",
      event: event(3, "speech.state", { state: "started" }),
    });
    expect(unchanged).toBe(synchronized);
  });

  it("updates input level without adding an event log", () => {
    const synchronized = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    const updated = runtimeReducer(synchronized, {
      type: "event",
      event: event(1, "audio.input_level", { level: 0.4 }),
    });

    expect(updated.inputLevel).toBe(0.4);
    expect(updated.logs).toHaveLength(synchronized.logs.length);
  });

  it("replaces live transcripts and clears them when the turn is accepted", () => {
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(1, "transcript.update", {
        text: "你好",
        is_final: false,
        language: "zh",
      }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(2, "transcript.update", {
        text: "你好世界",
        is_final: false,
        language: "zh",
      }),
    });

    expect(state.liveTranscript?.text).toBe("你好世界");
    expect(state.logs.at(-1)?.type).toBe("snapshot");

    state = runtimeReducer(state, {
      type: "event",
      event: event(3, "turn.input", {
        session_id: "session",
        turn_id: 1,
        source: "voice",
        text: "你好世界",
      }),
    });
    expect(state.liveTranscript).toBeNull();
    expect(state.turns[0].user_text).toBe("你好世界");
  });

  it("projects adaptive input gate diagnostics", () => {
    const synchronized = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    const updated = runtimeReducer(synchronized, {
      type: "event",
      event: event(1, "audio.input_level", {
        level: 0.04,
        level_db: -28,
        noise_floor_db: -42,
        threshold_db: -35,
        gate_mode: "normal",
        gate_passed: true,
      }),
    });

    expect(updated.inputGate).toEqual({
      level_db: -28,
      noise_floor_db: -42,
      threshold_db: -35,
      mode: "normal",
      passed: true,
    });
    expect(updated.logs).toHaveLength(synchronized.logs.length);
  });

  it("projects and clears a proactive offer", () => {
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    const offer = {
      id: "request-1",
      title: "Product meeting",
      available_at: "2026-08-19T09:00:00+00:00",
      state: "offered",
    } as const;

    state = runtimeReducer(state, {
      type: "event",
      event: event(1, "proactive.offer", { offer }),
    });
    expect(state.proactiveOffer).toEqual(offer);

    state = runtimeReducer(state, {
      type: "event",
      event: event(2, "proactive.offer", { offer: null }),
    });
    expect(state.proactiveOffer).toBeNull();
  });

  it("marks the latest turn when the user interrupts a response", () => {
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(1, "turn.input", {
        session_id: "session",
        turn_id: 7,
        source: "voice",
        text: "stop there",
      }),
    });
    state = runtimeReducer(state, {
      type: "event",
      event: event(2, "turn.state", { turn_id: 7, state: "interrupted" }),
    });

    expect(state.turns.at(-1)?.state).toBe("interrupted");
  });

  it("keeps only the 100 most recent event logs", () => {
    let state = runtimeReducer(initialRuntimeState, {
      type: "snapshot",
      snapshot,
    });

    for (let seq = 1; seq <= 120; seq += 1) {
      state = runtimeReducer(state, {
        type: "event",
        event: event(seq, "speech.state", { state: `state-${seq}` }),
      });
    }

    expect(state.logs).toHaveLength(100);
    expect(state.logs.at(-1)?.type).toBe("speech.state");
  });

  it("dismisses runtime and client errors", () => {
    const state = {
      ...initialRuntimeState,
      clientError: "command failed",
      error: { message: "microphone failed" },
    };

    expect(runtimeReducer(state, { type: "error.clear" })).toMatchObject({
      clientError: null,
      error: null,
    });
  });
});
