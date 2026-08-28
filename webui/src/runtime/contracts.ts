export type ConnectionState =
  | "connecting"
  | "syncing"
  | "ready"
  | "disconnected";

export type RuntimeStatus =
  | "unconfigured"
  | "idle"
  | "starting"
  | "running"
  | "stopping"
  | "failed";

export type RuntimeStage =
  | RuntimeStatus
  | "listening"
  | "user_speaking"
  | "transcribing"
  | "thinking"
  | "tool_running"
  | "synthesizing"
  | "playing";

export type TurnState = "started" | "completed" | "interrupted" | "failed";
export type ToolState = "running" | "succeeded" | "failed";

export interface TextPart {
  type: "text";
  text: string;
}

export interface FileChange {
  path: string;
  added: number;
  deleted: number;
  unified_diff?: string;
  truncated?: boolean;
}

export interface ToolPart {
  type: "tool";
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  state: ToolState;
  result: string | null;
  elapsed_ms: number | null;
  file_changes?: FileChange[];
}

export type AssistantPart = TextPart | ToolPart;

export interface TurnMetrics {
  vad_confirmation_ms: number | null;
  turn_detection_ms: number | null;
  asr_finalization_ms: number | null;
  asr_audio_seconds: number | null;
  agent_request_preparation_ms: number | null;
  agent_first_token_ms: number | null;
  llm_first_token_ms: number | null;
  text_aggregation_ms: number | null;
  tts_first_audio_ms: number | null;
  vad_stop_to_tts_first_audio_ms: number | null;
  estimated_user_stop_to_first_playback_ms: number | null;
  speech_first_playback_ms: number | null;
  interruption_ms: number | null;
  turn_ms: number | null;
  asr_usage: Record<string, number> | null;
  llm_usage: Record<string, number> | null;
  tts_usage: Record<string, number> | null;
}

export interface RuntimeError {
  component?: string;
  operation?: string;
  message: string;
  error_type?: string;
  type?: string;
  fatal?: boolean;
}

export interface Turn {
  session_id: string;
  turn_id: number;
  source: "voice" | "text" | "opening" | "proactive" | "followup";
  user_text: string;
  state: TurnState;
  assistant: {
    parts: AssistantPart[];
    playback_state: string | null;
    spoken_text: string;
  };
  metrics: TurnMetrics | null;
  error: RuntimeError | null;
}

export interface ProactiveOffer {
  id: string;
  title: string;
  available_at: string;
  state: "offered";
}

export interface ComponentStatus {
  state: "starting" | "ready" | "failed";
  elapsed_ms: number | null;
}

export type InputGateMode = "bootstrap" | "normal" | "playback" | "speaking";

export interface InputGateState {
  level_db: number;
  noise_floor_db: number | null;
  threshold_db: number | null;
  mode: InputGateMode;
  passed: boolean;
}

export interface LiveTranscript {
  text: string;
  is_final: boolean;
  language: string | null;
}

export interface RuntimeSnapshot {
  runtime_state: RuntimeStatus;
  stage: RuntimeStage;
  stage_started_at: number | null;
  session_id: string | null;
  sequence: number;
  components: Record<string, ComponentStatus>;
  input_level: number;
  input_gate?: InputGateState | null;
  live_transcript: LiveTranscript | null;
  turns: Turn[];
  error: RuntimeError | null;
  proactive_offer: ProactiveOffer | null;
}

export interface SnapshotMessage {
  type: "snapshot";
  data: RuntimeSnapshot;
}

export interface RuntimeEventMessage {
  seq: number;
  type:
    | "runtime.state"
    | "session.state"
    | "component.state"
    | "audio.input_level"
    | "speech.state"
    | "transcript.update"
    | "turn.input"
    | "turn.state"
    | "agent.request"
    | "assistant.text.delta"
    | "tool.started"
    | "tool.finished"
    | "synthesis.state"
    | "playback.state"
    | "turn.metrics"
    | "runtime.error"
    | "proactive.offer";
  stage: RuntimeStage;
  stage_started_at: number | null;
  timestamp?: number;
  data: Record<string, unknown>;
}

export interface CommandResultMessage {
  type: "command.result";
  id: string;
  ok: boolean;
  data?: Record<string, unknown>;
  error?: { code: string; message: string };
}

export interface StreamOverflowMessage {
  type: "stream.overflow";
}

export type ServerMessage =
  | SnapshotMessage
  | RuntimeEventMessage
  | CommandResultMessage
  | StreamOverflowMessage;

export type RuntimeCommand =
  | { id: string; type: "session.start" }
  | { id: string; type: "session.stop" }
  | { id: string; type: "turn.interrupt" }
  | { id: string; type: "turn.submit_text"; text: string }
  | { id: string; type: "conversation.new" }
  | { id: string; type: "proactive.answer"; request_id: string }
  | { id: string; type: "proactive.dismiss"; request_id: string }
  | { id: string; type: "proactive.snooze"; request_id: string; minutes: number };

export interface AudioConfig {
  input_device: number | string | null;
  output_device: number | string | null;
  block_ms: number;
  capture_buffer_ms: number;
  latency: number | "low" | "high";
  echo_cancellation: "disabled" | "preferred" | "required";
}

export interface AppConfig {
  audio: AudioConfig;
  vad: {
    threshold: number;
    min_input_level: number;
    adaptive_input_level: boolean;
    speech_start_ms: number;
    speech_end_ms: number;
  };
  turn_detection: {
    incomplete_timeout_ms: number;
  };
  interruption: {
    backchannel_filter_enabled: boolean;
    backchannel_phrases: string[] | null;
  };
  asr: {
    provider: "qwen_audio";
    settings: {
      api_key: string;
      workspace_id: string;
    };
  };
  bumblehive: Record<string, unknown>;
  personalization_enabled: boolean;
  opening_enabled: boolean;
  tts: {
    provider: "volcengine";
    settings: {
      api_key: string;
      voice: string;
      resource_id: string;
      sample_rate: 8000 | 16000 | 22050 | 24000 | 32000 | 44100 | 48000;
    };
  };
  inactivity_policy: {
    timeout_seconds: number;
    max_followups: number;
    on_exhausted: "wait" | "stop" | "farewell";
  } | null;
}

export interface ConfigResponse {
  config: AppConfig | null;
  error: string | null;
}
