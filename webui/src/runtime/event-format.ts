import type { RuntimeEventMessage } from "./contracts";

const value = (data: Record<string, unknown>, key: string) => String(data[key] ?? "");
const milliseconds = (value: unknown) =>
  typeof value === "number" ? `${value.toFixed(1)} ms` : null;

const usageNumber = (usage: unknown, key: string) => {
  if (!usage || typeof usage !== "object" || Array.isArray(usage)) return null;
  const value = (usage as Record<string, unknown>)[key];
  return typeof value === "number" ? value : null;
};

const metricsSummary = (data: Record<string, unknown>) => {
  const metrics = data.metrics;
  if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) {
    return `Metrics finalized for turn ${value(data, "turn_id")}`;
  }
  const values = metrics as Record<string, unknown>;
  const parts = [`Turn ${value(data, "turn_id")}`];
  const modelOutput = usageNumber(values.llm_usage, "completion_tokens");
  const ttsWords = usageNumber(values.tts_usage, "text_words");
  const ttsCharacters = usageNumber(values.tts_usage, "input_characters");
  const audioBytes = usageNumber(values.tts_usage, "audio_bytes");
  const firstPlayback = milliseconds(values.estimated_user_stop_to_first_playback_ms);
  const total = milliseconds(values.turn_ms);

  if (modelOutput !== null) parts.push(`model output ${modelOutput} tokens`);
  if (ttsWords !== null) parts.push(`TTS ${ttsWords} words`);
  if (ttsCharacters !== null) parts.push(`${ttsCharacters} characters`);
  if (audioBytes !== null) parts.push(`${(audioBytes / 1_024).toFixed(1)} KiB audio`);
  if (firstPlayback !== null) parts.push(`first playback ${firstPlayback}`);
  if (total !== null) parts.push(`total ${total}`);
  return parts.join(" · ");
};

export function formatEvent(message: RuntimeEventMessage): string {
  const data = message.data;
  switch (message.type) {
    case "audio.input_level":
      return "Microphone input level updated";
    case "runtime.state":
      return `Runtime ${value(data, "state")}`;
    case "session.state":
      return `Session ${value(data, "state")}`;
    case "speech.state":
      return `User speech ${value(data, "state")}`;
    case "turn.state":
      return `Turn ${value(data, "turn_id")} ${value(data, "state")}`;
    case "synthesis.state": {
      const elapsed = milliseconds(data.elapsed_ms);
      return `Speech synthesis ${value(data, "state")}${elapsed ? ` · ${elapsed}` : ""}`;
    }
    case "playback.state":
      return `Playback ${value(data, "state")} · ${value(data, "spoken_text").length} characters heard`;
    case "component.state":
      return `${value(data, "component")} is ${value(data, "state")}${
        data.elapsed_ms == null ? "" : ` · ${Number(data.elapsed_ms).toFixed(1)} ms`
      }`;
    case "transcript.update":
      return `ASR ${data.is_final ? "final" : "interim"}${data.language ? ` (${value(data, "language")})` : ""}: ${value(data, "text")}`;
    case "turn.input":
      return `${value(data, "source")} input: ${value(data, "text")}`;
    case "agent.request":
      return `Agent request prepared · ${value(data, "message_count")} messages`;
    case "assistant.text.delta":
      return `Agent text generated · ${value(data, "delta").length} characters`;
    case "tool.started":
      return `${value(data, "name")} started`;
    case "tool.finished":
      return `${value(data, "name")} ${data.succeeded ? "succeeded" : "failed"} · ${Number(data.elapsed_ms ?? 0).toFixed(1)} ms`;
    case "turn.metrics":
      return metricsSummary(data);
    case "runtime.error":
      return `${value(data, "component")}.${value(data, "operation")}: ${value(data, "message")}`;
    case "proactive.offer": {
      const offer = data.offer as Record<string, unknown> | null;
      return offer ? `Proactive offer: ${value(offer, "title")}` : "Proactive offer cleared";
    }
  }
}
