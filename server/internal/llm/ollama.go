package llm

import (
	"context"
	"encoding/json"
	"fmt"
)

type ollama struct {
	model   string
	baseURL string
}

func newOllama(model, baseURL string) *ollama {
	if baseURL == "" {
		baseURL = "http://localhost:11434"
	}
	return &ollama{model: model, baseURL: baseURL}
}

func (o *ollama) Provider() string { return "ollama" }

func (o *ollama) Complete(ctx context.Context, prompt, system string) (string, error) {
	body := map[string]any{
		"model":  o.model,
		"prompt": prompt,
		"stream": false,
	}
	if system != "" {
		body["system"] = system
	}

	respData, err := httpDo(ctx, "POST", o.baseURL+"/api/generate", nil, body)
	if err != nil {
		return "", fmt.Errorf("ollama: %w", err)
	}

	var resp struct {
		Response string `json:"response"`
	}
	if err := json.Unmarshal(respData, &resp); err != nil {
		return "", fmt.Errorf("ollama parse: %w", err)
	}
	return resp.Response, nil
}

func (o *ollama) CompleteJSON(ctx context.Context, prompt, system string) (map[string]any, error) {
	text, err := o.Complete(ctx, prompt, system)
	if err != nil {
		return nil, err
	}
	return extractJSON(text)
}
