import type { AppConfig } from "../../runtime/contracts";

export type VoiceKind = "platform" | "clone";

export const resourceIdForVoiceKind = (kind: VoiceKind) =>
  kind === "clone" ? "seed-icl-2.0" : "seed-tts-2.0";

export const voiceKindFromResourceId = (resourceId: string): VoiceKind =>
  resourceId.startsWith("seed-icl-") ? "clone" : "platform";

export const voiceIdsFromSavedConfig = (voice: string, resourceId: string) => {
  const kind = voiceKindFromResourceId(resourceId);
  return {
    platform: kind === "platform" ? voice : "",
    clone: kind === "clone" ? voice : "",
  };
};

export interface ContextRow {
  id: string;
  name: string;
  value: string;
}

export interface GenerationControls {
  thinkingEnabled: boolean;
  reasoningEffort: string;
}

export const DEFAULT_CONFIG: AppConfig = {
  audio: {
    input_device: null,
    output_device: null,
    block_ms: 20,
    capture_buffer_ms: 500,
    latency: "low",
    echo_cancellation: "preferred",
  },
  vad: {
    threshold: 0.7,
    min_input_level: 0,
    adaptive_input_level: true,
    speech_start_ms: 200,
    speech_end_ms: 300,
  },
  turn_detection: {
    incomplete_timeout_ms: 3000,
  },
  interruption: {
    backchannel_filter_enabled: true,
    backchannel_phrases: null,
  },
  asr: {
    provider: "qwen_audio",
    settings: {
      api_key: "",
      workspace_id: "",
    },
  },
  bumblehive: {
    provider: {
      type: "openai_chat_completions",
      model: "",
      api_key: "",
      base_url: "",
    },
    generation: {},
    agent: {},
    runtime: {},
    mcp_servers: [],
  },
  personalization_enabled: false,
  opening_enabled: false,
  tts: {
    provider: "volcengine",
    settings: {
      api_key: "",
      voice: "",
      resource_id: "seed-tts-2.0",
      sample_rate: 48000,
    },
  },
  inactivity_policy: null,
};

export const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export const asText = (value: unknown) =>
  typeof value === "string" ? value : "";

export const generationControlsFromConfig = (
  generation: Record<string, unknown>,
): GenerationControls => {
  const extraBody = asObject(generation.extra_body);
  const thinking = asObject(extraBody.thinking);
  return {
    thinkingEnabled: asText(thinking.type) !== "disabled",
    reasoningEffort: asText(generation.reasoning_effort),
  };
};

export const mergeGenerationConfig = (
  generation: Record<string, unknown>,
  controls: GenerationControls,
): Record<string, unknown> => {
  const currentExtraBody = asObject(generation.extra_body);
  const currentThinking = asObject(currentExtraBody.thinking);
  const next: Record<string, unknown> = {
    ...generation,
    extra_body: {
      ...currentExtraBody,
      thinking: {
        ...currentThinking,
        type: controls.thinkingEnabled ? "enabled" : "disabled",
      },
    },
  };
  const reasoningEffort = controls.thinkingEnabled
    ? controls.reasoningEffort.trim()
    : "";
  if (reasoningEffort) {
    next.reasoning_effort = reasoningEffort;
  } else {
    delete next.reasoning_effort;
  }
  return next;
};

export const mergeAgentPersonalization = (
  agent: Record<string, unknown>,
  enabled: boolean,
  instructions: string,
  dynamicContext: Record<string, string>,
): Record<string, unknown> => {
  const next = { ...agent };
  if (enabled) {
    next.instructions = instructions;
    next.dynamic_context = dynamicContext;
  } else {
    delete next.instructions;
    delete next.dynamic_context;
  }
  return next;
};

export const createContextRows = (
  context: Record<string, unknown>,
): ContextRow[] => {
  const rows = Object.entries(context).map(([name, value]) => ({
    id: crypto.randomUUID(),
    name,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
  return rows.length
    ? rows
    : [{ id: crypto.randomUUID(), name: "", value: "" }];
};
