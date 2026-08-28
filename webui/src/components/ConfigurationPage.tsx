import { useEffect, useMemo, useRef, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import volcengineLogo from "../assets/volcengine-logo.png";
import { getModels } from "../api/http";
import type { AppConfig } from "../runtime/contracts";
import { ConfigurationHeader } from "./configuration/ConfigurationHeader";
import {
  asObject,
  asText,
  createContextRows,
  DEFAULT_CONFIG,
  generationControlsFromConfig,
  mergeAgentPersonalization,
  mergeGenerationConfig,
  resourceIdForVoiceKind,
  type VoiceKind,
  voiceIdsFromSavedConfig,
  voiceKindFromResourceId,
} from "./configuration/model";

type Step = "asr" | "agent" | "tts";
type SaveState = "idle" | "saving" | "saved";

const VOICE_LIBRARY_URL =
  "https://console.volcengine.com/speech/new/voices?_vtm_=a441938.b921646.c67268_0.d65110_0.0.143_7665551159285597696&projectName=default";
const INVALID_STORED_CONFIG_MESSAGE =
  "现有配置来自旧版本，请重新填写当前版本的配置后保存。";

const readableLoadError = (message: string | null) =>
  message ? INVALID_STORED_CONFIG_MESSAGE : "";

export function ConfigurationPage({
  config,
  active,
  loadError,
  loading,
  requestError,
  backLabel = "返回工作台",
  onBack,
  onRetry,
  onSave,
}: {
  config: AppConfig | null;
  active: boolean;
  loadError: string | null;
  loading: boolean;
  requestError: string | null;
  backLabel?: string;
  onBack: () => void;
  onRetry: () => void;
  onSave: (config: AppConfig) => Promise<void>;
}) {
  const base = useMemo(() => structuredClone(config ?? DEFAULT_CONFIG), [config]);
  const providerConfig = asObject(base.bumblehive.provider);
  const agentConfig = asObject(base.bumblehive.agent);
  const generationConfig = asObject(base.bumblehive.generation);
  const initialGeneration = generationControlsFromConfig(generationConfig);

  const [step, setStep] = useState<Step>(config ? "agent" : "asr");
  const [instructions, setInstructions] = useState(asText(agentConfig.instructions));
  const [rows, setRows] = useState(() =>
    createContextRows(asObject(agentConfig.dynamic_context)),
  );
  const [agentBaseUrl, setAgentBaseUrl] = useState(asText(providerConfig.base_url));
  const [agentModel, setAgentModel] = useState(asText(providerConfig.model));
  const [agentApiKey, setAgentApiKey] = useState(asText(providerConfig.api_key));
  const [asrApiKey, setAsrApiKey] = useState(base.asr.settings.api_key);
  const [asrWorkspaceId, setAsrWorkspaceId] = useState(
    base.asr.settings.workspace_id,
  );
  const [thinkingEnabled, setThinkingEnabled] = useState(
    initialGeneration.thinkingEnabled,
  );
  const [reasoningEffort, setReasoningEffort] = useState(
    initialGeneration.reasoningEffort,
  );
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState("");
  const [personalizationEnabled, setPersonalizationEnabled] = useState(
    base.personalization_enabled,
  );
  const [openingEnabled, setOpeningEnabled] = useState(base.opening_enabled);
  const [backchannelFilterEnabled, setBackchannelFilterEnabled] = useState(
    base.interruption.backchannel_filter_enabled,
  );
  const [followupEnabled, setFollowupEnabled] = useState(
    base.inactivity_policy !== null,
  );
  const [followupTimeout, setFollowupTimeout] = useState(
    String(base.inactivity_policy?.timeout_seconds ?? 3),
  );
  const [maximumFollowups, setMaximumFollowups] = useState(
    String(base.inactivity_policy?.max_followups ?? 3),
  );
  const [exhaustedAction, setExhaustedAction] = useState<
    "wait" | "stop" | "farewell"
  >(
    base.inactivity_policy?.on_exhausted ?? "wait",
  );
  const [ttsSelected, setTtsSelected] = useState(config?.tts.provider === "volcengine");
  const [ttsApiKey, setTtsApiKey] = useState(base.tts.settings.api_key);
  const [voiceKind, setVoiceKind] = useState<VoiceKind>(() =>
    voiceKindFromResourceId(base.tts.settings.resource_id),
  );
  const [platformVoiceId, setPlatformVoiceId] = useState(() =>
    voiceIdsFromSavedConfig(
      base.tts.settings.voice,
      base.tts.settings.resource_id,
    ).platform,
  );
  const [cloneVoiceId, setCloneVoiceId] = useState(() =>
    voiceIdsFromSavedConfig(
      base.tts.settings.voice,
      base.tts.settings.resource_id,
    ).clone,
  );
  const [error, setError] = useState(readableLoadError(loadError));
  const [dirty, setDirty] = useState(false);
  const [leaveConfirmationOpen, setLeaveConfirmationOpen] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const saveNoticeTimerRef = useRef<number | null>(null);
  const agentReady = Boolean(
    agentBaseUrl.trim() && agentModel.trim() && agentApiKey.trim(),
  );
  const asrReady = Boolean(asrApiKey.trim());
  const voiceId = voiceKind === "clone" ? cloneVoiceId : platformVoiceId;
  const ttsReady = Boolean(ttsSelected && ttsApiKey.trim() && voiceId.trim());
  const followupTimeoutValue = Number(followupTimeout);
  const maximumFollowupsValue = Number(maximumFollowups);
  const followupError = followupEnabled
    ? !Number.isFinite(followupTimeoutValue) || followupTimeoutValue <= 0
      ? "询问间隔必须大于 0 秒。"
      : !Number.isInteger(maximumFollowupsValue) || maximumFollowupsValue <= 0
        ? "最多询问次数必须是大于 0 的整数。"
        : ""
    : "";

  useEffect(() => {
    if (!config) return;
    const stored = structuredClone(config);
    const storedProvider = asObject(stored.bumblehive.provider);
    const storedAgent = asObject(stored.bumblehive.agent);
    const storedGeneration = generationControlsFromConfig(
      asObject(stored.bumblehive.generation),
    );
    const storedBaseUrl = asText(storedProvider.base_url);
    const storedModel = asText(storedProvider.model);
    const storedAgentApiKey = asText(storedProvider.api_key);
    const storedTtsApiKey = stored.tts.settings.api_key;
    const storedVoiceId = stored.tts.settings.voice;
    const storedVoiceKind = voiceKindFromResourceId(
      stored.tts.settings.resource_id,
    );
    const storedVoiceIds = voiceIdsFromSavedConfig(
      storedVoiceId,
      stored.tts.settings.resource_id,
    );

    setInstructions(asText(storedAgent.instructions));
    setRows(createContextRows(asObject(storedAgent.dynamic_context)));
    setAgentBaseUrl(storedBaseUrl);
    setAgentModel(storedModel);
    setAgentApiKey(storedAgentApiKey);
    setAsrApiKey(stored.asr.settings.api_key);
    setAsrWorkspaceId(stored.asr.settings.workspace_id);
    setThinkingEnabled(storedGeneration.thinkingEnabled);
    setReasoningEffort(storedGeneration.reasoningEffort);
    setPersonalizationEnabled(stored.personalization_enabled);
    setOpeningEnabled(stored.opening_enabled);
    setBackchannelFilterEnabled(
      stored.interruption.backchannel_filter_enabled,
    );
    setFollowupEnabled(stored.inactivity_policy !== null);
    setFollowupTimeout(
      String(stored.inactivity_policy?.timeout_seconds ?? 3),
    );
    setMaximumFollowups(
      String(stored.inactivity_policy?.max_followups ?? 3),
    );
    setExhaustedAction(stored.inactivity_policy?.on_exhausted ?? "wait");
    setTtsSelected(stored.tts.provider === "volcengine");
    setTtsApiKey(storedTtsApiKey);
    setVoiceKind(storedVoiceKind);
    setPlatformVoiceId(storedVoiceIds.platform);
    setCloneVoiceId(storedVoiceIds.clone);
    setDirty(false);
    setLeaveConfirmationOpen(false);
  }, [config]);

  useEffect(() => {
    if (loadError) setError(readableLoadError(loadError));
  }, [loadError]);

  useEffect(() => () => {
    if (saveNoticeTimerRef.current !== null) {
      window.clearTimeout(saveNoticeTimerRef.current);
    }
  }, []);

  const handleBack = () => {
    if (dirty) {
      setLeaveConfirmationOpen(true);
      return;
    }
    onBack();
  };

  const discardAndLeave = () => {
    setLeaveConfirmationOpen(false);
    onBack();
  };

  if (loading || requestError) {
    return (
      <main className="configuration-page">
        <div className="configuration-scroll">
          <section className="configuration-shell">
            <ConfigurationHeader backLabel={backLabel} onBack={handleBack} />
            <section className={`configuration-load-state ${requestError ? "failed" : ""}`}>
              {loading && <i className="model-spinner" aria-hidden="true" />}
              <strong>{loading ? "正在读取已保存的配置" : "暂时无法读取配置"}</strong>
              <p>
                {loading
                  ? "正在等待本地服务连接，读取完成后会自动填入，无需重新配置。"
                  : requestError}
              </p>
              {requestError && (
                <button type="button" onClick={onRetry}>重新读取</button>
              )}
            </section>
          </section>
        </div>
      </main>
    );
  }

  const selectableModels = Array.from(
    new Set([agentModel, ...modelOptions].filter(Boolean)),
  );
  const visibleModels = selectableModels.filter((model) =>
    model.toLowerCase().includes(modelSearch.trim().toLowerCase()),
  );
  const manualModel = modelSearch.trim();
  const hasExactModel = selectableModels.some(
    (model) => model.toLowerCase() === manualModel.toLowerCase(),
  );

  const markDirty = () => {
    if (saveNoticeTimerRef.current !== null) {
      window.clearTimeout(saveNoticeTimerRef.current);
      saveNoticeTimerRef.current = null;
    }
    setDirty(true);
    setSaveState("idle");
    setError("");
  };

  const changeAgent = (change: () => void) => {
    change();
    markDirty();
  };

  const updateRow = (id: string, field: "name" | "value", value: string) => {
    setRows((current) =>
      current.map((row) => (row.id === id ? { ...row, [field]: value } : row)),
    );
    markDirty();
  };

  const loadModels = async () => {
    if (!agentBaseUrl.trim() || !agentApiKey.trim()) {
      setModelError("请先填写 Base URL 和 API Key，也可以直接输入模型 ID。");
      return;
    }
    setModelLoading(true);
    setModelError("");
    try {
      const response = await getModels(agentBaseUrl.trim(), agentApiKey.trim());
      setModelOptions(
        Array.from(new Set(response.models.map((model) => model.trim()).filter(Boolean))),
      );
    } catch (reason) {
      setModelOptions([]);
      setModelError(reason instanceof Error ? reason.message : "模型列表加载失败");
    } finally {
      setModelLoading(false);
    }
  };

  const openModelPicker = () => {
    const opening = !modelPickerOpen;
    setModelPickerOpen(opening);
    if (!opening) return;
    setModelSearch("");
    if (!modelOptions.length) void loadModels();
  };

  const chooseModel = (model: string) => {
    const value = model.trim();
    if (!value) return;
    changeAgent(() => setAgentModel(value));
    setModelSearch("");
    setModelPickerOpen(false);
  };

  const continueToTts = () => {
    if (!agentReady) {
      setError("请完整填写 Base URL、API Key 和模型名称。");
      return;
    }
    setError("");
    setStep("tts");
  };

  const buildConfig = (): AppConfig => {
    const dynamicContext = Object.fromEntries(
      rows
        .filter((row) => row.name.trim())
        .map((row) => [row.name.trim(), row.value.trim()]),
    );
    return {
      ...base,
      asr: {
        provider: "qwen_audio",
        settings: {
          api_key: asrApiKey.trim(),
          workspace_id: asrWorkspaceId.trim(),
        },
      },
      bumblehive: {
        ...base.bumblehive,
        provider: {
          ...asObject(base.bumblehive.provider),
          type: "openai_chat_completions",
          model: agentModel.trim(),
          api_key: agentApiKey.trim(),
          base_url: agentBaseUrl.trim(),
        },
        generation: mergeGenerationConfig(
          asObject(base.bumblehive.generation),
          { thinkingEnabled, reasoningEffort },
        ),
        agent: mergeAgentPersonalization(
          asObject(base.bumblehive.agent),
          personalizationEnabled,
          instructions.trim(),
          dynamicContext,
        ),
      },
      personalization_enabled: personalizationEnabled,
      opening_enabled: openingEnabled,
      interruption: {
        ...base.interruption,
        backchannel_filter_enabled: backchannelFilterEnabled,
      },
      tts: {
        provider: "volcengine",
        settings: {
          ...base.tts.settings,
          api_key: ttsApiKey.trim(),
          voice: voiceId.trim(),
          resource_id: resourceIdForVoiceKind(voiceKind),
        },
      },
      inactivity_policy: followupEnabled
        ? {
            timeout_seconds: followupTimeoutValue,
            max_followups: maximumFollowupsValue,
            on_exhausted: exhaustedAction,
          }
        : null,
    };
  };

  const save = async () => {
    if (!asrReady) {
      setError("请填写 Qwen Audio 的 API Key。");
      setStep("asr");
      return;
    }
    if (!agentReady) {
      setError("请完整填写 Base URL、API Key 和模型名称。");
      setStep("agent");
      return;
    }
    if (!ttsReady) {
      setError("请选择语音服务，并填写 API Key 和音色 ID。");
      setStep("tts");
      return;
    }
    if (followupError) {
      setError(followupError);
      setStep("agent");
      return;
    }
    if (active) {
      setError("当前对话运行中，请结束对话后再保存配置。");
      return;
    }
    setSaveState("saving");
    setError("");
    try {
      await onSave(buildConfig());
      setDirty(false);
      setSaveState("saved");
      if (saveNoticeTimerRef.current !== null) {
        window.clearTimeout(saveNoticeTimerRef.current);
      }
      saveNoticeTimerRef.current = window.setTimeout(() => {
        saveNoticeTimerRef.current = null;
        setSaveState("idle");
      }, 2_800);
    } catch (reason) {
      setSaveState("idle");
      setError(reason instanceof Error ? reason.message : "配置保存失败");
    }
  };

  const stageStatus = (item: Step) => {
    if (item === "asr") return asrReady;
    if (item === "agent") return agentReady;
    if (item === "tts") return ttsReady;
    return true;
  };

  const savedConfig = config !== null;
  const saveButtonLabel = saveState === "saving"
    ? "正在保存…"
    : saveState === "saved"
      ? "已保存 ✓"
      : savedConfig
        ? "保存更改"
        : "保存配置";
  const saveStatus = active
    ? "当前对话运行中，请结束对话后再保存配置。"
    : error || (dirty
      ? "有未保存的更改"
      : savedConfig
        ? "当前配置已保存"
        : "服务连接信息仅保存在本机。");

  return (
    <main className="configuration-page">
      <div className="configuration-scroll">
        <section className="configuration-shell">
          <ConfigurationHeader backLabel={backLabel} onBack={handleBack} />
          <nav className="configuration-chain" aria-label="语音处理链路">
            {([
              ["asr", "语音识别", asrReady ? "已填写" : "待配置"],
              ["agent", "智能体", agentReady ? "已填写" : "待配置"],
              ["tts", "语音合成", ttsReady ? "已填写" : "待配置"],
            ] as const).map(([item, label, badge], index) => {
              const ready = stageStatus(item);
              return (
                <button
                  className={`configuration-stage ${ready ? "ready" : "pending"} ${step === item ? "selected" : ""}`}
                  key={item}
                  type="button"
                  onClick={() => { setStep(item); setError(""); }}
                >
                  <span>{ready ? "✓" : index + 1}</span>
                  <strong>{label}</strong>
                  <small>{badge}</small>
                </button>
              );
            })}
          </nav>

          {step === "asr" && (
            <section className="configuration-panel agent-panel">
              <div className="configuration-body">
                <div className="agent-layout">
                  <article className="configuration-card connection-card">
                    <header className="connection-card-header">
                      <div>
                        <h3>Qwen Audio</h3>
                        <p>使用阿里云实时语音识别，音频会在说话过程中持续上传。</p>
                      </div>
                      <span>Streaming ASR</span>
                    </header>
                    <div className="connection-fields">
                      <label>
                        <span><strong>API Key</strong><small>模型服务访问密钥</small></span>
                        <input
                          type="password"
                          value={asrApiKey}
                          placeholder="填写 Qwen Audio API Key"
                          onChange={(event) => { setAsrApiKey(event.target.value); markDirty(); }}
                        />
                      </label>
                      <label>
                        <span><strong>Workspace ID（选填）</strong><small>不填时使用阿里云公共接口</small></span>
                        <input
                          value={asrWorkspaceId}
                          placeholder="选填 Workspace ID"
                          onChange={(event) => { setAsrWorkspaceId(event.target.value); markDirty(); }}
                        />
                      </label>
                      <label>
                        <span><strong>模型</strong><small>当前使用的实时识别模型</small></span>
                        <input value="qwen-audio-3.0-asr-flash-streaming" readOnly />
                      </label>
                    </div>
                  </article>
                </div>
                <PageActions
                  disabled={active || saveState === "saving" || (savedConfig && !dirty)}
                  label={saveButtonLabel}
                  status={saveStatus}
                  onClick={() => void save()}
                />
              </div>
            </section>
          )}

          {step === "agent" && (
            <section className="configuration-panel agent-panel">
              <div className="configuration-body">
                <div className="agent-layout">
                  <article className="configuration-card connection-card">
                    <header className="connection-card-header">
                      <div><h3>模型配置</h3><p>连接任何兼容 OpenAI Chat Completions 的模型服务。</p></div>
                      <span>OpenAI Compatible</span>
                    </header>
                    <div className="connection-fields">
                        <label><span><strong>Base URL</strong><small>模型服务地址</small></span><input type="url" value={agentBaseUrl} placeholder="例如：https://api.deepseek.com" onChange={(event) => { changeAgent(() => setAgentBaseUrl(event.target.value)); setModelOptions([]); setModelError(""); }} /></label>
                        <label><span><strong>API Key</strong><small>模型访问密钥</small></span><input type="password" value={agentApiKey} placeholder="填写模型服务 API Key" onChange={(event) => { changeAgent(() => setAgentApiKey(event.target.value)); setModelOptions([]); setModelError(""); }} /></label>
                        <div className="model-field">
                          <span><strong>模型</strong><small>选择或输入模型 ID</small></span>
                          <button className="model-selector" type="button" aria-haspopup="dialog" aria-expanded={modelPickerOpen} onClick={openModelPicker}>
                            <strong>{agentModel || "选择或输入模型"}</strong>
                            {modelLoading ? <i className="model-spinner" aria-label="正在获取模型" /> : <i className="model-chevron" />}
                          </button>
                          {modelPickerOpen && (
                            <div className="model-popover" role="dialog" aria-label="选择模型">
                              <input
                                autoFocus
                                value={modelSearch}
                                placeholder="搜索或输入模型 ID"
                                aria-label="搜索或输入模型 ID"
                                onChange={(event) => setModelSearch(event.target.value)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" && manualModel) chooseModel(manualModel);
                                  if (event.key === "Escape") setModelPickerOpen(false);
                                }}
                              />
                              {!modelLoading && modelError && (
                                <div className="model-error" role="alert">{modelError}</div>
                              )}
                              <div className="model-results" role="listbox">
                                {modelLoading ? (
                                  <div className="model-empty"><i className="model-spinner" /><span>正在从服务商获取模型…</span></div>
                                ) : (
                                  <>
                                    {visibleModels.map((model) => (
                                      <button key={model} type="button" role="option" aria-selected={model === agentModel} onClick={() => chooseModel(model)}>
                                        <i>{model === agentModel ? "✓" : ""}</i><span>{model}</span>
                                      </button>
                                    ))}
                                    {manualModel && !hasExactModel && (
                                      <button className="manual" type="button" role="option" aria-selected="false" onClick={() => chooseModel(manualModel)}>
                                        <i>＋</i><span><strong>使用“{manualModel}”</strong><small>手动输入模型 ID</small></span>
                                      </button>
                                    )}
                                    {!visibleModels.length && !manualModel && !modelError && (
                                      <div className="model-empty"><i>◇</i><span>填写连接信息后获取模型，也可以直接输入模型 ID。</span></div>
                                    )}
                                  </>
                                )}
                              </div>
                              <footer><span>{modelOptions.length ? `${modelOptions.length} 个模型` : "支持手动输入"}</span><button type="button" disabled={modelLoading || !agentBaseUrl.trim() || !agentApiKey.trim()} onClick={() => void loadModels()}>↻ {modelOptions.length ? "刷新" : "获取"}</button></footer>
                            </div>
                          )}
                        </div>
                        <section className="generation-settings" aria-label="生成配置">
                          <button
                            className="generation-setting-row"
                            type="button"
                            role="switch"
                            aria-checked={thinkingEnabled}
                            aria-expanded={thinkingEnabled}
                            aria-controls="reasoning-effort-setting"
                            onClick={() => changeAgent(() => setThinkingEnabled((enabled) => !enabled))}
                          >
                            <span>
                              <strong>思考模式</strong>
                              <small>默认开启；关闭时发送 thinking.type=disabled</small>
                            </span>
                            <i className={`generation-switch ${thinkingEnabled ? "enabled" : ""}`} aria-hidden="true"><b /></i>
                          </button>
                          {thinkingEnabled && (
                            <label className="generation-setting-row reasoning-setting" id="reasoning-effort-setting">
                              <span>
                                <strong>推理强度</strong>
                                <small>留空时不发送 reasoning_effort，填写后按原值加入请求</small>
                              </span>
                              <input
                                className="reasoning-effort-control"
                                aria-label="推理强度"
                                spellCheck={false}
                                value={reasoningEffort}
                                placeholder="如 high、max"
                                onChange={(event) => changeAgent(() => setReasoningEffort(event.target.value))}
                              />
                            </label>
                          )}
                          <button
                            className="generation-setting-row"
                            type="button"
                            role="switch"
                            aria-checked={openingEnabled}
                            onClick={() => changeAgent(() => setOpeningEnabled((enabled) => !enabled))}
                          >
                            <span>
                              <strong>主动开启对话</strong>
                              <small>开启语音后，Agent 会根据系统提示词主动开始对话</small>
                            </span>
                            <i className={`generation-switch ${openingEnabled ? "enabled" : ""}`} aria-hidden="true"><b /></i>
                          </button>
                          <button
                            className="generation-setting-row"
                            type="button"
                            role="switch"
                            aria-checked={backchannelFilterEnabled}
                            onClick={() => changeAgent(() => setBackchannelFilterEnabled((enabled) => !enabled))}
                          >
                            <span>
                              <strong>误打断过滤</strong>
                              <small>Agent 播放时，简短附和词不会中断播放</small>
                            </span>
                            <i className={`generation-switch ${backchannelFilterEnabled ? "enabled" : ""}`} aria-hidden="true"><b /></i>
                          </button>
                          <button
                            className="generation-setting-row"
                            type="button"
                            role="switch"
                            aria-checked={followupEnabled}
                            aria-expanded={followupEnabled}
                            aria-controls="inactivity-policy-settings"
                            onClick={() => changeAgent(() => setFollowupEnabled((enabled) => !enabled))}
                          >
                              <span>
                                <strong>无响应时主动询问</strong>
                                <small>每次进入聆听后，用户没有回应时，Agent 会主动询问</small>
                            </span>
                            <i className={`generation-switch ${followupEnabled ? "enabled" : ""}`} aria-hidden="true"><b /></i>
                          </button>
                          {followupEnabled && (
                            <div className="followup-settings" id="inactivity-policy-settings">
                              <label className="generation-setting-row followup-setting-row">
                                <span>
                                  <strong>询问间隔</strong>
                                  <small>Agent 播放结束并重新进入聆听后开始计时</small>
                                </span>
                                <span className="followup-number-control">
                                  <input
                                    type="number"
                                    inputMode="decimal"
                                    min="0.1"
                                    step="0.1"
                                    value={followupTimeout}
                                    aria-label="询问间隔"
                                    onFocus={(event) => event.target.select()}
                                    onChange={(event) => changeAgent(() => setFollowupTimeout(event.target.value))}
                                  />
                                  <small>秒</small>
                                </span>
                              </label>
                              <label className="generation-setting-row followup-setting-row">
                                <span>
                                  <strong>最多询问</strong>
                                  <small>连续无回应时最多主动询问的次数</small>
                                </span>
                                <span className="followup-number-control">
                                  <input
                                    type="number"
                                    inputMode="numeric"
                                    min="1"
                                    step="1"
                                    value={maximumFollowups}
                                    aria-label="最多询问次数"
                                    onFocus={(event) => event.target.select()}
                                    onChange={(event) => changeAgent(() => setMaximumFollowups(event.target.value))}
                                  />
                                  <small>次</small>
                                </span>
                              </label>
                              <label className="generation-setting-row followup-setting-row">
                                <span>
                                  <strong>达到上限后</strong>
                                  <small>默认停止追问并继续聆听</small>
                                </span>
                                <select
                                  className="followup-action-control"
                                  value={exhaustedAction}
                                  aria-label="达到询问上限后的行为"
                                  onChange={(event) => changeAgent(() => setExhaustedAction(event.target.value as "wait" | "stop" | "farewell"))}
                                >
                                  <option value="wait">继续聆听</option>
                                  <option value="stop">关闭语音</option>
                                  <option value="farewell">告别后关闭</option>
                                </select>
                              </label>
                            </div>
                          )}
                        </section>
                    </div>
                    {followupError && <p className="settings-inline-error" role="alert">{followupError}</p>}
                  </article>

                  <article className={`configuration-card personalization-card ${personalizationEnabled ? "open" : ""}`}>
                    <button
                      className="personalization-toggle-row"
                      type="button"
                      role="switch"
                      aria-checked={personalizationEnabled}
                      aria-expanded={personalizationEnabled}
                      aria-controls="personalization-content"
                      onClick={() => changeAgent(() => setPersonalizationEnabled((enabled) => !enabled))}
                    >
                      <div><h3>个性化配置</h3><p>设置助手的角色、业务目标和工作方式；默认语音与工具规则会自动保留。</p></div>
                      <span className="personalization-switch" aria-hidden="true"><i /></span>
                    </button>
                    {personalizationEnabled && <div className="personalization-content" id="personalization-content">
                      <label className="instructions-field">
                        <span>角色与工作要求</span>
                        <textarea
                          aria-label="智能体角色与工作要求"
                          value={instructions}
                          placeholder="例如：你是公司的专业售前顾问。先了解客户的业务场景，再介绍合适的产品能力。"
                          onChange={(event) => changeAgent(() => setInstructions(event.target.value))}
                        />
                      </label>
                      <section className="context-section">
                        <header><div><h3>全局信息</h3><p>填写智能体需要长期了解的固定信息，例如公司名称、产品名称或服务范围。</p></div><button type="button" onClick={() => changeAgent(() => setRows((current) => [...current, { id: crypto.randomUUID(), name: "", value: "" }] ))}>＋ 添加全局信息</button></header>
                        <div className="context-labels"><span>信息名称</span><span>信息内容</span><span /></div>
                        <div className="context-editor">
                          {rows.map((row) => (
                            <div className="context-row" key={row.id}>
                              <input aria-label="信息名称" placeholder="例如：公司名称" value={row.name} onChange={(event) => updateRow(row.id, "name", event.target.value)} />
                              <input aria-label="信息内容" placeholder="填写具体信息内容" value={row.value} onChange={(event) => updateRow(row.id, "value", event.target.value)} />
                              <button type="button" aria-label="删除这条全局信息" onClick={() => changeAgent(() => setRows((current) => current.filter((item) => item.id !== row.id)))}>×</button>
                            </div>
                          ))}
                        </div>
                      </section>
                    </div>}
                  </article>
                </div>
                <PageActions
                  disabled={active || saveState === "saving" || (savedConfig && !dirty)}
                  label={savedConfig ? saveButtonLabel : "下一步：配置语音"}
                  status={saveStatus}
                  onClick={savedConfig ? () => void save() : continueToTts}
                />
              </div>
            </section>
          )}

          {step === "tts" && (
            <section className="configuration-panel">
              <div className="configuration-body">
                <div className="tts-setup">
                  <aside className="service-picker">
                    <h3>语音服务</h3>
                    <button className={`service-option ${ttsSelected ? "selected" : ""}`} type="button" onClick={() => { setTtsSelected(true); markDirty(); }}>
                      <img src={volcengineLogo} alt="" aria-hidden="true" /><span><strong>火山引擎语音</strong></span><b>✓</b>
                    </button>
                  </aside>
                  <section className="service-detail">
                    {!ttsSelected ? (
                      <div className="service-empty"><i>⌁</i><strong>先选择语音服务</strong><p>选择左侧服务后，这里会显示需要填写的连接信息。</p></div>
                    ) : (
                      <div className="service-form">
                        <header><h3>连接与音色</h3></header>
                        <div className="provider-fields">
                          <label><span>API Key</span><input type="password" value={ttsApiKey} placeholder="填写火山引擎 API Key" onChange={(event) => { setTtsApiKey(event.target.value); markDirty(); }} /></label>
                          <fieldset className="voice-kind-field">
                            <legend>音色类型</legend>
                            <div className="voice-kind-picker">
                              <button
                                className={voiceKind === "platform" ? "selected" : ""}
                                type="button"
                                aria-pressed={voiceKind === "platform"}
                                onClick={() => { setVoiceKind("platform"); markDirty(); }}
                              >
                                平台音色
                              </button>
                              <button
                                className={voiceKind === "clone" ? "selected" : ""}
                                type="button"
                                aria-pressed={voiceKind === "clone"}
                                onClick={() => { setVoiceKind("clone"); markDirty(); }}
                              >
                                我的克隆音色
                              </button>
                            </div>
                          </fieldset>
                          <label>
                            <span className="voice-field-title">
                              <span>音色 ID</span>
                              {voiceKind === "platform" && (
                                <a href={VOICE_LIBRARY_URL} target="_blank" rel="noreferrer" onClick={(event) => { if (!("__TAURI_INTERNALS__" in window)) return; event.preventDefault(); void openUrl(VOICE_LIBRARY_URL).catch(() => setError("无法打开音色库，请稍后重试。")); }}>
                                  前往平台音色库 ↗
                                </a>
                              )}
                            </span>
                            <input
                              value={voiceId}
                              placeholder={voiceKind === "clone" ? "填写克隆音色 ID" : "填写平台音色 ID"}
                              onChange={(event) => {
                                if (voiceKind === "clone") setCloneVoiceId(event.target.value);
                                else setPlatformVoiceId(event.target.value);
                                markDirty();
                              }}
                            />
                          </label>
                        </div>
                        <footer>
                          <span>{saveStatus}</span>
                          <button type="button" disabled={active || saveState === "saving" || (savedConfig && !dirty)} onClick={() => void save()}>{saveButtonLabel}</button>
                        </footer>
                      </div>
                    )}
                  </section>
                </div>
                {error && <p className="configuration-error">{error}</p>}
              </div>
            </section>
          )}
        </section>
      </div>
      {saveState === "saved" && (
        <div className="configuration-save-toast" role="status">
          <i aria-hidden="true">✓</i>
          <span><strong>配置已保存</strong><small>新的设置将在下次启动对话时生效。</small></span>
        </div>
      )}
      {leaveConfirmationOpen && (
        <ConfigurationLeaveDialog
          onCancel={() => setLeaveConfirmationOpen(false)}
          onConfirm={discardAndLeave}
        />
      )}
    </main>
  );
}

export function ConfigurationLeaveDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="configuration-leave-backdrop">
      <section
        className="configuration-leave-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="configuration-leave-title"
        aria-describedby="configuration-leave-description"
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
        }}
      >
        <div className="configuration-leave-icon" aria-hidden="true">!</div>
        <h2 id="configuration-leave-title">放弃未保存的更改？</h2>
        <p id="configuration-leave-description">
          当前修改尚未保存。返回后这些修改会丢失，但正在进行的语音对话不会中断。
        </p>
        <div className="configuration-leave-actions">
          <button type="button" autoFocus onClick={onCancel}>继续编辑</button>
          <button className="danger" type="button" onClick={onConfirm}>
            放弃更改并返回
          </button>
        </div>
      </section>
    </div>
  );
}

function PageActions({ disabled, label, status, onClick }: { disabled: boolean; label: string; status: string; onClick: () => void }) {
  return <div className="configuration-actions"><span>{status}</span><button type="button" disabled={disabled} onClick={onClick}>{label}</button></div>;
}
