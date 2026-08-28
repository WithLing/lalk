import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { EventLogEntry } from "../runtime/reducer";

const time = (timestamp: number) =>
  new Date(timestamp * 1_000).toLocaleTimeString([], { hour12: false });

export const EventsPanel = memo(function EventsPanel({
  logs,
  collapsed,
  onToggleCollapsed,
}: {
  logs: EventLogEntry[];
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const [filter, setFilter] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return query
      ? logs.filter((entry) => `${entry.type} ${entry.message}`.toLowerCase().includes(query))
      : logs;
  }, [filter, logs]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [logs]);

  return (
    <section className={`events-panel ${collapsed ? "collapsed" : ""}`}>
      <header>
        <h2>Events</h2>
        <label hidden={collapsed}><span>▽</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter" aria-label="Filter events" /></label>
        <button
          className="events-collapse-button"
          type="button"
          aria-label={collapsed ? "展开事件流" : "收起事件流"}
          aria-expanded={!collapsed}
          onClick={onToggleCollapsed}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 14 5-5 5 5" /></svg>
        </button>
      </header>
      <div className="event-list" ref={scrollRef} aria-live="polite" hidden={collapsed}>
        {filtered.map((entry) => (
          <div className="event-row" key={entry.id}>
            <time>{time(entry.timestamp)}</time>
            <strong>{entry.type}</strong>
            <span>{entry.message}</span>
          </div>
        ))}
      </div>
    </section>
  );
});
