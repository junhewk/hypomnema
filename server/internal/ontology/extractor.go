package ontology

import (
	"context"
	"fmt"
	"strings"

	"github.com/junhewk/hypomnema/internal/llm"
)

// Entity is a raw extracted entity before dedup.
type Entity struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

const extractionSystem = `You are an ontology extraction engine. Given input text, extract entities: theories, methodologies, phenomena, named concepts, significant people, core ideas.

Return JSON:
{
  "entities": [{"name": "entity name", "description": "brief description"}],
  "tidy_title": "clean title or empty string",
  "tidy_text": "cleaned/summarized text or empty string"
}

Rules:
- Extract 3-20 entities depending on text length
- Use precise, canonical names (e.g., "Bayesian inference" not "bayesian method")
- Descriptions should be 1-2 sentences max
- tidy_title: generate a concise title if the text lacks one
- tidy_text: for URLs/files, generate a TL;DR summary (not a full rewrite)
- Do NOT fabricate information not present in the source text
- Respond in the same language as the source text — do NOT translate
- Preserve entity names, descriptions, tidy_title, and tidy_text in the original language
- For mixed-language text, preserve each span in its original language`

// ExtractEntities calls the LLM to extract entities from document text.
func ExtractEntities(ctx context.Context, client llm.Client, text, sourceType string) ([]Entity, string, string, error) {
	prompt := fmt.Sprintf("Extract entities from this %s:\n\n%s", sourceType, text)

	// Truncate very long texts
	if len(prompt) > 30000 {
		prompt = prompt[:30000] + "\n\n[truncated]"
	}

	result, err := client.CompleteJSON(ctx, prompt, extractionSystem)
	if err != nil {
		return nil, "", "", fmt.Errorf("LLM extraction: %w", err)
	}

	var entities []Entity
	if raw, ok := result["entities"].([]any); ok {
		for _, item := range raw {
			if m, ok := item.(map[string]any); ok {
				e := Entity{
					Name:        toString(m["name"]),
					Description: toString(m["description"]),
				}
				if e.Name != "" {
					entities = append(entities, e)
				}
			}
		}
	}

	tidyTitle := toString(result["tidy_title"])
	tidyText := toString(result["tidy_text"])

	return entities, tidyTitle, tidyText, nil
}

func toString(v any) string {
	if s, ok := v.(string); ok {
		return strings.TrimSpace(s)
	}
	return ""
}
