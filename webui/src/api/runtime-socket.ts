import { SERVER_WS_URL } from "./endpoint";
import type {
  CommandResultMessage,
  RuntimeCommand,
  ServerMessage,
} from "../runtime/contracts";

type RuntimePushMessage = Exclude<ServerMessage, CommandResultMessage>;

type CommandInput =
  | { type: "session.start" }
  | { type: "session.stop" }
  | { type: "turn.interrupt" }
  | { type: "turn.submit_text"; text: string }
  | { type: "conversation.new" }
  | { type: "proactive.answer"; request_id: string }
  | { type: "proactive.dismiss"; request_id: string }
  | { type: "proactive.snooze"; request_id: string; minutes: number };

interface PendingCommand {
  resolve: (result: CommandResultMessage) => void;
  reject: (error: Error) => void;
}

const MAX_RECONNECT_DELAY_MS = 3_000;
const ALREADY_CONNECTED_RETRY_DELAY_MS = 1_000;

export class RuntimeSocket {
  private socket: WebSocket | null = null;
  private stopped = false;
  private retry = 0;
  private alreadyConnectedRetries = 0;
  private generation = 0;
  private commandSequence = 0;
  private reconnectTimer: number | null = null;
  private readonly pending = new Map<string, PendingCommand>();

  constructor(
    private readonly onMessage: (message: RuntimePushMessage) => void,
    private readonly onConnection: (
      state: "connecting" | "syncing" | "disconnected",
    ) => void,
  ) {}

  connect(): void {
    if (this.socket !== null || this.reconnectTimer !== null) return;
    this.stopped = false;
    this.open();
  }

  close(): void {
    this.stopped = true;
    this.generation += 1;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.rejectPending("Runtime connection closed");
  }

  command(input: CommandInput): Promise<CommandResultMessage> {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("Lalk Server is not connected"));
    }
    const id = `${Date.now()}-${++this.commandSequence}`;
    const command = { ...input, id } as RuntimeCommand;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket!.send(JSON.stringify(command));
    });
  }

  private open(): void {
    if (this.stopped || this.socket !== null) return;
    this.onConnection("connecting");
    const socket = new WebSocket(`${SERVER_WS_URL}/ws`);
    const generation = ++this.generation;
    this.socket = socket;

    socket.onopen = () => {
      if (!this.isCurrent(socket, generation)) return;
      this.onConnection("syncing");
    };
    socket.onmessage = ({ data }) => {
      if (!this.isCurrent(socket, generation)) return;
      const message = JSON.parse(String(data)) as ServerMessage;
      if (message.type === "snapshot") {
        this.retry = 0;
        this.alreadyConnectedRetries = 0;
      }
      if (message.type === "command.result") {
        const pending = this.pending.get(message.id);
        if (pending) {
          this.pending.delete(message.id);
          if (message.ok) pending.resolve(message);
          else pending.reject(new Error(message.error?.message ?? "Command failed"));
        }
        return;
      }
      this.onMessage(message);
    };
    socket.onclose = (event) => {
      if (!this.isCurrent(socket, generation)) return;
      this.socket = null;
      this.rejectPending("Runtime connection closed");
      this.onConnection("disconnected");
      if (this.stopped) return;
      if (event.code === 1008) {
        if (event.reason !== "Runtime WebSocket already connected") return;
        if (this.alreadyConnectedRetries++ > 0) return;
        this.scheduleReconnect(ALREADY_CONNECTED_RETRY_DELAY_MS);
        return;
      }
      const delay = Math.min(300 * 2 ** this.retry++, MAX_RECONNECT_DELAY_MS);
      this.scheduleReconnect(delay);
    };
  }

  private isCurrent(socket: WebSocket, generation: number): boolean {
    return this.socket === socket && this.generation === generation;
  }

  private scheduleReconnect(delay: number): void {
    if (this.stopped || this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  private rejectPending(message: string): void {
    for (const command of this.pending.values()) command.reject(new Error(message));
    this.pending.clear();
  }
}
