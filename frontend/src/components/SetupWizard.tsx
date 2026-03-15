"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import {
  BASE_LLM_LABEL,
  BASE_LLM_MODEL,
  BASE_LLM_PROVIDER,
  PROVIDER_ICONS,
} from "@/lib/constants";
import type {
  SetupPayload,
  EmbeddingProviderInfo,
  ProviderInfo,
  ModelOption,
} from "@/lib/types";

const EMBEDDING_PROVIDERS: EmbeddingProviderInfo[] = [
  { id: "local", name: "Local (sentence-transformers)", default_dimension: 384, default_model: "all-MiniLM-L6-v2", requires_key: false },
  { id: "openai", name: "OpenAI Embeddings", default_dimension: 1536, default_model: "text-embedding-3-small", requires_key: true },
  { id: "google", name: "Google Embeddings", default_dimension: 768, default_model: "text-embedding-004", requires_key: true },
];

const LLM_PROVIDERS: ProviderInfo[] = [
  {
    id: "google",
    name: "Google Gemini",
    requires_key: true,
    default_model: BASE_LLM_MODEL,
    models: [
      { id: BASE_LLM_MODEL, name: "Gemini 2.5 Flash" },
      { id: "gemini-3-flash-preview", name: "Gemini 3 Flash Preview" },
      { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro" },
      { id: "gemini-3-pro-preview", name: "Gemini 3 Pro Preview" },
      { id: "gemini-2.5-flash-lite-preview-09-2025", name: "Gemini 2.5 Flash-Lite Preview" },
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    requires_key: true,
    default_model: "gpt-5-mini",
    models: [
      { id: "gpt-5-mini", name: "GPT-5 mini" },
      { id: "gpt-4.1-mini", name: "GPT-4.1 mini" },
      { id: "gpt-4o", name: "GPT-4o" },
    ],
  },
  {
    id: "claude",
    name: "Anthropic Claude",
    requires_key: true,
    default_model: "claude-sonnet-4-20250514",
    models: [
      { id: "claude-sonnet-4-20250514", name: "Claude Sonnet 4" },
      { id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku" },
    ],
  },
  { id: "ollama", name: "Ollama (local)", requires_key: false, default_model: "llama3.1", models: [] },
];

export function SetupWizard({ mode, onComplete }: { mode: string; onComplete: () => void }) {
  const [step, setStep] = useState(1);

  // Step 1 state
  const [embeddingProvider, setEmbeddingProvider] = useState<string>(
    mode === "desktop" ? "openai" : "local"
  );
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [embeddingProbe, setEmbeddingProbe] = useState<string | null>(null);
  const [embeddingProbeTone, setEmbeddingProbeTone] = useState<"info" | "checking" | "success" | "error">("info");
  const [embeddingChecking, setEmbeddingChecking] = useState(false);

  // Step 2 state
  const [llmProvider, setLlmProvider] = useState<string | null>(null);
  const [llmModel, setLlmModel] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [googleKey, setGoogleKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [openaiUrl, setOpenaiUrl] = useState("");
  const [llmProbe, setLlmProbe] = useState<string | null>(null);
  const [llmProbeTone, setLlmProbeTone] = useState<"info" | "checking" | "success" | "error">("info");
  const [llmChecking, setLlmChecking] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedEmbedding = EMBEDDING_PROVIDERS.find((p) => p.id === embeddingProvider);
  const selectedLlm = LLM_PROVIDERS.find((p) => p.id === llmProvider) ?? null;
  const selectedLlmModels = selectedLlm?.models ?? [];
  const needsEmbeddingKey = selectedEmbedding?.requires_key ?? false;

  const canProceedStep1 =
    embeddingProvider && (!needsEmbeddingKey || embeddingApiKey.trim().length > 0);

  async function verifyEmbeddingConnection(providerId = embeddingProvider, key = embeddingApiKey) {
    const selected = EMBEDDING_PROVIDERS.find((item) => item.id === providerId);
    if (!selected) return;
    if (selected.requires_key && !key.trim()) {
      setEmbeddingProbeTone("info");
      setEmbeddingProbe("Add the provider key to verify wiring.");
      return;
    }
    setEmbeddingChecking(true);
    setEmbeddingProbeTone("checking");
    setEmbeddingProbe(`Checking ${selected.default_model}...`);
    try {
      const result = await api.checkConnection({
        kind: "embedding",
        provider: providerId,
        model: selected.default_model,
        openai_api_key: providerId === "openai" ? key : undefined,
        google_api_key: providerId === "google" ? key : undefined,
      });
      setEmbeddingProbeTone("success");
      setEmbeddingProbe(`${result.message}${result.dimension ? ` (${result.dimension}d)` : ""}`);
    } catch (e) {
      setEmbeddingProbeTone("error");
      setEmbeddingProbe(e instanceof Error ? e.message : "Connection check failed");
    } finally {
      setEmbeddingChecking(false);
    }
  }

  function currentLlmKey(providerId: string | null) {
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

  async function verifyLlmConnection(providerId = llmProvider, modelId = llmModel) {
    if (!providerId) return;
    const selected = LLM_PROVIDERS.find((item) => item.id === providerId);
    const effectiveModel = modelId || selected?.default_model || "";
    if (!effectiveModel) {
      setLlmProbeTone("info");
      setLlmProbe("Select a model to verify wiring.");
      return;
    }
    if (providerId !== "ollama" && !currentLlmKey(providerId)) {
      setLlmProbeTone("info");
      setLlmProbe("Add the provider key to verify wiring.");
      return;
    }
    setLlmChecking(true);
    setLlmProbeTone("checking");
    setLlmProbe(`Checking ${effectiveModel}...`);
    try {
      const result = await api.checkConnection({
        kind: "llm",
        provider: providerId,
        model: effectiveModel,
        anthropic_api_key: providerId === "claude" ? anthropicKey : undefined,
        google_api_key: providerId === "google" ? googleKey : undefined,
        openai_api_key: providerId === "openai" ? openaiKey : undefined,
        openai_base_url: providerId === "openai" ? openaiUrl : undefined,
        ollama_base_url: providerId === "ollama" ? ollamaUrl : undefined,
      });
      setLlmProbeTone("success");
      setLlmProbe(result.message);
    } catch (e) {
      setLlmProbeTone("error");
      setLlmProbe(e instanceof Error ? e.message : "Connection check failed");
    } finally {
      setLlmChecking(false);
    }
  }

  async function handleComplete(skipLlm: boolean) {
    setSubmitting(true);
    setError(null);
    try {
      const payload: SetupPayload = {
        embedding_provider: embeddingProvider as "local" | "openai" | "google",
      };

      // Add embedding API key to the right field
      if (embeddingProvider === "openai" && embeddingApiKey) {
        payload.openai_api_key = embeddingApiKey;
      } else if (embeddingProvider === "google" && embeddingApiKey) {
        payload.google_api_key = embeddingApiKey;
      }

      if (!skipLlm && llmProvider) {
        payload.llm_provider = llmProvider;
        payload.llm_model = llmModel || selectedLlm?.default_model;
        if (llmProvider === "claude" && anthropicKey) payload.anthropic_api_key = anthropicKey;
        if (llmProvider === "google" && googleKey) payload.google_api_key = googleKey;
        if (llmProvider === "openai" && openaiKey) payload.openai_api_key = openaiKey;
        if (llmProvider === "openai" && openaiUrl) payload.openai_base_url = openaiUrl;
        if (llmProvider === "ollama" && ollamaUrl) payload.ollama_base_url = ollamaUrl;
      }

      await api.completeSetup(payload);
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="max-w-lg w-full mx-auto px-4">
        {/* Header */}
        <div className="mb-8 animate-fade-up">
          <h1 className="font-mono text-lg font-bold tracking-tight">hypomnema</h1>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted/60 mt-1">
            first-run setup
          </p>
        </div>

        {/* Step indicator */}
        <div className="mb-6 flex items-center gap-2 animate-fade-up" style={{ animationDelay: "50ms" }}>
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted/60">
            step {step} of 2
          </span>
          <div className="h-px flex-1 bg-border" />
          <div className="flex gap-1">
            <div
              className="h-1 w-6 rounded-full transition-colors"
              style={{ background: "var(--accent)" }}
            />
            <div
              className="h-1 w-6 rounded-full transition-colors"
              style={{ background: step === 2 ? "var(--accent)" : "var(--border)" }}
            />
          </div>
        </div>

        {/* Step 1: Embedding Provider */}
        {step === 1 && (
          <div className="animate-fade-up" style={{ animationDelay: "100ms" }}>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
                Embedding Provider
              </h2>
              <div className="h-px flex-1 bg-border" />
            </div>

            <p className="font-mono text-[10px] text-muted/40 mb-4">
              This choice is permanent for this database. Different models produce incompatible vectors.
            </p>

            <div className="flex flex-col gap-px mb-4">
              {EMBEDDING_PROVIDERS.map((p, i) => {
                const isDisabled = p.id === "local" && mode === "desktop";
                const isActive = embeddingProvider === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      if (!isDisabled) {
                        setEmbeddingProvider(p.id);
                        setEmbeddingApiKey("");
                        setEmbeddingProbe(null);
                        void verifyEmbeddingConnection(p.id, "");
                      }
                    }}
                    disabled={isDisabled}
                    className={`animate-fade-up group relative border-l-2 bg-surface-raised py-2.5 pr-4 pl-4 text-left transition-colors ${isDisabled ? "opacity-40 cursor-not-allowed" : "hover:bg-surface"}`}
                    style={{
                      borderLeftColor: isActive && !isDisabled ? "var(--accent)" : "var(--border)",
                      animationDelay: `${(i + 2) * 50}ms`,
                    }}
                  >
                    {isActive && !isDisabled && (
                      <div className="absolute top-2.5 right-3 h-1.5 w-1.5 rounded-full bg-[var(--complete)]" />
                    )}
                    <div className="flex items-center gap-2.5">
                      <span
                        className="flex h-6 w-6 items-center justify-center rounded-sm font-mono text-[10px] font-bold"
                        style={{
                          background: isActive && !isDisabled
                            ? "color-mix(in srgb, var(--accent) 15%, transparent)"
                            : "color-mix(in srgb, var(--muted) 10%, transparent)",
                          color: isActive && !isDisabled ? "var(--accent)" : "var(--muted)",
                        }}
                      >
                        {PROVIDER_ICONS[p.id] ?? "?"}
                      </span>
                      <div>
                        <span className="block font-mono text-xs font-medium">
                          {p.name}
                        </span>
                        <span className="block font-mono text-[10px] text-muted/60">
                          {p.requires_key ? "api key required" : "no api key"} · {p.default_model} · {p.default_dimension}-dim
                        </span>
                        {isDisabled && (
                          <span className="block font-mono text-[10px] text-red-400 mt-0.5">
                            local embeddings not available in desktop build
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* API key input for cloud embedding providers */}
            {needsEmbeddingKey && (
              <div className="animate-fade-up border-l-2 bg-surface-raised py-4 pr-4 pl-4 mb-4" style={{ borderLeftColor: "var(--accent)" }}>
                <label className="block">
                  <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                    {embeddingProvider === "openai" ? "OpenAI" : "Google"} API Key
                  </span>
                  <input
                    type="password"
                    value={embeddingApiKey}
                    onChange={(e) => { setEmbeddingApiKey(e.target.value); setEmbeddingProbe(null); }}
                    placeholder={embeddingProvider === "openai" ? "sk-..." : "AIza..."}
                    className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                  />
                </label>
              </div>
            )}

            <div className="mb-4 flex items-center justify-between">
              <span
                className={`font-mono text-[10px] ${
                  embeddingProbeTone === "success"
                    ? "text-[var(--complete)]"
                    : embeddingProbeTone === "error"
                      ? "text-red-500"
                      : "text-muted/50"
                }`}
              >
                {embeddingProbe ?? ""}
              </span>
              <button
                onClick={() => void verifyEmbeddingConnection()}
                disabled={embeddingChecking}
                className="font-mono text-[10px] uppercase tracking-wider text-muted/60 hover:text-foreground transition-colors disabled:opacity-20"
              >
                {embeddingChecking ? "Checking..." : "Check Wiring"}
              </button>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => setStep(2)}
                disabled={!canProceedStep1}
                className="rounded-md bg-foreground px-6 py-1.5 font-mono text-xs font-medium text-background transition-opacity disabled:opacity-20"
              >
                Next
              </button>
            </div>
          </div>
        )}

        {/* Step 2: LLM Provider */}
        {step === 2 && (
          <div className="animate-fade-up" style={{ animationDelay: "100ms" }}>
            <div className="mb-3 flex items-center gap-2">
              <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
                LLM Provider
              </h2>
              <span className="rounded-sm bg-muted/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted/60">
                optional
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>

            <p className="font-mono text-[10px] text-muted/40 mb-4">
              Powers entity extraction and edge generation. Can be changed later in settings.
            </p>
            <p className="font-mono text-[10px] text-muted/50 mb-4">
              Recommended baseline from the reduced tidy eval: Google Gemini / {BASE_LLM_MODEL}.
            </p>

            <div className="flex flex-col gap-px mb-4">
              {LLM_PROVIDERS.map((p, i) => {
                const isActive = llmProvider === p.id;
                const isRecommended = p.id === BASE_LLM_PROVIDER && p.default_model === BASE_LLM_MODEL;
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      if (isActive) {
                        setLlmProvider(null);
                        setLlmModel("");
                        setLlmProbe(null);
                        return;
                      }
                      setLlmProvider(p.id);
                      setLlmModel(p.default_model);
                      setLlmProbe(null);
                      void verifyLlmConnection(p.id, p.default_model);
                    }}
                    className="animate-fade-up group relative border-l-2 bg-surface-raised py-2.5 pr-4 pl-4 text-left transition-colors hover:bg-surface"
                    style={{
                      borderLeftColor: isActive ? "var(--accent)" : "var(--border)",
                      animationDelay: `${(i + 2) * 50}ms`,
                    }}
                  >
                    {isActive && (
                      <div className="absolute top-2.5 right-3 h-1.5 w-1.5 rounded-full bg-[var(--complete)]" />
                    )}
                    <div className="flex items-center gap-2.5">
                      <span
                        className="flex h-6 w-6 items-center justify-center rounded-sm font-mono text-[10px] font-bold"
                        style={{
                          background: isActive
                            ? "color-mix(in srgb, var(--accent) 15%, transparent)"
                            : "color-mix(in srgb, var(--muted) 10%, transparent)",
                          color: isActive ? "var(--accent)" : "var(--muted)",
                        }}
                      >
                        {PROVIDER_ICONS[p.id] ?? "?"}
                      </span>
                      <div>
                        <span className="block font-mono text-xs font-medium">
                          {p.name}
                          {isRecommended && (
                            <span className="ml-2 rounded-sm bg-muted/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted/60">
                              {BASE_LLM_LABEL}
                            </span>
                          )}
                        </span>
                        <span className="block font-mono text-[10px] text-muted/60">
                          {p.requires_key ? "api key required" : "local"} · {p.default_model}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* LLM API key inputs */}
            {llmProvider && (
              <div className="animate-fade-up border-l-2 bg-surface-raised py-4 pr-4 pl-4 mb-4" style={{ borderLeftColor: "var(--accent)" }}>
                {selectedLlmModels.length > 0 ? (
                  <label className="mb-3 block">
                    <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                      Model
                    </span>
                    <select
                      value={llmModel || selectedLlm?.default_model || ""}
                      onChange={(e) => {
                        setLlmModel(e.target.value);
                        setLlmProbe(null);
                        void verifyLlmConnection(llmProvider, e.target.value);
                      }}
                      className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors focus:border-border-focus"
                    >
                      {selectedLlmModels.map((option: ModelOption) => (
                        <option key={option.id} value={option.id} className="bg-background text-foreground">
                          {option.name} · {option.id}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label className="mb-3 block">
                    <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                      Model
                    </span>
                    <input
                      type="text"
                      value={llmModel}
                      onChange={(e) => { setLlmModel(e.target.value); setLlmProbe(null); }}
                      placeholder={selectedLlm?.default_model}
                      className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                    />
                  </label>
                )}

                {llmProvider === "claude" && (
                  <label className="block">
                    <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                      Anthropic API Key
                    </span>
                    <input
                      type="password"
                      value={anthropicKey}
                      onChange={(e) => { setAnthropicKey(e.target.value); setLlmProbe(null); }}
                      placeholder="sk-ant-..."
                      className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                    />
                  </label>
                )}

                {llmProvider === "google" && (
                  <label className="block">
                    <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                      Google API Key
                    </span>
                    <input
                      type="password"
                      value={googleKey}
                      onChange={(e) => { setGoogleKey(e.target.value); setLlmProbe(null); }}
                      placeholder="AIza..."
                      className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                    />
                  </label>
                )}

                {llmProvider === "openai" && (
                  <>
                    <label className="mb-3 block">
                      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                        OpenAI API Key
                      </span>
                      <input
                        type="password"
                        value={openaiKey}
                        onChange={(e) => { setOpenaiKey(e.target.value); setLlmProbe(null); }}
                        placeholder="sk-..."
                        className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                        Base URL (optional)
                      </span>
                      <input
                        type="text"
                        value={openaiUrl}
                        onChange={(e) => { setOpenaiUrl(e.target.value); setLlmProbe(null); }}
                        placeholder="https://api.openai.com/v1"
                        className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                      />
                    </label>
                  </>
                )}

                {llmProvider === "ollama" && (
                  <label className="block">
                    <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                      Ollama Base URL
                    </span>
                    <input
                      type="text"
                      value={ollamaUrl}
                      onChange={(e) => { setOllamaUrl(e.target.value); setLlmProbe(null); }}
                      placeholder="http://localhost:11434"
                      className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/30 focus:border-border-focus"
                    />
                  </label>
                )}

                <div className="mt-4 flex items-center justify-between">
                  <span
                    className={`font-mono text-[10px] ${
                      llmProbeTone === "success"
                        ? "text-[var(--complete)]"
                        : llmProbeTone === "error"
                          ? "text-red-500"
                          : "text-muted/50"
                    }`}
                  >
                    {llmProbe ?? ""}
                  </span>
                  <button
                    onClick={() => void verifyLlmConnection()}
                    disabled={llmChecking}
                    className="font-mono text-[10px] uppercase tracking-wider text-muted/60 hover:text-foreground transition-colors disabled:opacity-20"
                  >
                    {llmChecking ? "Checking..." : "Check Wiring"}
                  </button>
                </div>
              </div>
            )}

            {/* Error display */}
            {error && (
              <div className="mb-4 animate-fade-up">
                <p className="font-mono text-[10px] text-red-500">{error}</p>
              </div>
            )}

            <div className="flex items-center justify-between">
              <button
                onClick={() => setStep(1)}
                className="font-mono text-[10px] uppercase tracking-wider text-muted/60 hover:text-foreground transition-colors"
              >
                Back
              </button>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => handleComplete(true)}
                  disabled={submitting}
                  className="font-mono text-[10px] uppercase tracking-wider text-muted/60 hover:text-foreground transition-colors disabled:opacity-20"
                >
                  Skip
                </button>
                <button
                  onClick={() => handleComplete(false)}
                  disabled={submitting}
                  className="rounded-md bg-foreground px-6 py-1.5 font-mono text-xs font-medium text-background transition-opacity disabled:opacity-20"
                >
                  {submitting ? "Setting up..." : "Complete Setup"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
