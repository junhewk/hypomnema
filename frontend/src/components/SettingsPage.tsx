"use client";

import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useSettings } from "@/hooks/useSettings";
import type {
  SettingsUpdatePayload,
  ProviderInfo,
  EmbeddingChangeStatus,
  ModelOption,
  ConnectivityCheckPayload,
  TidyLevel,
} from "@/lib/types";
import {
  BASE_LLM_LABEL,
  BASE_LLM_MODEL,
  BASE_LLM_PROVIDER,
  PROVIDER_ICONS,
  TIDY_LEVEL_OPTIONS,
} from "@/lib/constants";

function ProviderCard({
  info,
  active,
  onSelect,
  index,
}: {
  info: ProviderInfo;
  active: boolean;
  onSelect: () => void;
  index: number;
}) {
  return (
    <button
      onClick={onSelect}
      className="animate-fade-up group relative border-l-2 bg-surface-raised py-2.5 pr-4 pl-4 text-left transition-colors hover:bg-surface"
      style={{
        borderLeftColor: active ? "var(--accent)" : "var(--border)",
        animationDelay: `${index * 50}ms`,
      }}
    >
      {/* active dot */}
      {active && (
        <div className="absolute top-2.5 right-3 h-1.5 w-1.5 rounded-full bg-[var(--complete)]" />
      )}
      <div className="flex items-center gap-2.5">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-sm font-mono text-[10px] font-bold"
          style={{
            background: active
              ? "color-mix(in srgb, var(--accent) 15%, transparent)"
              : "color-mix(in srgb, var(--muted) 10%, transparent)",
            color: active ? "var(--accent)" : "var(--muted)",
          }}
        >
          {PROVIDER_ICONS[info.id] ?? "?"}
        </span>
        <div>
          <span className="block font-mono text-xs font-medium">
            {info.name}
            {info.id === BASE_LLM_PROVIDER && info.default_model === BASE_LLM_MODEL && (
              <span className="ml-2 rounded-sm bg-muted/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted/60">
                {BASE_LLM_LABEL}
              </span>
            )}
          </span>
          <span className="block font-mono text-[10px] text-muted/60">
            {info.requires_key ? "api key required" : "local"} · {info.default_model}
          </span>
        </div>
      </div>
    </button>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  mono = true,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <label className="mb-3 block animate-fade-up">
      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full border-b border-border bg-transparent pb-1.5 text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus ${mono ? "font-mono" : "font-sans"}`}
      />
    </label>
  );
}

function FieldSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: ModelOption[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="mb-3 block animate-fade-up">
      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors focus:border-border-focus"
      >
        {options.map((option) => (
          <option key={option.id} value={option.id} className="bg-background text-foreground">
            {option.name} · {option.id}
          </option>
        ))}
      </select>
    </label>
  );
}

type ProbeState = {
  tone: "info" | "checking" | "success" | "error";
  message: string;
} | null;

function ProbeMessage({ state }: { state: ProbeState }) {
  if (!state) return null;
  const color = {
    info: "text-muted/50",
    checking: "text-muted/60",
    success: "text-[var(--complete)]",
    error: "text-red-500",
  }[state.tone];
  return <span className={`animate-fade-up font-mono text-[10px] ${color}`}>{state.message}</span>;
}

export function SettingsPage() {
  const { settings, providers, isLoading, error: loadError, refresh } = useSettings();

  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [googleKey, setGoogleKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [openaiUrl, setOpenaiUrl] = useState("");
  const [tidyLevel, setTidyLevel] = useState<TidyLevel>("structured_notes");

  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const [llmProbe, setLlmProbe] = useState<ProbeState>(null);
  const [llmChecking, setLlmChecking] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setProvider(settings.llm_provider);
    setModel(settings.llm_model);
    setAnthropicKey(settings.anthropic_api_key);
    setGoogleKey(settings.google_api_key);
    setOpenaiKey(settings.openai_api_key);
    setOllamaUrl(settings.ollama_base_url);
    setOpenaiUrl(settings.openai_base_url);
    setTidyLevel(settings.tidy_level);
    setDirty(new Set());
    setLlmProbe(null);
  }, [settings]);

  function markDirty(field: string) {
    setDirty((prev) => new Set(prev).add(field));
    setSaveOk(false);
    setSaveError(null);
  }

  function providerInfo(id: string) {
    return providers?.llm.find((item) => item.id === id) ?? null;
  }

  function configuredSecret(providerId: string) {
    switch (providerId) {
      case "claude":
        return anthropicKey.trim();
      case "google":
        return googleKey.trim();
      case "openai":
        return openaiKey.trim();
      default:
        return "";
    }
  }

  function buildLlmProbePayload(nextProvider = provider, nextModel = model): ConnectivityCheckPayload {
    const payload: ConnectivityCheckPayload = {
      kind: "llm",
      provider: nextProvider,
      model: nextModel,
    };

    switch (nextProvider) {
      case "claude":
        if (dirty.has("anthropic_api_key")) payload.anthropic_api_key = anthropicKey;
        break;
      case "google":
        if (dirty.has("google_api_key")) payload.google_api_key = googleKey;
        break;
      case "openai":
        if (dirty.has("openai_api_key")) payload.openai_api_key = openaiKey;
        if (dirty.has("openai_base_url")) payload.openai_base_url = openaiUrl;
        break;
      case "ollama":
        if (dirty.has("ollama_base_url")) payload.ollama_base_url = ollamaUrl;
        break;
    }

    return payload;
  }

  async function verifyLlmConnection(nextProvider = provider, nextModel = model) {
    if (!nextProvider) return;
    const selectedModel = nextModel || providerInfo(nextProvider)?.default_model || "";
    if (!selectedModel) {
      setLlmProbe({ tone: "info", message: "Select a model to verify wiring." });
      return;
    }
    if (nextProvider !== "ollama" && configuredSecret(nextProvider).length === 0) {
      setLlmProbe({ tone: "info", message: "Add the provider key to verify wiring." });
      return;
    }

    setLlmChecking(true);
    setLlmProbe({ tone: "checking", message: `Checking ${selectedModel}...` });
    try {
      const result = await api.checkConnection(buildLlmProbePayload(nextProvider, selectedModel));
      setLlmProbe({ tone: "success", message: result.message });
    } catch (e) {
      setLlmProbe({ tone: "error", message: e instanceof Error ? e.message : "Connection check failed" });
    } finally {
      setLlmChecking(false);
    }
  }

  function selectProvider(id: string) {
    const nextInfo = providerInfo(id);
    const nextModel = nextInfo?.default_model ?? model;
    setProvider(id);
    markDirty("llm_provider");
    if (nextInfo) {
      setModel(nextModel);
      markDirty("llm_model");
    }
    setLlmProbe(null);
    void verifyLlmConnection(id, nextModel);
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      const payload: SettingsUpdatePayload = {};
      if (dirty.has("llm_provider")) payload.llm_provider = provider;
      if (dirty.has("llm_model")) payload.llm_model = model;
      if (dirty.has("anthropic_api_key")) payload.anthropic_api_key = anthropicKey;
      if (dirty.has("google_api_key")) payload.google_api_key = googleKey;
      if (dirty.has("openai_api_key")) payload.openai_api_key = openaiKey;
      if (dirty.has("ollama_base_url")) payload.ollama_base_url = ollamaUrl;
      if (dirty.has("openai_base_url")) payload.openai_base_url = openaiUrl;
      if (dirty.has("tidy_level")) payload.tidy_level = tidyLevel;

      if (Object.keys(payload).length === 0) return;

      await api.updateSettings(payload);
      setSaveOk(true);
      setDirty(new Set());
      setLlmProbe(null);
      refresh();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-12">
        <p className="font-mono text-xs text-muted animate-pulse-dot">Loading...</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-12">
        <p className="font-mono text-xs text-red-500">{loadError}</p>
      </div>
    );
  }

  const selectedProvider = providerInfo(provider);
  const modelOptions = selectedProvider?.models ?? [];

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-6 font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-muted/40">
        Configuration
      </h1>

      {/* LLM Provider selector */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
            LLM Provider
          </h2>
          <div className="h-px flex-1 bg-border" />
        </div>

        <div className="mb-px flex flex-col gap-px">
          {providers?.llm.map((p, i) => (
            <ProviderCard
              key={p.id}
              info={p}
              active={provider === p.id}
              onSelect={() => selectProvider(p.id)}
              index={i}
            />
          ))}
        </div>
      </section>

      {/* Provider config fields */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
            Provider Config
          </h2>
          <div className="h-px flex-1 bg-border" />
        </div>

        <div
          className="animate-fade-up border-l-2 bg-surface-raised py-4 pr-4 pl-4"
          style={{ borderLeftColor: "var(--accent)" }}
        >
          {modelOptions.length > 0 ? (
            <FieldSelect
              label="Model"
              value={model || selectedProvider?.default_model || ""}
              options={modelOptions}
              onChange={(v) => {
                setModel(v);
                markDirty("llm_model");
                setLlmProbe(null);
                void verifyLlmConnection(provider, v);
              }}
            />
          ) : (
            <FieldInput
              label="Model"
              value={model}
              onChange={(v) => { setModel(v); markDirty("llm_model"); setLlmProbe(null); }}
              placeholder={selectedProvider?.default_model}
            />
          )}

          {provider === "claude" && (
            <FieldInput
              label="Anthropic API Key"
              value={anthropicKey}
              onChange={(v) => { setAnthropicKey(v); markDirty("anthropic_api_key"); }}
              type="password"
              placeholder="sk-ant-..."
            />
          )}

          {provider === "google" && (
            <FieldInput
              label="Google API Key"
              value={googleKey}
              onChange={(v) => { setGoogleKey(v); markDirty("google_api_key"); }}
              type="password"
              placeholder="AIza..."
            />
          )}

          {provider === "openai" && (
            <>
              <FieldInput
                label="OpenAI API Key"
                value={openaiKey}
                onChange={(v) => { setOpenaiKey(v); markDirty("openai_api_key"); }}
                type="password"
                placeholder="sk-..."
              />
              <FieldInput
                label="Base URL (optional — Together, Groq, vLLM, etc.)"
                value={openaiUrl}
                onChange={(v) => { setOpenaiUrl(v); markDirty("openai_base_url"); }}
                placeholder="https://api.openai.com/v1"
              />
            </>
          )}

          {provider === "ollama" && (
            <FieldInput
              label="Ollama Base URL"
              value={ollamaUrl}
              onChange={(v) => { setOllamaUrl(v); markDirty("ollama_base_url"); }}
              placeholder="http://localhost:11434"
            />
          )}

          <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
            <ProbeMessage state={llmProbe} />
            <button
              onClick={() => void verifyLlmConnection()}
              disabled={llmChecking || !provider}
              className="font-mono text-[10px] uppercase tracking-wider text-muted transition-colors hover:text-foreground disabled:opacity-20"
            >
              {llmChecking ? "Checking..." : "Check Wiring"}
            </button>
          </div>

          {/* Save action row */}
          <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
            <span className="font-mono text-[10px] text-muted/40">
              {dirty.size > 0
                ? `${dirty.size} unsaved ${dirty.size === 1 ? "change" : "changes"}`
                : ""}
            </span>
            <div className="flex items-center gap-3">
              {saveOk && (
                <span className="animate-fade-up font-mono text-[10px] text-[var(--complete)]">
                  applied — no restart needed
                </span>
              )}
              {saveError && (
                <span className="animate-fade-up font-mono text-[10px] text-red-500">
                  {saveError}
                </span>
              )}
              <button
                onClick={handleSave}
                disabled={saving || dirty.size === 0}
                className="rounded-md bg-foreground px-4 py-1.5 font-mono text-xs font-medium text-background transition-opacity disabled:opacity-20"
              >
                {saving ? "Applying..." : "Apply"}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
            Tidy Level
          </h2>
          <div className="h-px flex-1 bg-border" />
        </div>

        <div
          className="animate-fade-up border-l-2 bg-surface-raised py-4 pr-4 pl-4"
          style={{ borderLeftColor: "var(--engram)" }}
        >
          <FieldSelect
            label="Default tidy level"
            value={tidyLevel}
            options={TIDY_LEVEL_OPTIONS.map((option) => ({
              id: option.id,
              name: option.name,
            }))}
            onChange={(v) => {
              setTidyLevel(v as TidyLevel);
              markDirty("tidy_level");
            }}
          />
          <p className="font-mono text-[10px] leading-relaxed text-muted/50">
            {TIDY_LEVEL_OPTIONS.find((option) => option.id === tidyLevel)?.description}
          </p>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-muted/35">
            New processing uses this level immediately. Existing tidy text stays as-is until the
            document is edited or re-tidied from the CLI.
          </p>
        </div>
      </section>

      {/* Embedding Model — changeable with rebuild */}
      <EmbeddingSection
        settings={settings}
        providers={providers}
        refresh={refresh}
        openaiKey={openaiKey}
        googleKey={googleKey}
        openaiUrl={openaiUrl}
        dirty={dirty}
      />
    </div>
  );
}

function EmbeddingSection({
  settings,
  providers,
  refresh,
  openaiKey,
  googleKey,
  openaiUrl,
  dirty,
}: {
  settings: ReturnType<typeof useSettings>["settings"];
  providers: ReturnType<typeof useSettings>["providers"];
  refresh: () => void;
  openaiKey: string;
  googleKey: string;
  openaiUrl: string;
  dirty: Set<string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [newProvider, setNewProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [changing, setChanging] = useState(false);
  const [changeError, setChangeError] = useState<string | null>(null);
  const [status, setStatus] = useState<EmbeddingChangeStatus | null>(null);
  const [embeddingProbe, setEmbeddingProbe] = useState<ProbeState>(null);
  const [embeddingChecking, setEmbeddingChecking] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll for embedding change status
  useEffect(() => {
    if (status?.status !== "in_progress") return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.getEmbeddingChangeStatus();
        setStatus((prev) => {
          if (prev && prev.status === s.status && prev.processed === s.processed) return prev;
          return s;
        });
        if (s.status !== "in_progress") {
          if (pollRef.current) clearInterval(pollRef.current);
          if (s.status === "complete") {
            refresh();
            setExpanded(false);
            setConfirmText("");
            setNewProvider("");
            setApiKey("");
            setEmbeddingProbe(null);
          }
        }
      } catch {
        // ignore polling errors
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status?.status, refresh]);

  function embeddingInfo(id: string) {
    return providers?.embedding.find((item) => item.id === id) ?? null;
  }

  function configuredSharedKey(providerId: string, typedKey = apiKey) {
    if (providerId === "openai") {
      if (typedKey.trim()) return typedKey.trim();
      return (dirty.has("openai_api_key") ? openaiKey : settings?.openai_api_key || "").trim();
    }
    if (providerId === "google") {
      if (typedKey.trim()) return typedKey.trim();
      return (dirty.has("google_api_key") ? googleKey : settings?.google_api_key || "").trim();
    }
    return "";
  }

  function hasEmbeddingCredential(providerId: string, typedKey = apiKey) {
    if (providerId === "local") return true;
    return configuredSharedKey(providerId, typedKey).length > 0;
  }

  function buildEmbeddingProbePayload(providerId: string, typedKey = apiKey): ConnectivityCheckPayload {
    const selected = embeddingInfo(providerId);
    const payload: ConnectivityCheckPayload = {
      kind: "embedding",
      provider: providerId,
      model: selected?.default_model,
    };

    if (providerId === "openai") {
      if (typedKey) {
        payload.openai_api_key = typedKey;
      } else if (dirty.has("openai_api_key")) {
        payload.openai_api_key = openaiKey;
      }
      if (dirty.has("openai_base_url")) payload.openai_base_url = openaiUrl;
    }
    if (providerId === "google") {
      if (typedKey) {
        payload.google_api_key = typedKey;
      } else if (dirty.has("google_api_key")) {
        payload.google_api_key = googleKey;
      }
    }

    return payload;
  }

  async function verifyEmbeddingConnection(providerId = newProvider, typedKey = apiKey) {
    if (!providerId) return;
    const selected = embeddingInfo(providerId);
    if (!selected) return;
    if (!hasEmbeddingCredential(providerId, typedKey)) {
      setEmbeddingProbe({ tone: "info", message: "Add the provider key to verify wiring." });
      return;
    }

    setEmbeddingChecking(true);
    setEmbeddingProbe({ tone: "checking", message: `Checking ${selected.default_model}...` });
    try {
      const result = await api.checkConnection(buildEmbeddingProbePayload(providerId, typedKey));
      const suffix = result.dimension ? ` (${result.dimension}d)` : "";
      setEmbeddingProbe({ tone: "success", message: `${result.message}${suffix}` });
    } catch (e) {
      setEmbeddingProbe({ tone: "error", message: e instanceof Error ? e.message : "Connection check failed" });
    } finally {
      setEmbeddingChecking(false);
    }
  }

  async function handleChange() {
    if (!newProvider || confirmText !== "RESET") return;
    setChanging(true);
    setChangeError(null);
    try {
      const payload: {
        embedding_provider: "local" | "openai" | "google";
        openai_api_key?: string;
        google_api_key?: string;
        openai_base_url?: string;
      } = {
        embedding_provider: newProvider as "local" | "openai" | "google",
      };
      if (newProvider === "openai") {
        if (apiKey) {
          payload.openai_api_key = apiKey;
        } else if (dirty.has("openai_api_key")) {
          payload.openai_api_key = openaiKey;
        }
        if (dirty.has("openai_base_url")) {
          payload.openai_base_url = openaiUrl;
        }
      }
      if (newProvider === "google") {
        if (apiKey) {
          payload.google_api_key = apiKey;
        } else if (dirty.has("google_api_key")) {
          payload.google_api_key = googleKey;
        }
      }
      const s = await api.changeEmbeddingProvider(payload);
      setStatus(s);
    } catch (e) {
      setChangeError(e instanceof Error ? e.message : "Failed to change provider");
    } finally {
      setChanging(false);
    }
  }

  const needsKey = newProvider === "openai" || newProvider === "google";
  const isInProgress = status?.status === "in_progress";

  const pct = status && status.total > 0 ? (status.processed / status.total) * 100 : 0;

  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
          Embedding Model
        </h2>
        <div className="h-px flex-1 bg-border" />
      </div>

      <div
        className="animate-fade-up border-l-2 bg-surface-raised py-3 pr-4 pl-4"
        style={{ borderLeftColor: "var(--engram)", animationDelay: "200ms" }}
      >
        {/* Current info */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">Provider</span>
            <span className="font-mono text-xs">{settings?.embedding_provider}</span>
          </div>
          <div>
            <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">Model</span>
            <span className="font-mono text-xs">{settings?.embedding_model}</span>
          </div>
          <div>
            <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">Dim</span>
            <span className="font-mono text-xs tabular-nums">{settings?.embedding_dim}</span>
          </div>
        </div>

        {/* Progress bar when in progress */}
        {isInProgress && status && (
          <div className="mt-3 border-t border-border pt-3 animate-fade-up">
            <div className="mb-1.5 flex justify-between font-mono text-[10px]">
              <span className="text-[var(--engram)] animate-pulse-dot">Rebuilding knowledge graph...</span>
              <span className="tabular-nums text-muted/60">{status.processed} / {status.total}</span>
            </div>
            <div className="rebuild-progress-track h-1 w-full bg-border">
              <div
                className="h-full bg-[var(--engram)] transition-all duration-500 ease-out"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-2 font-mono text-[9px] text-muted/30">
              extracting entities, generating embeddings, linking edges
            </p>
          </div>
        )}

        {/* Completion / error status */}
        {status?.status === "complete" && (
          <div className="mt-3 border-t border-border pt-2 animate-fade-up">
            <p className="font-mono text-[10px] text-[var(--complete)]">
              Knowledge graph rebuilt successfully.
            </p>
          </div>
        )}
        {status?.status === "failed" && (
          <div className="mt-3 border-t border-border pt-2 animate-fade-up">
            <p className="font-mono text-[10px] text-[var(--accent)]">
              Rebuild failed: {status.error}
            </p>
          </div>
        )}

        {/* Change provider button / panel */}
        {!isInProgress && (
          <div className="mt-3 border-t border-border pt-3">
            {!expanded ? (
              <button
                onClick={() => setExpanded(true)}
                className="group flex items-center gap-2 font-mono text-[10px] text-[var(--engram)] transition-colors hover:text-foreground"
              >
                <span className="inline-block h-px w-3 bg-[var(--engram)] transition-all group-hover:w-5" />
                Change Provider
              </button>
            ) : (
              <div className="space-y-3 animate-fade-up">
                {/* Provider selector — matches LLM card style */}
                <div className="flex flex-col gap-px">
                  {providers?.embedding.map((p, i) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        setNewProvider(p.id);
                        setApiKey("");
                        setEmbeddingProbe(null);
                        void verifyEmbeddingConnection(p.id, "");
                      }}
                      className="animate-fade-up group relative border-l-2 bg-surface py-2.5 pr-4 pl-4 text-left transition-colors hover:bg-surface-raised"
                      style={{
                        borderLeftColor: newProvider === p.id ? "var(--engram)" : "var(--border)",
                        animationDelay: `${i * 50}ms`,
                      }}
                    >
                      {newProvider === p.id && (
                        <div className="absolute top-2.5 right-3 h-1.5 w-1.5 rounded-full bg-[var(--engram)]" />
                      )}
                      <div className="flex items-center gap-2.5">
                        <span
                          className="flex h-6 w-6 items-center justify-center rounded-sm font-mono text-[10px] font-bold"
                          style={{
                            background: newProvider === p.id
                              ? "color-mix(in srgb, var(--engram) 15%, transparent)"
                              : "color-mix(in srgb, var(--muted) 10%, transparent)",
                            color: newProvider === p.id ? "var(--engram)" : "var(--muted)",
                          }}
                        >
                          {PROVIDER_ICONS[p.id] ?? "?"}
                        </span>
                        <div>
                          <span className="block font-mono text-xs font-medium">{p.name}</span>
                          <span className="block font-mono text-[10px] text-muted/60">
                            {p.requires_key ? "api key required" : "local"} · {p.default_model} · {p.default_dimension}d
                          </span>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>

                {/* API key input */}
                {needsKey && (
                  <FieldInput
                    label={`${newProvider === "openai" ? "OpenAI" : "Google"} API Key`}
                    value={apiKey}
                    onChange={(value) => { setApiKey(value); setEmbeddingProbe(null); }}
                    type="password"
                    placeholder={newProvider === "openai" ? "sk-..." : "AIza..."}
                  />
                )}

                {newProvider && (
                  <div className="flex items-center justify-between border-t border-border pt-3">
                    <ProbeMessage state={embeddingProbe} />
                    <button
                      onClick={() => void verifyEmbeddingConnection()}
                      disabled={embeddingChecking}
                      className="font-mono text-[10px] uppercase tracking-wider text-muted transition-colors hover:text-foreground disabled:opacity-20"
                    >
                      {embeddingChecking ? "Checking..." : "Check Wiring"}
                    </button>
                  </div>
                )}

                {/* Warning + confirmation — grouped in a danger zone */}
                {newProvider && (
                  <div
                    className="animate-fade-up border-l-2 bg-surface py-3 pr-4 pl-4"
                    style={{
                      borderLeftColor: "var(--accent)",
                      animationDelay: "150ms",
                    }}
                  >
                    <p className="mb-3 font-mono text-[10px] leading-relaxed text-[var(--accent)]">
                      This will delete all engrams, edges, and projections. Documents
                      are preserved and will be reprocessed. This may take time and
                      API credits.
                    </p>

                    <label className="block">
                      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                        Type RESET to confirm
                      </span>
                      <input
                        type="text"
                        value={confirmText}
                        onChange={(e) => setConfirmText(e.target.value)}
                        placeholder="RESET"
                        className="reset-confirm-input w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/20 focus:border-[var(--accent)]"
                        autoComplete="off"
                        spellCheck={false}
                      />
                    </label>
                  </div>
                )}

                {changeError && (
                  <p className="font-mono text-[10px] text-[var(--accent)]">{changeError}</p>
                )}

                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={() => {
                      setExpanded(false);
                      setNewProvider("");
                      setApiKey("");
                      setConfirmText("");
                      setChangeError(null);
                      setEmbeddingProbe(null);
                    }}
                    className="font-mono text-[10px] text-muted transition-colors hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleChange}
                    disabled={changing || confirmText !== "RESET" || !newProvider || !hasEmbeddingCredential(newProvider)}
                    className="rounded-sm bg-[var(--accent)] px-4 py-1.5 font-mono text-xs font-medium text-white transition-opacity disabled:opacity-20"
                  >
                    {changing ? "Rebuilding..." : "Reset & Rebuild"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
