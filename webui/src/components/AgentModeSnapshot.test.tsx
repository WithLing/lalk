import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AgentModeSnapshot } from "./AgentModeSnapshot";

describe("AgentModeSnapshot", () => {
  it("renders the exact sales preset as a read-only configuration reference", () => {
    const markup = renderToStaticMarkup(
      <AgentModeSnapshot mode="sales" onClose={() => undefined} />,
    );

    expect(markup).toContain("销售模式配置参考");
    expect(markup).toContain("思考模式");
    expect(markup).toContain("主动开启对话");
    expect(markup).toContain("误打断过滤");
    expect(markup).toContain("无响应时主动询问");
    expect(markup).toContain("3 秒");
    expect(markup).toContain("2 次");
    expect(markup).toContain("告别后关闭");
    expect(markup).toContain("向银行销售客服 Voice Agent");
    expect(markup).toContain("XX银行");
    expect(markup).toContain("调用任何工具前");
    expect(markup).toContain("只读参考");
    expect(markup).toContain("readOnly");
  });

  it("renders support values from the support preset", () => {
    const markup = renderToStaticMarkup(
      <AgentModeSnapshot mode="support" onClose={() => undefined} />,
    );

    expect(markup).toContain("客服模式配置参考");
    expect(markup).toContain("5 秒");
    expect(markup).toContain("继续聆听");
    expect(markup).toContain("银行信用卡客户");
    expect(markup).toContain("尾号四八二六");
    expect(markup).toContain("只称自己为“智能助手”");
  });
});
