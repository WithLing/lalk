import { describe, expect, it } from "vitest";
import {
  DEFAULT_CONFIG,
  generationControlsFromConfig,
  mergeAgentPersonalization,
  mergeGenerationConfig,
  resourceIdForVoiceKind,
  voiceIdsFromSavedConfig,
  voiceKindFromResourceId,
} from "./model";

describe("default model configuration", () => {
  it("does not treat an example Base URL as a saved value", () => {
    expect(
      (DEFAULT_CONFIG.bumblehive.provider as Record<string, unknown>).base_url,
    ).toBe("");
  });

  it("keeps silence follow-up disabled without a second flag", () => {
    expect(DEFAULT_CONFIG.inactivity_policy).toBeNull();
  });

  it("keeps proactive opening disabled by default", () => {
    expect(DEFAULT_CONFIG.opening_enabled).toBe(false);
  });

  it("keeps false-interruption filtering enabled by default", () => {
    expect(DEFAULT_CONFIG.interruption).toEqual({
      backchannel_filter_enabled: true,
      backchannel_phrases: null,
    });
  });

  it("enables adaptive input-level gating without a hard floor", () => {
    expect(DEFAULT_CONFIG.vad.adaptive_input_level).toBe(true);
    expect(DEFAULT_CONFIG.vad.min_input_level).toBe(0);
  });

  it("uses semantic turn detection timing defaults", () => {
    expect(DEFAULT_CONFIG.vad.speech_end_ms).toBe(300);
    expect(DEFAULT_CONFIG.turn_detection.incomplete_timeout_ms).toBe(3000);
  });

  it("keeps personalization disabled and omits its content by default", () => {
    expect(DEFAULT_CONFIG.personalization_enabled).toBe(false);
    expect(DEFAULT_CONFIG.bumblehive.agent).toEqual({});
  });
});

describe("agent personalization", () => {
  it("writes personalization content when enabled", () => {
    expect(
      mergeAgentPersonalization(
        { tool_names: ["weather"] },
        true,
        "Be concise.",
        { company: "Lalk" },
      ),
    ).toEqual({
      tool_names: ["weather"],
      instructions: "Be concise.",
      dynamic_context: { company: "Lalk" },
    });
  });

  it("removes personalization content when disabled", () => {
    expect(
      mergeAgentPersonalization(
        {
          tool_names: ["weather"],
          instructions: "Old instructions",
          dynamic_context: { company: "Old company" },
        },
        false,
        "Unsaved instructions",
        { company: "Unsaved company" },
      ),
    ).toEqual({ tool_names: ["weather"] });
  });
});

describe("generation controls", () => {
  it("defaults thinking to enabled and leaves reasoning effort unset", () => {
    expect(generationControlsFromConfig({})).toEqual({
      thinkingEnabled: true,
      reasoningEffort: "",
    });
  });

  it("restores disabled thinking and a saved reasoning effort", () => {
    expect(
      generationControlsFromConfig({
        reasoning_effort: "high",
        extra_body: { thinking: { type: "disabled" } },
      }),
    ).toEqual({ thinkingEnabled: false, reasoningEffort: "high" });
  });

  it("writes thinking while preserving unrelated generation values", () => {
    expect(
      mergeGenerationConfig(
        {
          temperature: 0.2,
          extra_body: { vendor_flag: true, thinking: { budget: 2048 } },
        },
        { thinkingEnabled: true, reasoningEffort: "max" },
      ),
    ).toEqual({
      temperature: 0.2,
      reasoning_effort: "max",
      extra_body: {
        vendor_flag: true,
        thinking: { budget: 2048, type: "enabled" },
      },
    });
  });

  it("passes through a provider-specific reasoning effort", () => {
    expect(
      mergeGenerationConfig({}, {
        thinkingEnabled: true,
        reasoningEffort: "provider-balanced",
      }),
    ).toEqual({
      reasoning_effort: "provider-balanced",
      extra_body: { thinking: { type: "enabled" } },
    });
  });

  it("writes disabled and removes a blank reasoning effort", () => {
    expect(
      mergeGenerationConfig(
        {
          reasoning_effort: "low",
          extra_body: { thinking: { type: "enabled" } },
        },
        { thinkingEnabled: false, reasoningEffort: "  " },
      ),
    ).toEqual({
      extra_body: { thinking: { type: "disabled" } },
    });
  });

  it("does not send reasoning effort while thinking is disabled", () => {
    expect(
      mergeGenerationConfig({}, {
        thinkingEnabled: false,
        reasoningEffort: "provider-balanced",
      }),
    ).toEqual({
      extra_body: { thinking: { type: "disabled" } },
    });
  });
});

describe("voice resource selection", () => {
  it("uses the TTS service for platform voices", () => {
    expect(resourceIdForVoiceKind("platform")).toBe("seed-tts-2.0");
  });

  it("uses the clone service for cloned voices", () => {
    expect(resourceIdForVoiceKind("clone")).toBe("seed-icl-2.0");
  });

  it("restores the saved voice kind", () => {
    expect(voiceKindFromResourceId("seed-icl-2.0")).toBe("clone");
    expect(voiceKindFromResourceId("seed-tts-2.0")).toBe("platform");
  });

  it("does not copy a saved platform voice into the clone field", () => {
    expect(
      voiceIdsFromSavedConfig(
        "zh_female_vv_uranus_bigtts",
        "seed-tts-2.0",
      ),
    ).toEqual({
      platform: "zh_female_vv_uranus_bigtts",
      clone: "",
    });
  });

  it("does not copy a saved clone voice into the platform field", () => {
    expect(voiceIdsFromSavedConfig("S_Nxxxxxxxx", "seed-icl-2.0")).toEqual({
      platform: "",
      clone: "S_Nxxxxxxxx",
    });
  });
});
