import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect } from "react";
import type { ProactiveOffer } from "../runtime/contracts";

function playRing(context: AudioContext): void {
  const startedAt = context.currentTime;
  for (const [offset, frequency] of [[0, 660], [0.22, 880]] as const) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, startedAt + offset);
    gain.gain.exponentialRampToValueAtTime(0.11, startedAt + offset + 0.025);
    gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + offset + 0.18);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(startedAt + offset);
    oscillator.stop(startedAt + offset + 0.2);
  }
}

export function ProactiveCall({
  offer,
  busy,
  pending,
  onAnswer,
  onDismiss,
  onSnooze,
}: {
  offer: ProactiveOffer;
  busy: boolean;
  pending: boolean;
  onAnswer: () => void;
  onDismiss: () => void;
  onSnooze: () => void;
}) {
  useEffect(() => {
    void (async () => {
      try {
        const appWindow = getCurrentWindow();
        await appWindow.show();
        await appWindow.setFocus();
      } catch {
        // The web UI also runs in a regular browser during development.
      }
    })();
  }, [offer.id]);

  useEffect(() => {
    if (busy) return;
    const context = new AudioContext();
    void context.resume().then(() => playRing(context)).catch(() => undefined);
    const interval = window.setInterval(() => playRing(context), 2_200);
    const stop = window.setTimeout(() => window.clearInterval(interval), 30_000);
    return () => {
      window.clearInterval(interval);
      window.clearTimeout(stop);
      void context.close();
    };
  }, [busy, offer.id]);

  if (busy) {
    return (
      <aside className="proactive-busy-notice" role="status" aria-labelledby="proactive-busy-title">
        <div>
          <p className="proactive-eyebrow">Voice Agent 稍后联系</p>
          <strong id="proactive-busy-title">{offer.title}</strong>
          <p>当前对话结束后即可接听</p>
        </div>
        <div className="proactive-busy-actions">
          <button type="button" disabled={pending} onClick={onDismiss}>忽略</button>
          <button type="button" disabled={pending} onClick={onSnooze}>10 分钟后</button>
        </div>
      </aside>
    );
  }

  return (
    <div className="proactive-backdrop" role="dialog" aria-modal="true" aria-labelledby="proactive-title">
      <section className="proactive-call-card">
        <div className="proactive-call-pulse" aria-hidden="true">
          <span />
          <svg viewBox="0 0 24 24"><path d="M8.4 3.8c.5-.2 1.1 0 1.4.5l1.5 3.2c.2.5.1 1-.3 1.4l-1.5 1.3a12.4 12.4 0 0 0 4.3 4.3l1.3-1.5c.4-.4.9-.5 1.4-.3l3.2 1.5c.5.3.7.9.5 1.4l-1 3.3c-.2.6-.7 1-1.3 1C10.3 19.9 4.1 13.7 4.1 6.1c0-.6.4-1.1 1-1.3l3.3-1Z" /></svg>
        </div>
        <p className="proactive-eyebrow">Voice Agent 正在联系你</p>
        <h2 id="proactive-title">{offer.title}</h2>
        <p className="proactive-status">接听后，Agent 会主动开始这次对话</p>
        <div className="proactive-actions">
          <button className="proactive-secondary" type="button" disabled={pending} onClick={onDismiss}>忽略</button>
          <button className="proactive-secondary" type="button" disabled={pending} onClick={onSnooze}>10 分钟后</button>
          <button className="proactive-answer" type="button" disabled={pending} onClick={onAnswer}>接听</button>
        </div>
      </section>
    </div>
  );
}
