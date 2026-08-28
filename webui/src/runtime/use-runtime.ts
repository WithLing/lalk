import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { RuntimeSocket } from "../api/runtime-socket";
import { initialRuntimeState, runtimeReducer } from "./reducer";

export function useRuntime() {
  const [state, dispatch] = useReducer(runtimeReducer, initialRuntimeState);
  const [pendingCommand, setPendingCommand] = useState<string | null>(null);
  const socketRef = useRef<RuntimeSocket | null>(null);

  useEffect(() => {
    const socket = new RuntimeSocket(
      (message) => {
        if (message.type === "snapshot") {
          dispatch({ type: "snapshot", snapshot: message.data });
        } else if (message.type === "stream.overflow") {
          dispatch({
            type: "client.error",
            message: "The runtime event stream overflowed; reconnecting…",
          });
        } else {
          dispatch({ type: "event", event: message });
        }
      },
      (connection) => dispatch({ type: "connection", connection }),
    );
    socketRef.current = socket;
    socket.connect();

    let disposed = false;
    let unlistenWindowHidden: (() => void) | undefined;
    void listen("lalk-window-hidden", () => {
      void socket.command({ type: "session.stop" }).catch(() => undefined);
    }).then((unlisten) => {
      if (disposed) unlisten();
      else unlistenWindowHidden = unlisten;
    }).catch(() => {
      // The web UI also runs in a regular browser during development.
    });

    return () => {
      disposed = true;
      unlistenWindowHidden?.();
      socket.close();
      socketRef.current = null;
    };
  }, []);

  const command = useCallback(
    async (
      name: string,
      input:
        | { type: "session.start" }
        | { type: "session.stop" }
        | { type: "turn.interrupt" }
        | { type: "turn.submit_text"; text: string }
        | { type: "conversation.new" }
        | { type: "proactive.answer"; request_id: string }
        | { type: "proactive.dismiss"; request_id: string }
        | { type: "proactive.snooze"; request_id: string; minutes: number },
    ) => {
      setPendingCommand(name);
      dispatch({ type: "error.clear" });
      try {
        return await socketRef.current!.command(input);
      } catch (error) {
        dispatch({
          type: "client.error",
          message: error instanceof Error ? error.message : "Runtime command failed",
        });
        throw error;
      } finally {
        setPendingCommand(null);
      }
    },
    [],
  );

  const start = useCallback(() => command("start", { type: "session.start" }), [command]);
  const stop = useCallback(() => command("stop", { type: "session.stop" }), [command]);
  const interrupt = useCallback(
    () => command("interrupt", { type: "turn.interrupt" }),
    [command],
  );
  const submitText = useCallback(
    (text: string) => command("submit", { type: "turn.submit_text", text }),
    [command],
  );
  const newConversation = useCallback(async () => {
    await command("new-conversation", { type: "conversation.new" });
    dispatch({ type: "conversation.new" });
  }, [command]);
  const answerProactive = useCallback(
    (requestId: string) => command(
      "proactive-answer",
      { type: "proactive.answer", request_id: requestId },
    ),
    [command],
  );
  const dismissProactive = useCallback(
    (requestId: string) => command(
      "proactive-dismiss",
      { type: "proactive.dismiss", request_id: requestId },
    ),
    [command],
  );
  const snoozeProactive = useCallback(
    (requestId: string, minutes: number) => command(
      "proactive-snooze",
      { type: "proactive.snooze", request_id: requestId, minutes },
    ),
    [command],
  );

  return {
    state,
    pendingCommand,
    start,
    stop,
    interrupt,
    submitText,
    newConversation,
    answerProactive,
    dismissProactive,
    snoozeProactive,
    clearError: () => dispatch({ type: "error.clear" }),
  };
}
