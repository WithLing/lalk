import { describe, expect, it } from "vitest";
import type { TurnMetrics } from "../runtime/contracts";
import {
  formatAsrUsage,
  formatModelUsage,
  formatTtsUsage,
  latencyBreakdown,
} from "./MetricsPanel";

const metrics: TurnMetrics = {
  vad_confirmation_ms: 200,
  turn_detection_ms: 40.4,
  asr_finalization_ms: 52.1,
  asr_audio_seconds: 2,
  agent_request_preparation_ms: 4,
  agent_first_token_ms: 739.9,
  llm_first_token_ms: 735.9,
  text_aggregation_ms: 20,
  tts_first_audio_ms: 300,
  vad_stop_to_tts_first_audio_ms: 1_112.4,
  estimated_user_stop_to_first_playback_ms: 1_870.5,
  speech_first_playback_ms: 838.1,
  interruption_ms: null,
  turn_ms: 3_000,
  asr_usage: null,
  llm_usage: null,
  tts_usage: null,
};

describe("latencyBreakdown", () => {
  it("uses directly measured non-overlapping phases", () => {
    expect(latencyBreakdown(metrics)).toEqual({
      total: 1_870.5,
      vad: 200,
      turnDetection: 40.4,
      asr: 52.1,
      agent: 739.9,
      speech: 838.1,
    });
  });
});

describe("usage formatting", () => {
  it("shows ASR billable and captured duration", () => {
    expect(
      formatAsrUsage({
        duration: 5,
        input_audio_seconds: 4.7665,
        output_characters: 18,
      }),
    ).toBe("Billed 5 s · Input Audio 4.77 s · 18 characters");
  });

  it("shows model input, output, and cached tokens", () => {
    expect(
      formatModelUsage({
        prompt_tokens: 6907,
        completion_tokens: 82,
        total_tokens: 6989,
        cached_tokens: 6656,
      }),
    ).toBe("Input 6907 · Output 82 · Cached 6656");
  });

  it("does not repeat equal TTS word and character counts", () => {
    expect(formatTtsUsage({ text_words: 11, input_characters: 11 })).toBe(
      "11 words",
    );
  });

  it("shows both TTS counts when they differ", () => {
    expect(formatTtsUsage({ text_words: 3, input_characters: 11 })).toBe(
      "3 words · 11 characters",
    );
  });
});
