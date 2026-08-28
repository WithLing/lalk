import { formatEvent } from "./event-format";
import type {
  AssistantPart,
  ComponentStatus,
  ConnectionState,
  InputGateState,
  LiveTranscript,
  ProactiveOffer,
  RuntimeError,
  RuntimeEventMessage,
  RuntimeSnapshot,
  RuntimeStage,
  RuntimeStatus,
  ToolPart,
  Turn,
  TurnMetrics,
  TurnState,
} from "./contracts";

export interface EventLogEntry {
  id: string;
  timestamp: number;
  type: string;
  message: string;
}

export interface RuntimeState {
  connection: ConnectionState;
  runtimeState: RuntimeStatus;
  stage: RuntimeStage;
  stageStartedAt: number | null;
  sessionId: string | null;
  sequence: number;
  components: Record<string, ComponentStatus>;
  inputLevel: number;
  inputGate: InputGateState | null;
  liveTranscript: LiveTranscript | null;
  turns: Turn[];
  error: RuntimeError | null;
  proactiveOffer: ProactiveOffer | null;
  clientError: string | null;
  logs: EventLogEntry[];
}

export const initialRuntimeState: RuntimeState = {
  connection: "connecting",
  runtimeState: "idle",
  stage: "idle",
  stageStartedAt: null,
  sessionId: null,
  sequence: 0,
  components: {},
  inputLevel: 0,
  inputGate: null,
  liveTranscript: null,
  turns: [],
  error: null,
  proactiveOffer: null,
  clientError: null,
  logs: [],
};

export type RuntimeAction =
  | { type: "connection"; connection: ConnectionState }
  | { type: "snapshot"; snapshot: RuntimeSnapshot }
  | { type: "event"; event: RuntimeEventMessage }
  | { type: "conversation.new" }
  | { type: "client.error"; message: string }
  | { type: "error.clear" };

const dataString = (data: Record<string, unknown>, key: string) =>
  String(data[key] ?? "");
const dataNumber = (data: Record<string, unknown>, key: string) =>
  Number(data[key]);

function appendLog(
  logs: EventLogEntry[],
  entry: EventLogEntry,
): EventLogEntry[] {
  const next = [...logs, entry];
  return next.length > 100 ? next.slice(next.length - 100) : next;
}

function shouldLog(event: RuntimeEventMessage): boolean {
  switch (event.type) {
    case "audio.input_level":
    case "assistant.text.delta":
      return false;
    case "transcript.update":
      return Boolean(event.data.is_final);
    case "component.state":
      return dataString(event.data, "state") !== "starting";
    case "turn.input":
      return dataString(event.data, "source") === "text";
    case "turn.state":
      return dataString(event.data, "state") !== "started";
    case "playback.state":
      return dataString(event.data, "state") !== "progress";
    default:
      return true;
  }
}

function updateTurn(
  turns: Turn[],
  sessionId: string,
  turnId: number,
  update: (turn: Turn) => Turn,
): Turn[] {
  return turns.map((turn) =>
    turn.turn_id === turnId && (!sessionId || turn.session_id === sessionId)
      ? update(turn)
      : turn,
  );
}

function updateRuntimeState(
  current: RuntimeStatus,
  event: RuntimeEventMessage,
): RuntimeStatus {
  if (event.type === "runtime.state") {
    return dataString(event.data, "state") as RuntimeStatus;
  }
  if (event.type !== "session.state") return current;
  const state = dataString(event.data, "state");
  if (state === "starting") return "starting";
  if (state === "ready") return "running";
  if (state === "stopping") return "stopping";
  if (state === "stopped") return "idle";
  return current;
}

function applyEvent(state: RuntimeState, event: RuntimeEventMessage): RuntimeState {
  if (event.seq <= state.sequence) return state;
  let turns = state.turns;
  let components = state.components;
  let inputLevel = state.inputLevel;
  let inputGate = state.inputGate;
  let liveTranscript = state.liveTranscript;
  let error = state.error;
  let proactiveOffer = state.proactiveOffer;
  const data = event.data;
  const turnId = data.turn_id == null ? null : dataNumber(data, "turn_id");
  const eventSessionId = dataString(data, "session_id");

  switch (event.type) {
    case "audio.input_level":
      inputLevel = dataNumber(data, "level");
      inputGate = data.gate_mode == null
        ? null
        : {
            level_db: dataNumber(data, "level_db"),
            noise_floor_db: data.noise_floor_db == null
              ? null
              : dataNumber(data, "noise_floor_db"),
            threshold_db: data.threshold_db == null
              ? null
              : dataNumber(data, "threshold_db"),
            mode: dataString(data, "gate_mode") as InputGateState["mode"],
            passed: Boolean(data.gate_passed),
          };
      break;
    case "session.state":
      if (dataString(data, "state") === "stopped") {
        inputLevel = 0;
        inputGate = null;
        liveTranscript = null;
      }
      break;
    case "speech.state":
      if (dataString(data, "state") === "started") liveTranscript = null;
      break;
    case "component.state": {
      const component = dataString(data, "component");
      components = {
        ...components,
        [component]: {
          state: dataString(data, "state") as ComponentStatus["state"],
          elapsed_ms:
            data.elapsed_ms == null ? null : dataNumber(data, "elapsed_ms"),
        },
      };
      break;
    }
    case "turn.input": {
      liveTranscript = null;
      const turn: Turn = {
        session_id: dataString(data, "session_id"),
        turn_id: turnId!,
        source: dataString(data, "source") as Turn["source"],
        user_text: dataString(data, "text"),
        state: "started",
        assistant: { parts: [], playback_state: null, spoken_text: "" },
        metrics: null,
        error: null,
      };
      turns = [...turns, turn];
      break;
    }
    case "transcript.update":
      liveTranscript = {
        text: dataString(data, "text"),
        is_final: Boolean(data.is_final),
        language: data.language == null ? null : dataString(data, "language"),
      };
      break;
    case "turn.state":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => ({
        ...turn,
        state: dataString(data, "state") as TurnState,
      }));
      break;
    case "assistant.text.delta":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => {
        const parts = [...turn.assistant.parts];
        const last = parts.at(-1);
        if (last?.type === "text") {
          parts[parts.length - 1] = {
            ...last,
            text: last.text + dataString(data, "delta"),
          };
        } else {
          parts.push({ type: "text", text: dataString(data, "delta") });
        }
        return { ...turn, assistant: { ...turn.assistant, parts } };
      });
      break;
    case "tool.started":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => ({
        ...turn,
        assistant: {
          ...turn.assistant,
          parts: [
            ...turn.assistant.parts,
            {
              type: "tool",
              call_id: dataString(data, "call_id"),
              name: dataString(data, "name"),
              arguments: (data.arguments ?? {}) as Record<string, unknown>,
              state: "running",
              result: null,
              elapsed_ms: null,
            },
          ],
        },
      }));
      break;
    case "tool.finished":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => ({
        ...turn,
        assistant: {
          ...turn.assistant,
          parts: turn.assistant.parts.map((part: AssistantPart) =>
            part.type === "tool" && part.call_id === data.call_id
              ? ({
                  ...part,
                  state: data.succeeded ? "succeeded" : "failed",
                  result: dataString(data, "result"),
                  elapsed_ms: dataNumber(data, "elapsed_ms"),
                  file_changes: Array.isArray(data.file_changes)
                    ? (data.file_changes as ToolPart["file_changes"])
                    : undefined,
                } satisfies ToolPart)
              : part,
          ),
        },
      }));
      break;
    case "playback.state":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => ({
        ...turn,
        assistant: {
          ...turn.assistant,
          playback_state: dataString(data, "state"),
          spoken_text: dataString(data, "spoken_text"),
        },
      }));
      break;
    case "turn.metrics":
      turns = updateTurn(turns, eventSessionId, turnId!, (turn) => ({
        ...turn,
        metrics: data.metrics as TurnMetrics,
      }));
      break;
    case "runtime.error": {
      const runtimeError: RuntimeError = {
        component: dataString(data, "component"),
        operation: dataString(data, "operation"),
        message: dataString(data, "message"),
        error_type: dataString(data, "error_type"),
        fatal: Boolean(data.fatal),
      };
      if (turnId == null) error = runtimeError;
      else {
        turns = updateTurn(turns, eventSessionId, turnId, (turn) => ({
          ...turn,
          error: runtimeError,
        }));
      }
      break;
    }
    case "proactive.offer":
      proactiveOffer = (data.offer ?? null) as ProactiveOffer | null;
      break;
  }

  const log = shouldLog(event)
    ? {
        id: String(event.seq),
        timestamp: event.timestamp ?? Date.now() / 1_000,
        type: event.type,
        message: formatEvent(event),
      }
    : null;
  return {
    ...state,
    runtimeState: updateRuntimeState(state.runtimeState, event),
    stage: event.stage,
    stageStartedAt: event.stage_started_at,
    sequence: event.seq,
    components,
    inputLevel,
    inputGate,
    liveTranscript,
    turns,
    error,
    proactiveOffer,
    clientError: null,
    logs: log === null ? state.logs : appendLog(state.logs, log),
  };
}

export function runtimeReducer(
  state: RuntimeState,
  action: RuntimeAction,
): RuntimeState {
  switch (action.type) {
    case "connection":
      return { ...state, connection: action.connection };
    case "snapshot":
      return {
        ...state,
        connection: "ready",
        runtimeState: action.snapshot.runtime_state,
        stage: action.snapshot.stage,
        stageStartedAt: action.snapshot.stage_started_at,
        sessionId: action.snapshot.session_id,
        sequence: action.snapshot.sequence,
        components: action.snapshot.components,
        inputLevel: action.snapshot.input_level,
        inputGate: action.snapshot.input_gate ?? null,
        liveTranscript: action.snapshot.live_transcript,
        turns: action.snapshot.turns,
        error: action.snapshot.error,
        proactiveOffer: action.snapshot.proactive_offer,
        clientError: null,
        logs: appendLog(state.logs, {
          id: `snapshot-${Date.now()}`,
          timestamp: Date.now() / 1_000,
          type: "snapshot",
          message: `Runtime synchronized · ${action.snapshot.turns.length} turns`,
        }),
      };
    case "event":
      return applyEvent(state, action.event);
    case "conversation.new":
      return { ...state, turns: [], liveTranscript: null };
    case "client.error":
      return { ...state, clientError: action.message };
    case "error.clear":
      return { ...state, clientError: null, error: null };
  }
}
