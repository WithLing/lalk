import { useCallback, useEffect, useState } from "react";
import { brand } from "./brand";
import { ConfigurationPage } from "./components/ConfigurationPage";
import { ConversationPanel } from "./components/ConversationPanel";
import { EventsPanel } from "./components/EventsPanel";
import { MonitorPanel } from "./components/MonitorPanel";
import { ProactiveCall } from "./components/ProactiveCall";
import { TopBar } from "./components/TopBar";
import { VoicePage } from "./components/VoicePage";
import { isSessionActive } from "./runtime/status";
import { useConfiguration } from "./runtime/use-configuration";
import { useRuntime } from "./runtime/use-runtime";

type AppView = "voice" | "workbench" | "settings";

function WindowDragRegion() {
  return <div className="window-drag-region" data-tauri-drag-region aria-hidden="true" />;
}

function viewFromHash(): AppView {
  const value = window.location.hash.replace(/^#\/?/, "");
  if (value === "workbench" || value === "settings") return value;
  return "voice";
}

export default function App() {
  const runtime = useRuntime();
  const { state } = runtime;
  const configuration = useConfiguration(state.connection);
  const configResponse = configuration.response;
  const [view, setView] = useState<AppView>(viewFromHash);
  const [previousView, setPreviousView] = useState<Exclude<AppView, "settings">>("voice");
  const [eventsCollapsed, setEventsCollapsed] = useState(() => {
    const stored = localStorage.getItem("lalk-events-collapsed");
    return stored === null ? true : stored === "true";
  });
  const [monitorOpen, setMonitorOpen] = useState(() => {
    const stored = localStorage.getItem("lalk-monitor-open");
    return stored === null ? false : stored === "true";
  });
  const [dark, setDark] = useState(() => localStorage.getItem("lalk-theme") === "dark");
  useEffect(() => {
    if (!window.location.hash) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/voice`);
    }
    const updateView = () => setView(viewFromHash());
    window.addEventListener("hashchange", updateView);
    return () => window.removeEventListener("hashchange", updateView);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("lalk-theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    localStorage.setItem("lalk-events-collapsed", String(eventsCollapsed));
  }, [eventsCollapsed]);

  useEffect(() => {
    localStorage.setItem("lalk-monitor-open", String(monitorOpen));
  }, [monitorOpen]);

  useEffect(() => {
    if (configResponse?.config !== null) return;
    setPreviousView("voice");
    setView("settings");
    window.location.hash = "/settings";
  }, [configResponse]);

  const activeSession = isSessionActive(state.runtimeState);
  const proactiveBusy = activeSession && (
    state.runtimeState !== "running" || state.stage !== "listening"
  );
  const latestTurn = state.turns.at(-1);
  const interruptionSignal = latestTurn?.state === "interrupted"
    ? `${latestTurn.session_id}:${latestTurn.turn_id}`
    : null;

  const navigate = (next: AppView) => {
    setView(next);
    window.location.hash = `/${next}`;
  };

  const toggleEventsCollapsed = useCallback(() => {
    setEventsCollapsed((value) => !value);
  }, []);

  const openSettings = () => {
    setPreviousView(view === "workbench" ? "workbench" : "voice");
    navigate("settings");
  };

  const connect = () => {
    if (configResponse === null) return;
    if (!configResponse?.config) {
      openSettings();
      return;
    }
    if (activeSession) void runtime.stop().catch(() => undefined);
    else void runtime.start().catch(() => undefined);
  };

  const clearError = () => {
    runtime.clearError();
    configuration.clearResponseError();
  };

  const proactiveCall = state.proactiveOffer && (
    <ProactiveCall
      offer={state.proactiveOffer}
      busy={proactiveBusy}
      pending={runtime.pendingCommand !== null}
      onAnswer={() => {
        navigate("voice");
        void runtime.answerProactive(state.proactiveOffer!.id).catch(() => undefined);
      }}
      onDismiss={() => {
        void runtime.dismissProactive(state.proactiveOffer!.id).catch(() => undefined);
      }}
      onSnooze={() => {
        void runtime.snoozeProactive(state.proactiveOffer!.id, 10).catch(() => undefined);
      }}
    />
  );

  if (view === "settings") {
    return (
      <>
        <WindowDragRegion />
        <ConfigurationPage
          config={configResponse?.config ?? null}
          active={activeSession}
          loadError={configResponse?.error ?? null}
          loading={configuration.loading}
          requestError={configuration.requestError}
          backLabel={previousView === "voice" ? "返回语音" : "返回工作台"}
          onBack={() => navigate(previousView)}
          onRetry={configuration.retry}
          onSave={configuration.save}
        />
        {proactiveCall}
      </>
    );
  }

  if (view === "voice") {
    return (
      <>
        <WindowDragRegion />
        <VoicePage
          stage={state.stage}
          runtimeState={state.runtimeState}
          inputLevel={state.inputLevel}
          liveTranscript={state.liveTranscript}
          acceptedTranscript={latestTurn?.source === "voice" ? latestTurn.user_text : null}
          interruptionSignal={interruptionSignal}
          hasConversation={state.turns.length > 0}
          pending={runtime.pendingCommand !== null || configResponse === null}
          onToggleSession={connect}
          onNewConversation={runtime.newConversation}
          onOpenSettings={openSettings}
          onOpenWorkbench={() => navigate("workbench")}
        />
        {proactiveCall}
      </>
    );
  }

  return (
    <>
      <WindowDragRegion />
      <main className="app">
        <TopBar
          connection={state.connection}
          runtimeState={state.runtimeState}
          pending={runtime.pendingCommand !== null}
          hasConversation={state.turns.length > 0}
          dark={dark}
          monitorOpen={monitorOpen}
          onConnect={connect}
          onConfigure={openSettings}
          onOpenVoice={() => navigate("voice")}
          onToggleMonitor={() => setMonitorOpen((value) => !value)}
          onNewConversation={runtime.newConversation}
          onToggleTheme={() => setDark((value) => !value)}
        />

        <section className={`workspace ${eventsCollapsed ? "events-collapsed" : ""}`}>
          <div className={`main-grid ${monitorOpen ? "metrics-visible" : ""}`}>
            <ConversationPanel
              turns={state.turns}
              liveTranscript={state.liveTranscript}
              runtimeState={state.runtimeState}
              stage={state.stage}
              inputLevel={state.inputLevel}
              interruptionSignal={interruptionSignal}
              pendingCommand={runtime.pendingCommand}
              onSubmit={async (text) => { await runtime.submitText(text); }}
              onInterrupt={runtime.interrupt}
            />
            <aside className={`metrics-inspector ${monitorOpen ? "open" : ""}`} aria-hidden={!monitorOpen}>
              {monitorOpen && (
                <MonitorPanel
                  inputGate={state.inputGate}
                  stage={state.stage}
                  turns={state.turns}
                />
              )}
            </aside>
          </div>
          <div className="resize-handle horizontal" />
          <EventsPanel
            logs={state.logs}
            collapsed={eventsCollapsed}
            onToggleCollapsed={toggleEventsCollapsed}
          />
        </section>

        {(state.clientError || state.error || configResponse?.error) && (
          <aside className="error-toast" role="alert">
            <strong>{brand.displayName}</strong>
            <span>{state.clientError ?? state.error?.message ?? configResponse?.error}</span>
            <button className="error-toast-close" type="button" aria-label="关闭警告" onClick={clearError}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>
            </button>
          </aside>
        )}
      </main>
      {proactiveCall}
    </>
  );
}
