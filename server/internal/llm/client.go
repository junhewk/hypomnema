// Package llm provides a unified interface for LLM providers.
// All providers are plain HTTP clients — no SDKs, no heavy deps.
package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client is the interface all LLM providers implement.
type Client interface {
	Complete(ctx context.Context, prompt, system string) (string, error)
	CompleteJSON(ctx context.Context, prompt, system string) (map[string]any, error)
	Provider() string
}

// New creates an LLM client for the given provider.
func New(provider, model, apiKey, baseURL string) (Client, error) {
	switch provider {
	case "claude":
		return newClaude(model, apiKey), nil
	case "google":
		return newGoogle(model, apiKey), nil
	case "openai":
		return newOpenAI(model, apiKey, baseURL), nil
	case "ollama":
		return newOllama(model, baseURL), nil
	default:
		return nil, fmt.Errorf("unknown LLM provider: %s", provider)
	}
}

// httpDo is a shared helper for making JSON HTTP requests.
func httpDo(ctx context.Context, method, url string, headers map[string]string, body any) ([]byte, error) {
	var bodyReader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		bodyReader = bytes.NewReader(data)
	}

	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(respBody))
	}
	return respBody, nil
}

// extractJSON parses a JSON response from LLM text output.
// Handles both raw JSON and markdown-fenced JSON (```json ... ```).
func extractJSON(text string) (map[string]any, error) {
	text = trimJSONFences(text)
	var result map[string]any
	if err := json.Unmarshal([]byte(text), &result); err != nil {
		return nil, fmt.Errorf("parse LLM JSON: %w\nraw: %s", err, text)
	}
	return result, nil
}

func trimJSONFences(s string) string {
	// Strip ```json ... ``` fences
	if len(s) > 7 && s[:7] == "```json" {
		s = s[7:]
	} else if len(s) > 3 && s[:3] == "```" {
		s = s[3:]
	}
	if len(s) > 3 && s[len(s)-3:] == "```" {
		s = s[:len(s)-3]
	}
	// Trim whitespace
	for len(s) > 0 && (s[0] == '\n' || s[0] == '\r' || s[0] == ' ') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == '\n' || s[len(s)-1] == '\r' || s[len(s)-1] == ' ') {
		s = s[:len(s)-1]
	}
	return s
}
