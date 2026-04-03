package llm

import (
	"context"
	"encoding/json"
	"fmt"
)

type google struct {
	model  string
	apiKey string
}

func newGoogle(model, apiKey string) *google {
	if model == "" {
		model = "gemini-2.5-flash"
	}
	return &google{model: model, apiKey: apiKey}
}

func (g *google) Provider() string { return "google" }

func (g *google) Complete(ctx context.Context, prompt, system string) (string, error) {
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s",
		g.model, g.apiKey)

	contents := []map[string]any{
		{"role": "user", "parts": []map[string]string{{"text": prompt}}},
	}
	body := map[string]any{"contents": contents}
	if system != "" {
		body["systemInstruction"] = map[string]any{
			"parts": []map[string]string{{"text": system}},
		}
	}

	respData, err := httpDo(ctx, "POST", url, nil, body)
	if err != nil {
		return "", fmt.Errorf("google: %w", err)
	}

	var resp struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
	}
	if err := json.Unmarshal(respData, &resp); err != nil {
		return "", fmt.Errorf("google parse: %w", err)
	}
	if len(resp.Candidates) == 0 || len(resp.Candidates[0].Content.Parts) == 0 {
		return "", fmt.Errorf("google: empty response")
	}
	return resp.Candidates[0].Content.Parts[0].Text, nil
}

func (g *google) CompleteJSON(ctx context.Context, prompt, system string) (map[string]any, error) {
	text, err := g.Complete(ctx, prompt, system)
	if err != nil {
		return nil, err
	}
	return extractJSON(text)
}
