"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useSettings } from "@/hooks/useSettings";
import type { SettingsUpdatePayload, ProviderInfo } from "@/lib/types";

const PROVIDER_ICONS: Record<string, string> = {
  claude: "A",
  google: "G",
  openai: "O",
  ollama: "~",
};

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

export function SettingsPage() {
  const { settings, providers, isLoading, error: loadError, refresh } = useSettings();

  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [googleKey, setGoogleKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [openaiUrl, setOpenaiUrl] = useState("");

  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setProvider(settings.llm_provider);
    setModel(settings.llm_model);
    setAnthropicKey(settings.anthropic_api_key);
    setGoogleKey(settings.google_api_key);
    setOpenaiKey(settings.openai_api_key);
    setOllamaUrl(settings.ollama_base_url);
    setOpenaiUrl(settings.openai_base_url);
    setDirty(new Set());
  }, [settings]);

  function markDirty(field: string) {
    setDirty((prev) => new Set(prev).add(field));
    setSaveOk(false);
    setSaveError(null);
  }

  function selectProvider(id: string) {
    setProvider(id);
    markDirty("llm_provider");
    const p = providers?.llm.find((l) => l.id === id);
    if (p) {
      setModel(p.default_model);
      markDirty("llm_model");
    }
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

      if (Object.keys(payload).length === 0) return;

      await api.updateSettings(payload);
      setSaveOk(true);
      setDirty(new Set());
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
          <FieldInput
            label="Model"
            value={model}
            onChange={(v) => { setModel(v); markDirty("llm_model"); }}
            placeholder={providers?.llm.find((p) => p.id === provider)?.default_model}
          />

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

      {/* Embedding — read-only "sealed reading" */}
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="font-mono text-[10px] font-bold uppercase tracking-widest text-muted/60">
            Embedding Model
          </h2>
          <span className="rounded-sm bg-[var(--engram)]/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-[var(--engram)]">
            fixed
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>

        <div
          className="animate-fade-up border-l-2 bg-surface-raised py-3 pr-4 pl-4"
          style={{
            borderLeftColor: "var(--engram)",
            animationDelay: "200ms",
          }}
        >
          <div className="grid grid-cols-3 gap-4">
            <div>
              <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">
                Provider
              </span>
              <span className="font-mono text-xs">
                {settings?.embedding_provider}
              </span>
            </div>
            <div>
              <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">
                Model
              </span>
              <span className="font-mono text-xs">
                {settings?.embedding_model}
              </span>
            </div>
            <div>
              <span className="block font-mono text-[10px] uppercase tracking-wider text-muted/50">
                Dim
              </span>
              <span className="font-mono text-xs tabular-nums">
                {settings?.embedding_dim}
              </span>
            </div>
          </div>
          <p className="mt-3 border-t border-border pt-2 font-mono text-[10px] text-muted/40">
            Set via HYPOMNEMA_EMBEDDING_PROVIDER at startup. Changing embedding models
            produces incompatible vectors — requires a fresh database.
          </p>
        </div>
      </section>
    </div>
  );
}
