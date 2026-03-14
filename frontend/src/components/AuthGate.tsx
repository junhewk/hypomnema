"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { AuthStatus } from "@/lib/types";

interface AuthGateProps {
  authStatus: AuthStatus;
  onAuthenticated: () => void;
}

export function AuthGate({ authStatus, onAuthenticated }: AuthGateProps) {
  const isSetup = !authStatus.has_passphrase;
  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [shaking, setShaking] = useState(false);

  const strength = passphrase.length === 0 ? 0
    : passphrase.length < 8 ? 1
    : passphrase.length < 12 ? 2
    : 3;

  function triggerShake() {
    setShaking(true);
    setTimeout(() => setShaking(false), 500);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (isSetup && passphrase !== confirm) {
      setError("Passphrases do not match");
      triggerShake();
      return;
    }
    if (passphrase.length < 8) {
      setError("Passphrase must be at least 8 characters");
      triggerShake();
      return;
    }

    setSubmitting(true);
    try {
      if (isSetup) {
        await api.authSetup(passphrase);
      } else {
        await api.authLogin(passphrase);
      }
      onAuthenticated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
      triggerShake();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-gate min-h-screen bg-background flex items-center justify-center relative overflow-hidden">
      {/* Atmospheric radial gradient */}
      <div
        className="pointer-events-none fixed inset-0"
        style={{
          background: "radial-gradient(ellipse 60% 50% at 50% 45%, color-mix(in srgb, var(--accent) 4%, transparent), transparent)",
        }}
      />

      <div className="max-w-sm w-full mx-auto px-4 relative z-10">
        {/* Header */}
        <div className="mb-10 animate-fade-up">
          <h1 className="font-mono text-lg font-bold tracking-tight">hypomnema</h1>
          <div className="mt-2 flex items-center gap-2">
            <div
              className="h-px flex-1"
              style={{ background: "linear-gradient(to right, var(--accent), transparent)" }}
            />
          </div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted/60 mt-2">
            {isSetup ? "set a passphrase to secure this instance" : "authentication required"}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="animate-fade-up"
          style={{
            animationDelay: "100ms",
            animation: shaking ? "auth-shake 0.5s ease" : undefined,
          }}
        >
          {/* Passphrase field */}
          <div
            className="border-l-2 bg-surface-raised py-4 pr-4 pl-4 mb-0.5 transition-colors"
            style={{
              borderLeftColor: error ? "var(--processing)" : "var(--accent)",
            }}
          >
            <label className="block">
              <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                Passphrase
              </span>
              <input
                type="password"
                value={passphrase}
                onChange={(e) => { setPassphrase(e.target.value); setError(null); }}
                placeholder={isSetup ? "choose something memorable" : ""}
                autoFocus
                className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/20 focus:border-border-focus"
              />
            </label>
          </div>

          {/* Strength meter (setup only) */}
          {isSetup && (
            <div
              className="flex gap-px mb-0.5 animate-fade-up"
              style={{ animationDelay: "150ms" }}
            >
              {[1, 2, 3].map((level) => (
                <div
                  key={level}
                  className="h-0.5 flex-1 transition-all duration-300"
                  style={{
                    background: passphrase.length === 0
                      ? "var(--border)"
                      : strength >= level
                        ? level === 1 ? "var(--processing)"
                          : level === 2 ? "var(--accent)"
                          : "var(--complete)"
                        : "var(--border)",
                  }}
                />
              ))}
            </div>
          )}

          {/* Confirm field (setup only) */}
          {isSetup && (
            <div
              className="border-l-2 bg-surface-raised py-4 pr-4 pl-4 mb-4 animate-fade-up transition-colors"
              style={{
                borderLeftColor: error ? "var(--processing)" : "var(--accent)",
                animationDelay: "200ms",
              }}
            >
              <label className="block">
                <span className="mb-1.5 block font-mono text-[10px] uppercase tracking-wider text-muted/60">
                  Confirm
                </span>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => { setConfirm(e.target.value); setError(null); }}
                  placeholder="repeat passphrase"
                  className="w-full border-b border-border bg-transparent pb-1.5 font-mono text-sm outline-none transition-colors placeholder:text-muted/20 focus:border-border-focus"
                />
              </label>
            </div>
          )}

          {/* Spacer when not in setup mode */}
          {!isSetup && <div className="mb-4" />}

          {/* Error */}
          {error && (
            <div className="mb-4">
              <p className="font-mono text-[10px] text-red-500">{error}</p>
            </div>
          )}

          {/* Submit */}
          <div
            className="flex items-center justify-between animate-fade-up"
            style={{ animationDelay: isSetup ? "250ms" : "150ms" }}
          >
            <span className="font-mono text-[10px] text-muted/30">
              {isSetup
                ? strength === 0 ? "" : strength === 1 ? "too short" : strength === 2 ? "acceptable" : "strong"
                : ""
              }
            </span>
            <button
              type="submit"
              disabled={submitting || passphrase.length < 8}
              className="group relative rounded-md bg-foreground px-6 py-1.5 font-mono text-xs font-medium text-background transition-all disabled:opacity-20"
            >
              <span className={submitting ? "opacity-0" : ""}>
                {isSetup ? "Set Passphrase" : "Unlock"}
              </span>
              {submitting && (
                <span className="absolute inset-0 flex items-center justify-center">
                  <span
                    className="block h-1 w-1 rounded-full"
                    style={{
                      background: "var(--background)",
                      animation: "pulse-dot 1.2s ease infinite",
                    }}
                  />
                </span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
