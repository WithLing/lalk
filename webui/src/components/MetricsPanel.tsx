import type { Turn, TurnMetrics } from "../runtime/contracts";

const milliseconds = (value: number | null) =>
  value === null
    ? "—"
    : value >= 1_000
      ? `${(value / 1_000).toFixed(2)} s`
      : `${value.toFixed(0)} ms`;

const usage = (values: Record<string, number> | null, key: string) =>
  values?.[key] ?? null;

function MetricIcon({ type }: { type: "vad" | "turn" | "asr" | "agent" | "speech" }) {
  if (type === "vad") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h3l2-5 4 10 2-5h5" /></svg>;
  }
  if (type === "turn") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h8a4 4 0 0 1 4 4v6M15 14l3 3 3-3M9 10 6 7l3-3" /></svg>;
  }
  if (type === "asr") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8.5v7M9 5v14M13 8.5v7M17 6.5v11M21 10v4" /></svg>;
  }
  if (type === "agent") {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9L12 3ZM18.5 15l.7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h2M8 8v8M12 5v14M16 8v8M20 11v2" /></svg>;
}

export function formatModelUsage(values: Record<string, number> | null) {
  const items = [
    ["Input", usage(values, "prompt_tokens")],
    ["Output", usage(values, "completion_tokens")],
    ["Cached", usage(values, "cached_tokens")],
  ] as const;
  const visible = items.flatMap(([label, value]) =>
    value === null ? [] : [`${label} ${value}`],
  );
  return visible.length === 0 ? "—" : visible.join(" · ");
}

export function formatTtsUsage(values: Record<string, number> | null) {
  const words = usage(values, "text_words");
  const characters = usage(values, "input_characters");
  if (words === null && characters === null) return "—";
  if (words !== null && words === characters) return `${words} words`;
  return [
    words === null ? null : `${words} words`,
    characters === null ? null : `${characters} characters`,
  ]
    .filter((item): item is string => item !== null)
    .join(" · ");
}

export function formatAsrUsage(values: Record<string, number> | null) {
  const duration = usage(values, "duration");
  const audioSeconds = usage(values, "input_audio_seconds");
  const characters = usage(values, "output_characters");
  const items = [
    duration === null ? null : `Billed ${duration} s`,
    audioSeconds === null ? null : `Input Audio ${audioSeconds.toFixed(2)} s`,
    characters === null ? null : `${characters} characters`,
  ].filter((item): item is string => item !== null);
  return items.length === 0 ? "—" : items.join(" · ");
}

export function latencyBreakdown(metrics: TurnMetrics) {
  return {
    total: metrics.estimated_user_stop_to_first_playback_ms,
    vad: metrics.vad_confirmation_ms,
    turnDetection: metrics.turn_detection_ms,
    asr: metrics.asr_finalization_ms,
    agent: metrics.agent_first_token_ms,
    speech: metrics.speech_first_playback_ms,
  };
}

export function MetricsPanel({
  turns,
}: {
  turns: Turn[];
}) {
  const turn = [...turns]
    .reverse()
    .find(
      (item) =>
        item.source === "voice" &&
        item.metrics?.estimated_user_stop_to_first_playback_ms != null,
    );
  const metrics = turn?.metrics;
  if (!turn || !metrics) {
    return (
      <div className="metrics-empty">
        <strong>暂无语音指标</strong>
        <span>完成一轮语音对话后，这里会显示端到端延迟。</span>
      </div>
    );
  }

  const latency = latencyBreakdown(metrics);
  const phases = [
    ["vad", "VAD 停顿确认", latency.vad],
    ["turn", "轮次判断", latency.turnDetection],
    ["asr", "语音识别收尾", latency.asr],
    ["agent", "首个 Token", latency.agent],
    ["speech", "语音首帧", latency.speech],
  ] as const;

  return (
    <div className="metrics-view">
      <section className="metric-primary">
        <span>端到端首帧</span>
        <strong>{milliseconds(latency.total)}</strong>
      </section>

      <dl className="metric-phase-list">
        {phases.map(([type, label, value]) => (
          <div key={label}>
            <span className="metric-row-icon"><MetricIcon type={type} /></span>
            <dt>{label}</dt>
            <dd>{milliseconds(value)}</dd>
          </div>
        ))}
      </dl>

      <section className="metric-details">
        <header><span>最近一轮语音</span><strong>#{turn.turn_id}</strong></header>
        <dl>
          <div>
            <dt>语音识别</dt>
            <dd>{formatAsrUsage(metrics.asr_usage)}</dd>
          </div>
          <div>
            <dt>模型用量</dt>
            <dd>{formatModelUsage(metrics.llm_usage)}</dd>
          </div>
          <div>
            <dt>语音合成</dt>
            <dd>{formatTtsUsage(metrics.tts_usage)}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
