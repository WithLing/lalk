import { describe, expect, it } from "vitest";
import type { ToolPart } from "../runtime/contracts";
import { getToolPresentation, isKnownTool } from "./tool-presentation";

function tool(name: string, argumentsValue: Record<string, unknown>): ToolPart {
  return {
    type: "tool",
    call_id: "call-1",
    name,
    arguments: argumentsValue,
    state: "succeeded",
    result: "{}",
    elapsed_ms: 12.5,
  };
}

describe("getToolPresentation", () => {
  it("uses explicit user-facing copy for built-in tools", () => {
    const presentation = getToolPresentation(tool("read_file", { path: "销售配置.md" }));

    expect(presentation).toMatchObject({
      label: "已读取文件",
      summary: "销售配置.md",
      duration: "12.5 ms",
      technicalName: "read_file",
    });
    expect(isKnownTool("read_file")).toBe(true);
  });

  it("infers a neutral action for an unfamiliar tool with a recognizable verb", () => {
    const presentation = getToolPresentation(
      tool("crm_search_contacts", { query: "上海客户" }),
    );

    expect(presentation.label).toBe("已搜索信息");
    expect(presentation.summary).toBe("上海客户");
    expect(presentation.technicalName).toBe("crm_search_contacts");
    expect(isKnownTool("crm_search_contacts")).toBe(false);
  });

  it("falls back without inventing semantics for an unknown tool name", () => {
    const presentation = getToolPresentation(
      tool("acme_connector", { account_id: 42 }),
    );

    expect(presentation.label).toBe("已完成外部操作");
    expect(presentation.summary).toBe("account_id: 42");
    expect(presentation.technicalName).toBe("acme_connector");
  });
});
