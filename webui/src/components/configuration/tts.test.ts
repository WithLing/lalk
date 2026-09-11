import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG } from "./model";
import { ttsConfig, ttsDrafts } from "./tts";

describe("TTS provider configuration", () => {
  it("keeps provider credentials and voice drafts separate", () => {
    const drafts = ttsDrafts(DEFAULT_CONFIG.tts);
    drafts.volcengine.apiKey = "volc-key";
    drafts.volcengine.platformVoiceId = "volc-voice";
    drafts.qwen_audio.apiKey = "qwen-key";
    drafts.qwen_audio.cloneVoiceId = "my-clone";
    drafts.qwen_audio.voiceKind = "clone";
    const qwen = ttsConfig("qwen_audio", drafts.qwen_audio);
    expect(qwen).toEqual({ provider: "qwen_audio", settings: {
      api_key: "qwen-key", workspace_id: "", voice: "my-clone",
      voice_kind: "clone", sample_rate: 48000,
    } });
    expect(ttsConfig("volcengine", drafts.volcengine).settings.api_key).toBe("volc-key");
    expect(ttsDrafts(qwen).qwen_audio.cloneVoiceId).toBe("my-clone");
    expect(ttsDrafts(qwen).qwen_audio.voiceKind).toBe("clone");
  });

  it("preserves an optional workspace and selected sample rate", () => {
    const draft = ttsDrafts(DEFAULT_CONFIG.tts).qwen_audio;
    draft.workspaceId = " workspace ";
    draft.sampleRate = 24000;
    const config = ttsConfig("qwen_audio", draft);
    expect(ttsDrafts(config).qwen_audio.workspaceId).toBe("workspace");
    expect(config.settings.sample_rate).toBe(24000);
    expect(config.settings).not.toHaveProperty("resource_id");
  });
});
