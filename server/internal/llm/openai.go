package llm

import (
	"context"
	"encoding/json"
	"fmt"
)

type openai struct {
	model   string
	apiKey  string
	baseURL string
}

func newOpenAI(model, apiKey, baseURL string) *openai {
	if model == "" {
		model = "gpt-4o"
	}
	if baseURL == "" {
		baseURL = "https://api.openai.com/v1"
	}
	return &openai{model: model, apiKey: apiKey, baseURL: baseURL}
}

func (o *openai) Provider() string { return "openai" }

func (o *openai) Complete(ctx context.Context, prompt, system string) (string, error) {
	messages := []map[string]string{}
	if system != "" {
		messages = append(messages, map[string]string{"role": "system", "content": system})
	}
	messages = append(messages, map[string]string{"role": "user", "content": prompt})

	body := map[string]any{
		"model":    o.model,
		"messages": messages,
	}

	respData, err := httpDo(ctx, "POST", o.baseURL+"/chat/completions", map[string]string{
		"Authorization": "Bearer " + o.apiKey,
	}, body)
	if err != nil {
		return "", fmt.Errorf("openai: %w", err)
	}

	var resp struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(respData, &resp); err != nil {
		return "", fmt.Errorf("openai parse: %w", err)
	}
	if len(resp.Choices) == 0 {
		return "", fmt.Errorf("openai: empty response")
	}
	return resp.Choices[0].Message.Content, nil
}

func (o *openai) CompleteJSON(ctx context.Context, prompt, system string) (map[string]any, error) {
	text, err := o.Complete(ctx, prompt, system)
	if err != nil {
		return nil, err
	}
	return extractJSON(text)
}
