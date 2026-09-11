import { useState, type ReactNode } from "react";
import aliyunLogo from "../../assets/aliyun-logo.png";
import volcengineLogo from "../../assets/volcengine-logo.png";
import type { AppConfig } from "../../runtime/contracts";

export const DEFAULT_ASR_RESOURCE = "volc.seedasr.sauc.duration";
export type ASRProvider = AppConfig["asr"]["provider"];
export type ASRDrafts = {
  qwen_audio: { api_key: string; workspace_id: string };
  volcengine: { api_key: string; resource_id: string };
};

export function asrDrafts(config: AppConfig["asr"]): ASRDrafts {
  return {
    qwen_audio: config.provider === "qwen_audio"
      ? { ...config.settings } : { api_key: "", workspace_id: "" },
    volcengine: config.provider === "volcengine"
      ? { ...config.settings } : { api_key: "", resource_id: DEFAULT_ASR_RESOURCE },
  };
}

export function buildASRConfig(provider: ASRProvider, drafts: ASRDrafts): AppConfig["asr"] {
  return provider === "qwen_audio"
    ? { provider, settings: {
        api_key: drafts.qwen_audio.api_key.trim(),
        workspace_id: drafts.qwen_audio.workspace_id.trim(),
      } }
    : { provider, settings: {
        api_key: drafts.volcengine.api_key.trim(),
        resource_id: drafts.volcengine.resource_id.trim() || DEFAULT_ASR_RESOURCE,
      } };
}

export function ASRConfiguration({
  provider, drafts, disabled, onProviderChange, onChange, children,
}: {
  provider: ASRProvider;
  drafts: ASRDrafts;
  disabled: boolean;
  onProviderChange: (provider: ASRProvider) => void;
  onChange: (drafts: ASRDrafts) => void;
  children: ReactNode;
}) {
  const volcengine = provider === "volcengine";
  const advancedValue = volcengine
    ? drafts.volcengine.resource_id : drafts.qwen_audio.workspace_id;
  return (
    <div className="tts-setup asr-setup">
      <aside className="service-picker">
        <h3>识别服务</h3>
        {(["qwen_audio", "volcengine"] as const).map((item) => (
          <button key={item} type="button"
            className={`service-option ${provider === item ? "selected" : ""}`}
            aria-pressed={provider === item}
            disabled={disabled}
            onClick={() => onProviderChange(item)}>
            {item === "volcengine"
              ? <img src={volcengineLogo} alt="" />
              : <img src={aliyunLogo} alt="" />}
            <span><strong>{item === "volcengine" ? "火山引擎" : "阿里云"}</strong></span>
            <b aria-hidden="true">✓</b>
          </button>
        ))}
      </aside>
      <section className="service-detail">
        <div className="service-form">
          <header><h3>连接配置</h3></header>
          {disabled && <p className="asr-session-notice">结束当前会话后可修改识别配置。</p>}
          <div className="provider-fields">
            <div className="asr-model">
              <span>识别模型</span>
              <strong>{volcengine
                ? "豆包流式语音识别模型2.0"
                : "qwen-audio-3.0-asr-flash-streaming"}</strong>
            </div>
            <label><span>API Key</span>
              <input type="password" disabled={disabled}
                value={drafts[provider].api_key}
                placeholder={volcengine ? "填写火山引擎 API Key" : "填写 Qwen Audio API Key"}
                onChange={(event) => onChange({
                  ...drafts, [provider]: { ...drafts[provider], api_key: event.target.value },
                })} />
            </label>
            <AdvancedSettings key={provider} provider={provider}
              initiallyOpen={volcengine
                ? advancedValue !== DEFAULT_ASR_RESOURCE && advancedValue !== ""
                : advancedValue !== ""}>
              <label>
                <span>{volcengine ? "Resource ID" : "Workspace ID"}</span>
                <input disabled={disabled} value={advancedValue}
                  aria-describedby="asr-advanced-description"
                  placeholder={volcengine ? DEFAULT_ASR_RESOURCE : "留空使用公共接口"}
                  onChange={(event) => onChange(volcengine
                    ? { ...drafts, volcengine: { ...drafts.volcengine, resource_id: event.target.value } }
                    : { ...drafts, qwen_audio: { ...drafts.qwen_audio, workspace_id: event.target.value } })} />
              </label>
              <p id="asr-advanced-description">
                {volcengine
                  ? "默认按音频时长计费，通常无需修改。留空时使用默认资源。"
                  : "留空时使用阿里云公共接口。"}
              </p>
            </AdvancedSettings>
          </div>
          {children}
        </div>
      </section>
    </div>
  );
}

function AdvancedSettings({ provider, initiallyOpen, children }: {
  provider: ASRProvider;
  initiallyOpen: boolean;
  children: ReactNode;
}) {
  const storageKey = `lalk-asr-advanced-${provider}`;
  const [open, setOpen] = useState(() => {
    const saved = typeof localStorage === "undefined"
      ? null : localStorage.getItem(storageKey);
    return saved === null ? initiallyOpen : saved === "true";
  });
  return (
    <details className="asr-advanced" open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        if (next === open) return;
        setOpen(next);
        if (typeof localStorage !== "undefined") {
          localStorage.setItem(storageKey, String(next));
        }
      }}>
      <summary>高级设置</summary>
      {children}
    </details>
  );
}
