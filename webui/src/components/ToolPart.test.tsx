import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ToolPart as ToolPartData } from "../runtime/contracts";
import { parseUnifiedDiff, ToolPart } from "./ToolPart";

const unifiedDiff = [
  "--- sale_agent.md",
  "+++ sale_agent.md",
  "@@ -4,3 +4,3 @@",
  " 保持上下文",
  "-先介绍价格",
  "+先询问客户每年招聘多少人",
  " 继续上下文",
].join("\n");

describe("parseUnifiedDiff", () => {
  it("projects context, deleted, and added lines with their visible line numbers", () => {
    expect(parseUnifiedDiff(unifiedDiff)).toEqual([
      { kind: "context", lineNumber: 4, text: "保持上下文" },
      { kind: "deletion", lineNumber: 5, text: "先介绍价格" },
      { kind: "addition", lineNumber: 5, text: "先询问客户每年招聘多少人" },
      { kind: "context", lineNumber: 6, text: "继续上下文" },
    ]);
  });
});

describe("ToolPart mutation presentation", () => {
  it("renders a successful file edit as an expanded inline diff", () => {
    const part: ToolPartData = {
      type: "tool",
      call_id: "call-1",
      name: "apply_patch",
      arguments: {},
      state: "succeeded",
      result: '{"success":true}',
      elapsed_ms: 12,
      file_changes: [
        {
          path: "sale_agent.md",
          added: 1,
          deleted: 1,
          unified_diff: unifiedDiff,
        },
      ],
    };

    const markup = renderToStaticMarkup(createElement(ToolPart, { part }));

    expect(markup).toContain("已编辑文件");
    expect(markup).toContain("sale_agent.md · +1 −1");
    expect(markup).toContain("tool-diff-line deletion");
    expect(markup).toContain("tool-diff-line addition");
    expect(markup).toContain("先询问客户每年招聘多少人");
    expect(markup).not.toContain("Arguments");
  });

  it("shows read tools as a compact Bumblehive-style activity row", () => {
    const part: ToolPartData = {
      type: "tool",
      call_id: "call-2",
      name: "read_file",
      arguments: { path: "sale_agent.md" },
      state: "succeeded",
      result: "content",
      elapsed_ms: 8,
    };

    const markup = renderToStaticMarkup(createElement(ToolPart, { part }));

    expect(markup).toContain("read_file");
    expect(markup).toContain("已读取文件");
    expect(markup).toContain("sale_agent.md");
    expect(markup).not.toContain("Arguments");
    expect(markup).not.toContain("tool-diff-code");
  });

  it("keeps the technical name, arguments, and result for an unfamiliar tool", () => {
    const part: ToolPartData = {
      type: "tool",
      call_id: "call-3",
      name: "acme_connector",
      arguments: { account_id: 42 },
      state: "failed",
      result: '{"error":"connection refused"}',
      elapsed_ms: 18,
    };

    const markup = renderToStaticMarkup(createElement(ToolPart, { part }));

    expect(markup).toContain("已执行外部操作");
    expect(markup).toContain("acme_connector");
    expect(markup).toContain("account_id");
    expect(markup).toContain("connection refused");
  });
});
