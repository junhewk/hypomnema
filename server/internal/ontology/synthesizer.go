package ontology

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/llm"
)

const (
	docBudget        = 2000 // max chars per source doc excerpt
	maxDocs          = 20
	minDocsForArticle = 2
)

const articleSystemPrompt = `You are a knowledge synthesis engine. Given source excerpts about a concept and its relationships in a knowledge graph, write a comprehensive wiki-style article in markdown. The article should:

- Start with a clear definition
- Cover key aspects and relationships mentioned across sources
- Note points of agreement or tension between sources
- Identify open questions or gaps in coverage
- Be factual — only state what the sources support
- Use concise, clear language suitable for a personal research wiki
- Do NOT add headings like "# Title" — the concept name is already shown
- Keep the article between 200-800 words depending on source richness`

type sourceDoc struct {
	title, text, sourceType string
}

type edgeInfo struct {
	predicate, relatedName, direction string
	confidence                        float64
}

// SynthesizeArticle generates a wiki-style article for an engram from its linked documents.
func SynthesizeArticle(ctx context.Context, database *db.DB, llmClient llm.Client, engramID string) (string, error) {
	// Fetch engram
	engram, err := database.GetEngram(engramID)
	if err != nil || engram == nil {
		return "", fmt.Errorf("engram %s not found", engramID)
	}

	// Fetch linked documents
	rows, err := database.Query(`
		SELECT d.title, d.tidy_title, d.text, d.tidy_text, d.source_type
		FROM documents d
		JOIN document_engrams de ON de.document_id = d.id
		WHERE de.engram_id = ?
		ORDER BY d.created_at DESC LIMIT ?`, engramID, maxDocs)
	if err != nil {
		return "", fmt.Errorf("fetch docs: %w", err)
	}
	defer rows.Close()

	var docs []sourceDoc
	for rows.Next() {
		var title, tidyTitle, text, tidyText, srcType *string
		if err := rows.Scan(&title, &tidyTitle, &text, &tidyText, &srcType); err != nil {
			return "", err
		}
		t := db.Deref(tidyTitle, db.Deref(title, "Untitled"))
		tx := db.Deref(tidyText, db.Deref(text, ""))
		st := db.Deref(srcType, "unknown")
		docs = append(docs, sourceDoc{title: t, text: tx, sourceType: st})
	}

	if len(docs) < minDocsForArticle {
		return "", nil // not enough sources
	}

	// Fetch edges for relational context
	edgeRows, err := database.Query(`
		SELECT e.predicate, e.confidence,
			CASE WHEN e.source_engram_id = ? THEN t.canonical_name ELSE s.canonical_name END AS related_name,
			CASE WHEN e.source_engram_id = ? THEN 'outgoing' ELSE 'incoming' END AS direction
		FROM edges e
		JOIN engrams s ON s.id = e.source_engram_id
		JOIN engrams t ON t.id = e.target_engram_id
		WHERE e.source_engram_id = ? OR e.target_engram_id = ?
		ORDER BY e.confidence DESC LIMIT 30`,
		engramID, engramID, engramID, engramID)
	if err != nil {
		return "", fmt.Errorf("fetch edges: %w", err)
	}
	defer edgeRows.Close()

	var edges []edgeInfo
	for edgeRows.Next() {
		var ei edgeInfo
		if err := edgeRows.Scan(&ei.predicate, &ei.confidence, &ei.relatedName, &ei.direction); err != nil {
			continue
		}
		edges = append(edges, ei)
	}

	// Build prompt
	prompt := buildSynthesisPrompt(engram.CanonicalName, db.Deref(engram.Description, ""), docs, edges)

	// Call LLM
	article, err := llmClient.Complete(ctx, prompt, articleSystemPrompt)
	if err != nil {
		return "", fmt.Errorf("llm complete: %w", err)
	}
	article = strings.TrimSpace(article)
	if article == "" {
		return "", fmt.Errorf("empty LLM response for %s", engramID)
	}

	// Store
	if err := database.UpdateEngramArticle(engramID, article); err != nil {
		return "", fmt.Errorf("store article: %w", err)
	}

	log.Printf("[synthesizer] article for '%s' (%d chars from %d docs)", engram.CanonicalName, len(article), len(docs))
	return article, nil
}

// SynthesizeStaleArticles finds engrams with stale/missing articles and regenerates them.
func SynthesizeStaleArticles(ctx context.Context, database *db.DB, llmClient llm.Client, limit int) (int, error) {
	rows, err := database.Query(`
		SELECT e.id, COUNT(de.document_id) AS doc_count
		FROM engrams e
		JOIN document_engrams de ON de.engram_id = e.id
		JOIN documents d ON d.id = de.document_id
		GROUP BY e.id
		HAVING doc_count >= ?
		  AND (e.article IS NULL
		       OR e.article_updated_at IS NULL
		       OR e.article_updated_at < MAX(d.updated_at))
		ORDER BY doc_count DESC
		LIMIT ?`, minDocsForArticle, limit)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	var staleIDs []string
	for rows.Next() {
		var id string
		var count int
		if err := rows.Scan(&id, &count); err != nil {
			continue
		}
		staleIDs = append(staleIDs, id)
	}

	count := 0
	for _, id := range staleIDs {
		if _, err := SynthesizeArticle(ctx, database, llmClient, id); err != nil {
			log.Printf("[synthesizer] failed for %s: %v", id, err)
			continue
		}
		count++
	}
	return count, nil
}

func buildSynthesisPrompt(name, description string, docs []sourceDoc, edges []edgeInfo) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Concept: \"%s\"\n", name)
	if description != "" {
		fmt.Fprintf(&b, "Current description: %s\n", description)
	}

	fmt.Fprintf(&b, "\n## Source Documents (%d)\n\n", len(docs))
	for i, doc := range docs {
		text := doc.text
		if len(text) > docBudget {
			text = text[:docBudget]
		}
		fmt.Fprintf(&b, "### Source %d: %s [%s]\n%s\n\n", i+1, doc.title, doc.sourceType, text)
	}

	if len(edges) > 0 {
		fmt.Fprintf(&b, "\n## Knowledge Graph Relationships (%d)\n\n", len(edges))
		for _, e := range edges {
			if e.direction == "outgoing" {
				fmt.Fprintf(&b, "- %s → %s → %s (confidence: %.0f%%)\n", name, e.predicate, e.relatedName, e.confidence*100)
			} else {
				fmt.Fprintf(&b, "- %s → %s → %s (confidence: %.0f%%)\n", e.relatedName, e.predicate, name, e.confidence*100)
			}
		}
	}

	b.WriteString("\nWrite a comprehensive wiki article about this concept based on the sources above.\n")
	return b.String()
}

