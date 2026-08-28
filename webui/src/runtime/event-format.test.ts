import { describe, expect, it } from "vitest";
import type { RuntimeEventMessage } from "./contracts";
import { formatEvent } from "./event-format";

describe("formatEvent", () => {
  it("summarizes model and TTS usage once per turn", () => {
    const event: RuntimeEventMessage = {
      seq: 1,
      type: "turn.metrics",
      stage: "listening",
      stage_started_at: 1,
      data: {
        turn_id: 3,
        metrics: {
          estimated_user_stop_to_first_playback_ms: 820,
          turn_ms: 2_100,
          llm_usage: { completion_tokens: 42 },
          tts_usage: {
            text_words: 18,
            input_characters: 36,
            audio_bytes: 35_840,
          },
        },
      },
    };

    expect(formatEvent(event)).toBe(
      "Turn 3 · model output 42 tokens · TTS 18 words · 36 characters · " +
        "35.0 KiB audio · first playback 820.0 ms · total 2100.0 ms",
    );
  });
});
