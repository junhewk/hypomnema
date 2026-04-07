package ontology

import (
	"context"
	"fmt"
	"strings"
	"unicode"

	"github.com/junhewk/hypomnema/internal/llm"
)

// NormalizeName applies deterministic normalization: lowercase, collapse whitespace, strip trailing punctuation.
func NormalizeName(name string) string {
	name = strings.TrimSpace(name)
	name = collapseWhitespace(name)
	name = strings.ToLower(name)
	name = strings.TrimRightFunc(name, func(r rune) bool {
		return unicode.IsPunct(r) && r != ')' && r != ']'
	})
	return name
}

// ResolveSynonyms asks the LLM to group synonyms and pick canonical forms.
func ResolveSynonyms(ctx context.Context, client llm.Client, names []string) (map[string]string, error) {
	if len(names) <= 1 {
		m := make(map[string]string)
		for _, n := range names {
			m[n] = n
		}
		return m, nil
	}

	prompt := fmt.Sprintf(`Group these entity names by synonymy and pick one canonical form per group.
Return JSON: {"mapping": {"original_name": "canonical_name", ...}}

Names: %v`, names)

	system := "You normalize entity names. Group synonyms, pick the most precise canonical form. Preserve the original language of each name — do NOT translate. For mixed-language names, keep each span in its original language. Return only the JSON mapping."

	result, err := client.CompleteJSON(ctx, prompt, system)
	if err != nil {
		return nil, err
	}

	mapping := make(map[string]string)
	if raw, ok := result["mapping"].(map[string]any); ok {
		for k, v := range raw {
			if s, ok := v.(string); ok {
				mapping[k] = NormalizeName(s)
			}
		}
	}

	// Ensure all input names have a mapping
	for _, n := range names {
		if _, ok := mapping[n]; !ok {
			mapping[n] = n
		}
	}

	return mapping, nil
}

func collapseWhitespace(s string) string {
	var b strings.Builder
	space := false
	for _, r := range s {
		if unicode.IsSpace(r) {
			if !space {
				b.WriteRune(' ')
				space = true
			}
		} else {
			b.WriteRune(r)
			space = false
		}
	}
	return b.String()
}
