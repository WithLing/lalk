import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentModeMenu } from "./AgentModeMenu";

describe("AgentModeMenu", () => {
  it("shows the current agent as a compact workbench control", () => {
    const markup = renderToStaticMarkup(
      <AgentModeMenu mode="support" pending={false} error={null} onChange={() => undefined} />,
    );

    expect(markup).toContain("客服模式");
    expect(markup).not.toContain("当前 Agent");
    expect(markup).not.toContain("选择 Agent 模式");
  });

  it("disables the trigger while a mode switch is pending", () => {
    const markup = renderToStaticMarkup(
      <AgentModeMenu mode="sales" pending error={null} onChange={() => undefined} />,
    );

    expect(markup).toContain("disabled");
    expect(markup).toContain("销售模式");
  });
});
