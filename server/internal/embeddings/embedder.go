// Package embeddings provides a unified interface for text embedding providers.
package embeddings

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Embedder generates vector embeddings from text.
type Embedder interface {
	Embed(ctx context.Context, texts []string) ([][]float32, error)
	Dimension() int
	Provider() string
}

// New creates an embedder for the given provider.
func New(provider, model, apiKey, baseURL string) (Embedder, error) {
	switch provider {
	case "openai":
		return newOpenAIEmbedder(model, apiKey, baseURL), nil
	case "google":
		return newGoogleEmbedder(model, apiKey), nil
	default:
		return nil, fmt.Errorf("unknown embedding provider: %s", provider)
	}
}

// --- OpenAI embeddings ---

type openaiEmbedder struct {
	model   string
	apiKey  string
	baseURL string
	dim     int
}

func newOpenAIEmbedder(model, apiKey, baseURL string) *openaiEmbedder {
	if model == "" {
		model = "text-embedding-3-large"
	}
	if baseURL == "" {
		baseURL = "https://api.openai.com/v1"
	}
	dim := 3072
	if model == "text-embedding-3-small" {
		dim = 1536
	}
	return &openaiEmbedder{model: model, apiKey: apiKey, baseURL: baseURL, dim: dim}
}

func (e *openaiEmbedder) Provider() string { return "openai" }
func (e *openaiEmbedder) Dimension() int   { return e.dim }

func (e *openaiEmbedder) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	body := map[string]any{
		"model": e.model,
		"input": texts,
	}
	data, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "POST", e.baseURL+"/embeddings", bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+e.apiKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("openai embedding HTTP %d: %s", resp.StatusCode, string(respBody))
	}

	var result struct {
		Data []struct {
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, err
	}

	out := make([][]float32, len(result.Data))
	for i, d := range result.Data {
		out[i] = d.Embedding
	}
	return out, nil
}

// --- Google embeddings ---

type googleEmbedder struct {
	model  string
	apiKey string
	dim    int
}

func newGoogleEmbedder(model, apiKey string) *googleEmbedder {
	if model == "" {
		model = "text-embedding-004"
	}
	dim := 768
	return &googleEmbedder{model: model, apiKey: apiKey, dim: dim}
}

func (e *googleEmbedder) Provider() string { return "google" }
func (e *googleEmbedder) Dimension() int   { return e.dim }

func (e *googleEmbedder) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/%s:batchEmbedContents?key=%s",
		e.model, e.apiKey)

	requests := make([]map[string]any, len(texts))
	for i, t := range texts {
		requests[i] = map[string]any{
			"model":   "models/" + e.model,
			"content": map[string]any{"parts": []map[string]string{{"text": t}}},
		}
	}

	body := map[string]any{"requests": requests}
	data, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("google embedding HTTP %d: %s", resp.StatusCode, string(respBody))
	}

	var result struct {
		Embeddings []struct {
			Values []float32 `json:"values"`
		} `json:"embeddings"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, err
	}

	out := make([][]float32, len(result.Embeddings))
	for i, emb := range result.Embeddings {
		out[i] = emb.Values
	}
	return out, nil
}
