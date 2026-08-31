import type { AppConfig } from "./runtime/contracts";

export type AgentMode = "general" | "sales" | "support";
export type PresetAgentMode = Exclude<AgentMode, "general">;

export interface AgentModePreset {
  label: string;
  instructions: string;
  dynamicContext: Record<string, string>;
  thinkingEnabled: boolean;
  openingEnabled: boolean;
  backchannelFilterEnabled: boolean;
  personalizationEnabled: boolean;
  inactivityPolicy: NonNullable<AppConfig["inactivity_policy"]>;
}

export interface GeneralModeSnapshot {
  personalization_enabled: boolean;
  opening_enabled: boolean;
  inactivity_policy: AppConfig["inactivity_policy"];
  interruption?: AppConfig["interruption"];
  generation?: Record<string, unknown>;
  agent: Record<string, unknown>;
}

const GENERAL_MODE_SNAPSHOT_KEY = "lalk-general-mode-snapshot-v1";
const ACTIVE_MODE_KEY = "lalk-agent-mode-v1";

const VOICE_CONVERSATION_RULES = `实时语音规则：
- 你正在和用户进行实时语音通话，回复内容会直接交给语音合成播放。
- 自我介绍时只称自己为“智能助手”，不要介绍姓名、品牌、模型或技术实现，后续也不要重复自我介绍。
- 默认使用一句简短、自然的口语，通常控制在十五到三十五个汉字，非必要不超过五十个汉字。
- 复杂内容拆成多轮表达；每轮最多提出一个问题，讲解或排查时每轮最多给一到两步，然后等待用户回应。
- 不要输出 Markdown、标题、列表、表格、JSON、代码、括号动作、内部思考或不适合直接朗读的内容。
- 金额、日期、字母和数字应使用适合口语播放的表达，不要朗读动态上下文的字段名称。
- 用户表达不完整或语音识别结果存在歧义时，先用一句短话确认，不要自行猜测。
- 用户打断时立即回应最新内容，不要继续原来的长回答。

工具调用规则：
- 调用任何工具前，必须先用一句简短自然的话承接用户，并说明接下来要做什么，再执行工具调用。
- 不要向用户暴露工具名称、参数或内部流程，也不要在工具返回前声称操作已经成功。
- 工具成功后用简短口语说明关键结果；工具失败时如实说明暂未完成，并提供重试、替代方案或转人工。
- 查询类操作可以在承接后直接执行；预约、提交、冻结卡片等会改变状态的操作，必须先确认关键信息和用户意图。`;

const SALES_INSTRUCTIONS = `你是向银行销售客服 Voice Agent（语音智能体）解决方案的智能助手。
你的目标是结合银行客服场景和已知客户资料，自然了解需求，判断匹配场景，介绍最有价值的客服能力，并推动一个明确且不过度施压的下一步。

首次主动开场时说：“你好，我是智能助手，可以帮你了解语音智能体客服方案。你们现在更想改善高峰排队，还是夜间服务？”

销售要求：
- 动态上下文是已经掌握的客户资料，优先使用这些信息继续交流，不要重复询问；如果用户刚刚提供的信息与资料冲突，以用户最新表达为准。
- 每次只了解一个关键信息，优先确认咨询类型、话务规模、高峰排队、夜间服务、人工转接和决策时间。
- 只介绍与当前需求最匹配的一到两项能力，不要连续罗列全部卖点，也不要使用夸张或施压式表达。
- 可以介绍实时语音对话、自然打断、客户信息个性化、业务工具调用和人工转接，但不得编造未提供的能力、价格、客户案例或交付承诺。
- 用户提出异议时先确认顾虑，再针对该顾虑简短回应；无法确认的信息要明确说明需要进一步核实。
- 信息充分后，用一句话总结客户需求，再推动预约产品演示、确认试点场景或约定后续联系。
- 系统提示用户长时间未回应时，结合最近的话题做一次简短、自然的追问，不要重复完整问题。

${VOICE_CONVERSATION_RULES}`;

const SUPPORT_INSTRUCTIONS = `你是为银行信用卡客户提供服务的智能助手。
你的目标是结合已核验的客户与卡片信息，准确处理账单、还款、年费和卡片状态等咨询，并确认问题是否解决。

首次主动开场时说：“您好，我是智能助手，可以协助您处理信用卡业务。请问您需要查询账单，还是了解还款？”

客服要求：
- 动态上下文是当前会话可使用的模拟客户资料；优先使用已有信息，不要重复询问完整卡号或已经核验的内容。
- 每轮只处理一个问题，先说结论，再补充最必要的信息；需要排查时每轮最多给一到两步并等待反馈。
- 金额、日期、卡片状态和业务规则只能依据动态上下文或工具返回结果，不得自行推测或编造。
- 不得索要或复述完整卡号、密码、短信验证码、安全码等敏感信息，只能使用脱敏卡号。
- 不得承诺退款、调额、审批或争议处理结果；遇到盗刷、卡片遗失或争议交易时，优先引导用户冻结卡片或转人工处理。
- 用户提供的信息与资料不一致时，先简短确认；超出信用卡服务范围的问题，应说明可处理的范围并提供合适的下一步。
- 问题处理完成后，用一句话总结结果，并确认用户是否还需要其他帮助。
- 系统提示用户长时间未回应时，围绕当前业务做一次简短、自然的追问，不要重复播报敏感信息。

${VOICE_CONVERSATION_RULES}`;

const MODE_PRESETS: Record<PresetAgentMode, AgentModePreset> = {
  sales: {
    label: "销售模式",
    instructions: SALES_INSTRUCTIONS,
    dynamicContext: {
      客户称呼: "陈经理",
      客户公司: "XX银行",
      客户职位: "信用卡中心客服运营负责人",
      业务现状: "每月约八万通信用卡客户来电，目前由传统语音导航和人工客服承接",
      核心痛点: "账单日前后排队时间长、夜间服务能力不足、重复咨询占用大量人工",
      高频咨询: "账单查询、还款日期、年费规则、卡片状态和进度查询",
      重点关注能力: "自然打断、客户信息个性化、信用卡业务查询、工具调用和人工转接",
      建议下一步: "预约二十分钟产品演示，并以账单、还款和年费咨询作为首个试点场景",
    },
    thinkingEnabled: false,
    openingEnabled: true,
    backchannelFilterEnabled: true,
    personalizationEnabled: true,
    inactivityPolicy: {
      timeout_seconds: 3,
      max_followups: 2,
      on_exhausted: "farewell",
    },
  },
  support: {
    label: "客服模式",
    instructions: SUPPORT_INSTRUCTIONS,
    dynamicContext: {
      客户称呼: "李女士",
      身份核验状态: "已通过",
      信用卡信息: "尾号四八二六，卡片状态正常",
      本期账单: "三千二百八十六元四角",
      最低还款额: "三百二十八元六角四分",
      到期还款日: "九月二十六日",
      年费情况: "本年度已完成五次有效消费，完成六次可减免年费",
    },
    thinkingEnabled: false,
    openingEnabled: true,
    backchannelFilterEnabled: true,
    personalizationEnabled: true,
    inactivityPolicy: {
      timeout_seconds: 5,
      max_followups: 2,
      on_exhausted: "wait",
    },
  },
};

export function getAgentModePreset(mode: PresetAgentMode): AgentModePreset {
  return MODE_PRESETS[mode];
}

const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

const browserStorage = (): Storage | null =>
  typeof window === "undefined" ? null : window.localStorage;

function mergeThinkingMode(
  generation: Record<string, unknown>,
  enabled: boolean,
): Record<string, unknown> {
  const extraBody = asObject(generation.extra_body);
  const thinking = asObject(extraBody.thinking);
  const next: Record<string, unknown> = {
    ...generation,
    extra_body: {
      ...extraBody,
      thinking: {
        ...thinking,
        type: enabled ? "enabled" : "disabled",
      },
    },
  };
  if (!enabled) delete next.reasoning_effort;
  return next;
}

export function captureGeneralMode(config: AppConfig): GeneralModeSnapshot {
  return {
    personalization_enabled: config.personalization_enabled,
    opening_enabled: config.opening_enabled,
    inactivity_policy: config.inactivity_policy,
    interruption: { ...config.interruption },
    generation: { ...asObject(config.bumblehive.generation) },
    agent: { ...asObject(config.bumblehive.agent) },
  };
}

export function saveGeneralModeSnapshot(
  config: AppConfig,
  storage: Storage | null = browserStorage(),
): void {
  storage?.setItem(
    GENERAL_MODE_SNAPSHOT_KEY,
    JSON.stringify(captureGeneralMode(config)),
  );
}

export function loadGeneralModeSnapshot(
  storage: Storage | null = browserStorage(),
): GeneralModeSnapshot | null {
  const value = storage?.getItem(GENERAL_MODE_SNAPSHOT_KEY);
  if (!value) return null;
  try {
    return JSON.parse(value) as GeneralModeSnapshot;
  } catch {
    return null;
  }
}

export function loadStoredAgentMode(
  storage: Storage | null = browserStorage(),
): AgentMode {
  const value = storage?.getItem(ACTIVE_MODE_KEY);
  return value === "sales" || value === "support" ? value : "general";
}

export function saveStoredAgentMode(
  mode: AgentMode,
  storage: Storage | null = browserStorage(),
): void {
  storage?.setItem(ACTIVE_MODE_KEY, mode);
}

export function applyAgentMode(
  config: AppConfig,
  mode: AgentMode,
  generalSnapshot: GeneralModeSnapshot | null = null,
): AppConfig {
  if (mode === "general") {
    if (generalSnapshot === null) return config;
    return {
      ...config,
      personalization_enabled: generalSnapshot.personalization_enabled,
      opening_enabled: generalSnapshot.opening_enabled,
      inactivity_policy: generalSnapshot.inactivity_policy,
      interruption: generalSnapshot.interruption
        ? { ...generalSnapshot.interruption }
        : { ...config.interruption },
      bumblehive: {
        ...config.bumblehive,
        generation: generalSnapshot.generation
          ? { ...generalSnapshot.generation }
          : { ...asObject(config.bumblehive.generation) },
        agent: { ...generalSnapshot.agent },
      },
    };
  }

  const preset = MODE_PRESETS[mode];
  return {
    ...config,
    personalization_enabled: preset.personalizationEnabled,
    opening_enabled: preset.openingEnabled,
    inactivity_policy: { ...preset.inactivityPolicy },
    interruption: {
      ...config.interruption,
      backchannel_filter_enabled: preset.backchannelFilterEnabled,
    },
    bumblehive: {
      ...config.bumblehive,
      generation: mergeThinkingMode(
        asObject(config.bumblehive.generation),
        preset.thinkingEnabled,
      ),
      agent: {
        ...asObject(config.bumblehive.agent),
        instructions: preset.instructions,
        dynamic_context: { ...preset.dynamicContext },
      },
    },
  };
}
