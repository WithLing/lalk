import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG } from "./components/configuration/model";
import {
  applyAgentMode,
  captureGeneralMode,
  getAgentModePreset,
  loadGeneralModeSnapshot,
  loadStoredAgentMode,
  saveGeneralModeSnapshot,
  saveStoredAgentMode,
} from "./demo-agent-modes";
import type { AppConfig } from "./runtime/contracts";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

const generalConfig = (): AppConfig => ({
  ...DEFAULT_CONFIG,
  personalization_enabled: true,
  opening_enabled: false,
  inactivity_policy: {
    timeout_seconds: 30,
    max_followups: 1,
    on_exhausted: "wait",
  },
  bumblehive: {
    ...DEFAULT_CONFIG.bumblehive,
    provider: {
      type: "openai_chat_completions",
      model: "demo-model",
      api_key: "secret-key",
      base_url: "https://example.test/v1",
    },
    generation: {
      temperature: 0.3,
      reasoning_effort: "high",
      extra_body: {
        vendor_option: true,
        thinking: { type: "enabled", budget: 1024 },
      },
    },
    agent: {
      instructions: "这是原来的通用提示词。",
      dynamic_context: { company: "Lalk" },
      tool_names: ["weather"],
    },
  },
});

describe("demo agent modes", () => {
  it("exposes the same preset values used by the runtime and snapshot UI", () => {
    expect(getAgentModePreset("sales")).toMatchObject({
      label: "销售模式",
      thinkingEnabled: false,
      openingEnabled: true,
      backchannelFilterEnabled: true,
      personalizationEnabled: true,
    });
  });

  it("applies a sales preset without changing connection settings", () => {
    const current = generalConfig();
    const sales = applyAgentMode(current, "sales");

    expect(sales.personalization_enabled).toBe(true);
    expect(sales.opening_enabled).toBe(true);
    expect(sales.inactivity_policy).toEqual({
      timeout_seconds: 3,
      max_followups: 2,
      on_exhausted: "farewell",
    });
    expect(sales.bumblehive.provider).toEqual(current.bumblehive.provider);
    expect(sales.bumblehive.generation).toEqual({
      temperature: 0.3,
      extra_body: {
        vendor_option: true,
        thinking: { type: "disabled", budget: 1024 },
      },
    });
    expect(sales.interruption).toEqual({
      ...current.interruption,
      backchannel_filter_enabled: true,
    });
    expect(sales.bumblehive.agent).toMatchObject({
      dynamic_context: {
        客户公司: "XX银行",
        客户称呼: "陈经理",
        核心痛点: "账单日前后排队时间长、夜间服务能力不足、重复咨询占用大量人工",
      },
      tool_names: ["weather"],
    });
    const instructions = (sales.bumblehive.agent as Record<string, unknown>)
      .instructions as string;
    expect(instructions).not.toBe("这是原来的通用提示词。");
    expect(instructions).toContain("实时语音通话");
    expect(instructions).toContain("调用任何工具前");
    expect(instructions).toContain("只称自己为“智能助手”");
  });

  it("restores every general role field after switching presets", () => {
    const current = generalConfig();
    const snapshot = captureGeneralMode(current);
    const support = applyAgentMode(current, "support");
    const restored = applyAgentMode(support, "general", snapshot);

    expect(restored.personalization_enabled).toBe(current.personalization_enabled);
    expect(restored.opening_enabled).toBe(current.opening_enabled);
    expect(restored.inactivity_policy).toEqual(current.inactivity_policy);
    expect(restored.interruption).toEqual(current.interruption);
    expect(restored.bumblehive.generation).toEqual(current.bumblehive.generation);
    expect(restored.bumblehive.agent).toEqual(current.bumblehive.agent);
    expect(restored.bumblehive.provider).toEqual(current.bumblehive.provider);
  });

  it("persists the general snapshot and selected mode separately", () => {
    const storage = new MemoryStorage();
    const current = generalConfig();

    saveGeneralModeSnapshot(current, storage);
    saveStoredAgentMode("sales", storage);

    expect(loadGeneralModeSnapshot(storage)).toEqual(captureGeneralMode(current));
    expect(loadStoredAgentMode(storage)).toBe("sales");
  });

  it("can restore an earlier snapshot before the new controls were captured", () => {
    const current = generalConfig();
    const sales = applyAgentMode(current, "sales");
    const restored = applyAgentMode(sales, "general", {
      personalization_enabled: true,
      opening_enabled: false,
      inactivity_policy: null,
      agent: { instructions: "旧快照中的通用提示词" },
    });

    expect(restored.interruption).toEqual(sales.interruption);
    expect(restored.bumblehive.generation).toEqual(sales.bumblehive.generation);
    expect(restored.bumblehive.agent).toEqual({
      instructions: "旧快照中的通用提示词",
    });
  });
});
