import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface CloseDetails {
  code?: number;
  reason?: string;
}

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(): void {}

  close(): void {
    this.serverClose({ code: 1000 });
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  message(message: object): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(message) }));
  }

  serverClose({ code = 1006, reason = "" }: CloseDetails = {}): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code, reason }));
  }
}

describe("RuntimeSocket", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("window", globalThis);
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function createSocket() {
    const { RuntimeSocket } = await import("./runtime-socket");
    return new RuntimeSocket(vi.fn(), vi.fn());
  }

  it("keeps connect idempotent while a socket is active", async () => {
    const runtime = await createSocket();

    runtime.connect();
    runtime.connect();

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("ignores close callbacks from an obsolete socket", async () => {
    const runtime = await createSocket();
    runtime.connect();
    const first = FakeWebSocket.instances[0];
    first.serverClose();
    await vi.advanceTimersByTimeAsync(300);
    const second = FakeWebSocket.instances[1];
    second.open();

    first.serverClose();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("resets reconnect backoff only after receiving a snapshot", async () => {
    const runtime = await createSocket();
    runtime.connect();
    FakeWebSocket.instances[0].serverClose();
    await vi.advanceTimersByTimeAsync(300);

    const second = FakeWebSocket.instances[1];
    second.open();
    second.serverClose();
    await vi.advanceTimersByTimeAsync(599);
    expect(FakeWebSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);

    const third = FakeWebSocket.instances[2];
    third.open();
    third.message({ type: "snapshot", data: {} });
    third.serverClose();
    await vi.advanceTimersByTimeAsync(300);

    expect(FakeWebSocket.instances).toHaveLength(4);
  });

  it("retries an already-connected race once and then stops", async () => {
    const runtime = await createSocket();
    runtime.connect();
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].serverClose({
      code: 1008,
      reason: "Runtime WebSocket already connected",
    });
    await vi.advanceTimersByTimeAsync(1_000);

    FakeWebSocket.instances[1].open();
    FakeWebSocket.instances[1].serverClose({
      code: 1008,
      reason: "Runtime WebSocket already connected",
    });
    await vi.advanceTimersByTimeAsync(30_000);

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("does not retry permanent policy failures", async () => {
    const runtime = await createSocket();
    runtime.connect();
    FakeWebSocket.instances[0].serverClose({ code: 1008, reason: "Origin not allowed" });

    await vi.advanceTimersByTimeAsync(30_000);

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("does not reconnect after an explicit close", async () => {
    const runtime = await createSocket();
    runtime.connect();
    runtime.close();

    await vi.advanceTimersByTimeAsync(30_000);

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
