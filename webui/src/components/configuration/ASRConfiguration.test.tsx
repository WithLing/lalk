import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  ASRConfiguration, asrDrafts, buildASRConfig, DEFAULT_ASR_RESOURCE,
} from "./ASRConfiguration";

describe("ASR configuration", () => {
  it("keeps a saved collapse preference despite a configured workspace", () => {
    const getItem = vi.fn(() => "false");
    vi.stubGlobal("localStorage", { getItem });
    try {
      const markup = renderToStaticMarkup(
        <ASRConfiguration provider="qwen_audio"
          drafts={asrDrafts({ provider: "qwen_audio",
            settings: { api_key: "", workspace_id: "configured-workspace" } })}
          disabled={false} onProviderChange={vi.fn()} onChange={vi.fn()}>
          <button>保存更改</button>
        </ASRConfiguration>,
      );
      expect(getItem).toHaveBeenCalledWith("lalk-asr-advanced-qwen_audio");
      expect(markup).not.toContain('<details class="asr-advanced" open');
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("keeps provider drafts separate and only saves the selected provider", () => {
    const drafts = asrDrafts({
      provider: "qwen_audio", settings: { api_key: "ali-key", workspace_id: "workspace" },
    });
    drafts.volcengine.api_key = " volcano-key ";
    expect(buildASRConfig("volcengine", drafts)).toEqual({
      provider: "volcengine",
      settings: { api_key: "volcano-key", resource_id: DEFAULT_ASR_RESOURCE },
    });
    expect(buildASRConfig("qwen_audio", drafts).settings.api_key).toBe("ali-key");
  });

  it("restores saved volcano settings and defaults an empty resource", () => {
    const drafts = asrDrafts({
      provider: "volcengine", settings: { api_key: "key", resource_id: "custom" },
    });
    expect(drafts.volcengine.resource_id).toBe("custom");
    expect(drafts.qwen_audio.api_key).toBe("");
    drafts.volcengine.resource_id = " ";
    expect(buildASRConfig("volcengine", drafts).settings).toEqual({
      api_key: "key", resource_id: DEFAULT_ASR_RESOURCE,
    });
  });

  it.each(["qwen_audio", "volcengine"] as const)("shows %s model and fields", (provider) => {
    const markup = renderToStaticMarkup(
      <ASRConfiguration provider={provider}
        drafts={asrDrafts({ provider: "qwen_audio", settings: { api_key: "", workspace_id: "" } })}
        disabled={false} onProviderChange={vi.fn()} onChange={vi.fn()}>
        <button>保存更改</button>
      </ASRConfiguration>,
    );
    expect(markup).toContain("识别模型");
    expect(markup).toContain(provider === "volcengine"
      ? "豆包流式语音识别模型2.0" : "qwen-audio-3.0-asr-flash-streaming");
    expect(markup).toContain(provider === "volcengine" ? "Resource ID" : "Workspace ID");
    expect(markup).not.toContain("<details class=\"asr-advanced\" open");
    expect(markup).toContain('aria-pressed="true"');
  });
});
