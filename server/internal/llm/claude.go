package llm

import (
	"context"
	"encoding/json"
	"fmt"
)

const claudeAPI = "https://api.anthropic.com/v1/messages"

type claude struct {
	model  string
	apiKey string
}

func newClaude(model, apiKey string) *claude {
	if model == "" {
		model = "claude-sonnet-4-20250514"
	}
	return &claude{model: model, apiKey: apiKey}
}

func (c *claude) Provider() string { return "claude" }

func (c *claude) Complete(ctx context.Context, prompt, system string) (string, error) {
	body := map[string]any{
		"model":      c.model,
		"max_tokens": 4096,
		"messages":   []map[string]string{{"role": "user", "content": prompt}},
	}
	if system != "" {
		body["system"] = system
	}

	respData, err := httpDo(ctx, "POST", claudeAPI, map[string]string{
		"x-api-key":         c.apiKey,
		"anthropic-version": "2023-06-01",
	}, body)
	if err != nil {
		return "", fmt.Errorf("claude: %w", err)
	}

	var resp struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
	}
	if err := json.Unmarshal(respData, &resp); err != nil {
		return "", fmt.Errorf("claude parse: %w", err)
	}
	if len(resp.Content) == 0 {
		return "", fmt.Errorf("claude: empty response")
	}
	return resp.Content[0].Text, nil
}

func (c *claude) CompleteJSON(ctx context.Context, prompt, system string) (map[string]any, error) {
	text, err := c.Complete(ctx, prompt, system)
	if err != nil {
		return nil, err
	}
	return extractJSON(text)
}
