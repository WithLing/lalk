import type { AppConfig } from "../../runtime/contracts";
import { resourceIdForVoiceKind, voiceKindFromResourceId, type VoiceKind } from "./model";

export type TTSProvider = AppConfig["tts"]["provider"];
export interface TTSDraft {
  apiKey: string;
  workspaceId: string;
  voiceKind: VoiceKind;
  platformVoiceId: string;
  cloneVoiceId: string;
  sampleRate: AppConfig["tts"]["settings"]["sample_rate"];
}

export function ttsDrafts(config: AppConfig["tts"]): Record<TTSProvider, TTSDraft> {
  const empty = (): TTSDraft => ({ apiKey: "", workspaceId: "", voiceKind: "platform", platformVoiceId: "", cloneVoiceId: "", sampleRate: 48000 });
  const drafts = { volcengine: empty(), qwen_audio: { ...empty(), platformVoiceId: "longanhuan_v3.6" } };
  const kind = config.provider === "volcengine" ? voiceKindFromResourceId(config.settings.resource_id) : config.settings.voice_kind;
  drafts[config.provider] = {
    apiKey: config.settings.api_key,
    workspaceId: config.provider === "qwen_audio" ? config.settings.workspace_id : "",
    voiceKind: kind,
    platformVoiceId: kind === "platform" ? config.settings.voice : "",
    cloneVoiceId: kind === "clone" ? config.settings.voice : "",
    sampleRate: config.settings.sample_rate,
  };
  return drafts;
}

export function ttsConfig(provider: TTSProvider, draft: TTSDraft): AppConfig["tts"] {
  const common = {
    api_key: draft.apiKey.trim(),
    voice: (draft.voiceKind === "clone" ? draft.cloneVoiceId : draft.platformVoiceId).trim(),
  };
  if (provider === "qwen_audio") {
    return { provider, settings: { ...common, workspace_id: draft.workspaceId.trim(), voice_kind: draft.voiceKind, sample_rate: draft.sampleRate === 32000 ? 48000 : draft.sampleRate } };
  }
  return { provider, settings: { ...common, resource_id: resourceIdForVoiceKind(draft.voiceKind), sample_rate: draft.sampleRate } };
}
