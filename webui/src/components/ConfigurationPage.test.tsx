import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_CONFIG } from "./configuration/model";

vi.stubGlobal("window", { __LALK_SERVER_URL__: undefined });

describe("ConfigurationPage navigation", () => {
  it("hides internal audio and turn-detection stages", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={DEFAULT_CONFIG}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).not.toContain("语音输入");
    expect(markup).not.toContain("轮次检测");
    expect(markup).not.toContain("VAD + Smart Turn");
    expect(markup).toContain("语音识别");
    expect(markup).toContain("智能体");
    expect(markup).toContain("语音合成");
  });

  it("shows a readable message for obsolete stored configuration", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={null}
        active={false}
        loadError="7 validation errors for AppConfig asr.provider"
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("现有配置来自旧版本");
    expect(markup).not.toContain("validation errors");
  });

  it("keeps the return action enabled while a voice session is active", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={DEFAULT_CONFIG}
        active
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    const returnButton = markup.match(
      /<button class="configuration-back"[^>]*>返回工作台<\/button>/,
    )?.[0];
    expect(returnButton).toBeDefined();
    expect(returnButton).not.toContain("disabled");
  });

  it("marks the ASR workspace ID as optional", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={null}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("Workspace ID");
    expect(markup).toContain("留空使用公共接口");
    expect(markup).toContain("留空时使用阿里云公共接口。");
  });

  it.each([false, true])("restores audio understanding as %s", async (enabled) => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={{ ...DEFAULT_CONFIG, send_audio_to_llm: enabled }}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("将原始语音一起发送给模型，辅助理解内容和情绪。需模型支持音频输入。");
    expect(markup).toContain(`role="switch" aria-checked="${enabled}"><span><strong>语音理解增强`);
    expect(markup.indexOf("语音理解增强")).toBeLessThan(markup.indexOf("思考模式"));
  });

  it("shows the proactive opening control disabled by default", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={DEFAULT_CONFIG}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("主动开启对话");
    expect(markup).toContain("开启语音后，Agent 会根据系统提示词主动开始对话");
    expect(markup).toMatch(/role="switch" aria-checked="false"[^>]*><span><strong>主动开启对话/);
  });

  it("shows the false-interruption filter enabled by default", async () => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={DEFAULT_CONFIG}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("误打断过滤");
    expect(markup).toContain("Agent 播放时，简短附和词不会中断播放");
    expect(markup).toMatch(/role="switch" aria-checked="true"[^>]*><span><strong>误打断过滤/);
  });

  it.each([false, true])("restores noise suppression as %s", async (enabled) => {
    const { ConfigurationPage } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationPage
        config={{
          ...DEFAULT_CONFIG,
          audio: { ...DEFAULT_CONFIG.audio, noise_suppression: enabled },
        }}
        active={false}
        loadError={null}
        loading={false}
        requestError={null}
        onBack={vi.fn()}
        onRetry={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(markup).toContain("降低麦克风中的背景噪声");
    expect(markup).toContain(`role="switch" aria-checked="${enabled}"><span><strong>增强降噪`);
  });

  it("renders an in-page confirmation instead of relying on a native dialog", async () => {
    const { ConfigurationLeaveDialog } = await import("./ConfigurationPage");
    const markup = renderToStaticMarkup(
      <ConfigurationLeaveDialog onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );

    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-modal="true"');
    expect(markup).toContain("继续编辑");
    expect(markup).toContain("放弃更改并返回");
    expect(markup).toContain("正在进行的语音对话不会中断");
  });
});
