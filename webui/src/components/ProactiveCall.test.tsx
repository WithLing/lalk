import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ProactiveCall } from "./ProactiveCall";

const offer = {
  id: "request-id",
  title: "会议提醒",
  available_at: "2026-08-19T17:00:00+08:00",
  state: "offered" as const,
};

const handlers = {
  onAnswer: vi.fn(),
  onDismiss: vi.fn(),
  onSnooze: vi.fn(),
};

describe("ProactiveCall", () => {
  it("shows a compact notice without an answer action while the session is busy", () => {
    const markup = renderToStaticMarkup(
      <ProactiveCall offer={offer} busy pending={false} {...handlers} />,
    );

    expect(markup).toContain("proactive-busy-notice");
    expect(markup).toContain("当前对话结束后即可接听");
    expect(markup).not.toContain("proactive-backdrop");
    expect(markup).not.toContain(">接听</button>");
  });

  it("shows the incoming-call dialog when the session can answer", () => {
    const markup = renderToStaticMarkup(
      <ProactiveCall offer={offer} busy={false} pending={false} {...handlers} />,
    );

    expect(markup).toContain("proactive-backdrop");
    expect(markup).toContain(">接听</button>");
    expect(markup).not.toContain("proactive-busy-notice");
  });
});
