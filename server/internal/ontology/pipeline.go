package ontology

import (
	"context"
	"fmt"
	"log"
	"strings"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
	"github.com/junhewk/hypomnema/internal/llm"
)

// churnThreshold: if more than 50% of existing engrams change, fall back to full rebuild.
const churnThreshold = 0.5

// ProcessDocument runs the full ontology pipeline: extract → dedup → link → heat.
func ProcessDocument(ctx context.Context, database *db.DB, llmClient llm.Client, embedder embeddings.Embedder, docID string) error {
	doc, err := database.GetDocument(docID)
	if err != nil {
		return fmt.Errorf("get document: %w", err)
	}
	if doc == nil {
		return fmt.Errorf("document not found: %s", docID)
	}
	if doc.Processed >= 1 {
		return nil // already processed
	}

	log.Printf("[ontology] %s: extracting entities (%d chars)", docID, len(doc.Text))

	// 1. Extract entities via LLM
	text := doc.Text
	if doc.Annotation != nil && *doc.Annotation != "" {
		text += "\n\n" + *doc.Annotation
	}

	entities, tidyTitle, tidyText, err := ExtractEntities(ctx, llmClient, text, doc.SourceType)
	if err != nil {
		return fmt.Errorf("extract entities: %w", err)
	}
	log.Printf("[ontology] %s: extracted %d entities", docID, len(entities))

	// Store tidy results
	if tidyTitle != "" || tidyText != "" {
		database.Exec(`UPDATE documents SET tidy_title = ?, tidy_text = ? WHERE id = ?`,
			db.NilIfEmpty(tidyTitle), db.NilIfEmpty(tidyText), docID)
	}

	// 2. Normalize and resolve synonyms
	names := make([]string, len(entities))
	for i, e := range entities {
		names[i] = NormalizeName(e.Name)
	}
	synonymMap, err := ResolveSynonyms(ctx, llmClient, names)
	if err != nil {
		log.Printf("[ontology] synonym resolution failed, using raw names: %v", err)
		synonymMap = make(map[string]string)
		for _, n := range names {
			synonymMap[n] = n
		}
	}

	// 3. Embed canonical names
	canonicalNames := uniqueValues(synonymMap)
	log.Printf("[ontology] %s: %d canonical names after synonym resolution", docID, len(canonicalNames))
	if len(canonicalNames) == 0 {
		database.Exec(`UPDATE documents SET processed = 1 WHERE id = ?`, docID)
		return nil
	}

	embVecs, err := embedder.Embed(ctx, canonicalNames)
	if err != nil {
		return fmt.Errorf("embed entities: %w", err)
	}
	log.Printf("[ontology] %s: embedded %d names", docID, len(embVecs))

	// 4. Get or create engrams (dedup)
	nameToEmbedding := make(map[string][]float32)
	for i, name := range canonicalNames {
		nameToEmbedding[name] = embVecs[i]
	}

	for i, entity := range entities {
		canonical := synonymMap[names[i]]
		if canonical == "" {
			canonical = names[i]
		}

		engram, err := GetOrCreateEngram(ctx, database, embedder, canonical, entity.Description, nameToEmbedding[canonical])
		if err != nil {
			log.Printf("[ontology] engram error for %q: %v", canonical, err)
			continue
		}

		if err := database.LinkDocumentEngram(docID, engram.ID); err != nil {
			log.Printf("[ontology] link error: %v", err)
		}
	}

	// Mark entities extracted
	database.Exec(`UPDATE documents SET processed = 1 WHERE id = ?`, docID)
	log.Printf("[ontology] %s: engrams created, generating edges", docID)

	// 5. Link: generate edges
	if err := LinkDocument(ctx, database, llmClient, embedder, docID); err != nil {
		return fmt.Errorf("link document: %w", err)
	}

	// 6. Compute heat scores
	if err := ComputeAllHeat(database); err != nil {
		log.Printf("[ontology] heat scoring error: %v", err)
	}

	// 7. Synthesize stale engram articles
	if n, err := SynthesizeStaleArticles(ctx, database, llmClient, 5); err != nil {
		log.Printf("[ontology] article synthesis error: %v", err)
	} else if n > 0 {
		log.Printf("[ontology] synthesized %d engram articles", n)
	}

	// 8. Run lint checks
	if _, err := RunLint(database); err != nil {
		log.Printf("[ontology] lint error: %v", err)
	}

	return nil
}

// ReviseDocument handles incremental reprocessing after a document edit.
// It re-extracts entities, diffs the engram set against existing links,
// and only adds/removes the delta. If churn exceeds 50% of existing
// engrams, falls back to a full nuke-and-rebuild.
func ReviseDocument(ctx context.Context, database *db.DB, llmClient llm.Client, embedder embeddings.Embedder, docID string) error {
	doc, err := database.GetDocument(docID)
	if err != nil {
		return fmt.Errorf("get document: %w", err)
	}
	if doc == nil {
		return fmt.Errorf("document not found: %s", docID)
	}

	// Get existing engram IDs for this document
	existingIDs, err := getDocumentEngramIDs(database, docID)
	if err != nil {
		return fmt.Errorf("get existing engrams: %w", err)
	}

	// No existing engrams → full pipeline
	if len(existingIDs) == 0 {
		log.Printf("[ontology] revise %s: no existing engrams, using full pipeline", docID)
		database.Exec(`UPDATE documents SET processed = 0 WHERE id = ?`, docID)
		return ProcessDocument(ctx, database, llmClient, embedder, docID)
	}

	// Re-extract entities from current text
	text := doc.Text
	if doc.Annotation != nil && *doc.Annotation != "" {
		text += "\n\n" + *doc.Annotation
	}

	entities, tidyTitle, tidyText, err := ExtractEntities(ctx, llmClient, text, doc.SourceType)
	if err != nil {
		return fmt.Errorf("extract entities: %w", err)
	}

	// Normalize and resolve synonyms
	names := make([]string, len(entities))
	for i, e := range entities {
		names[i] = NormalizeName(e.Name)
	}
	synonymMap, err := ResolveSynonyms(ctx, llmClient, names)
	if err != nil {
		log.Printf("[ontology] synonym resolution failed, using raw names: %v", err)
		synonymMap = make(map[string]string)
		for _, n := range names {
			synonymMap[n] = n
		}
	}

	// Embed and get-or-create engrams
	canonicalNames := uniqueValues(synonymMap)
	var newIDs map[string]bool
	if len(canonicalNames) > 0 {
		embVecs, err := embedder.Embed(ctx, canonicalNames)
		if err != nil {
			return fmt.Errorf("embed entities: %w", err)
		}

		nameToEmb := make(map[string][]float32)
		for i, name := range canonicalNames {
			nameToEmb[name] = embVecs[i]
		}

		newIDs = make(map[string]bool)
		for i, entity := range entities {
			canonical := synonymMap[names[i]]
			if canonical == "" {
				canonical = names[i]
			}
			engram, err := GetOrCreateEngram(ctx, database, embedder, canonical, entity.Description, nameToEmb[canonical])
			if err != nil {
				log.Printf("[ontology] engram error for %q: %v", canonical, err)
				continue
			}
			newIDs[engram.ID] = true
		}
	} else {
		newIDs = make(map[string]bool)
	}

	// Compute diff
	added := setDiff(newIDs, existingIDs)
	removed := setDiff(existingIDs, newIDs)
	churn := len(added) + len(removed)

	// High churn → full nuke-and-rebuild
	existingCount := len(existingIDs)
	if existingCount == 0 {
		existingCount = 1
	}
	if float64(churn) > churnThreshold*float64(existingCount) {
		log.Printf("[ontology] revise %s: high churn (%d/%d), falling back to full rebuild", docID, churn, len(existingIDs))
		removeDocumentAssociations(database, docID)
		database.Exec(`UPDATE documents SET processed = 0 WHERE id = ?`, docID)
		return ProcessDocument(ctx, database, llmClient, embedder, docID)
	}

	// Apply incremental delta
	tx, err := database.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Remove old links and their edges
	if len(removed) > 0 {
		removedList := setToSlice(removed)
		placeholders := makePlaceholders(len(removedList))
		args := []any{docID}
		for _, id := range removedList {
			args = append(args, id)
		}
		tx.Exec(
			fmt.Sprintf("DELETE FROM document_engrams WHERE document_id = ? AND engram_id IN (%s)", placeholders),
			args...)

		// Delete edges sourced from this doc involving removed engrams
		edgeArgs := []any{docID}
		for _, id := range removedList {
			edgeArgs = append(edgeArgs, id)
		}
		for _, id := range removedList {
			edgeArgs = append(edgeArgs, id)
		}
		tx.Exec(
			fmt.Sprintf("DELETE FROM edges WHERE source_document_id = ? AND (source_engram_id IN (%s) OR target_engram_id IN (%s))",
				placeholders, placeholders),
			edgeArgs...)
	}

	// Add new links
	for id := range added {
		tx.Exec(`INSERT OR IGNORE INTO document_engrams (document_id, engram_id) VALUES (?, ?)`, docID, id)
	}

	// Update tidy fields
	if tidyTitle != "" || tidyText != "" {
		tx.Exec(`UPDATE documents SET tidy_title = ?, tidy_text = ? WHERE id = ?`,
			db.NilIfEmpty(tidyTitle), db.NilIfEmpty(tidyText), docID)
	}

	tx.Exec(`UPDATE documents SET processed = 1 WHERE id = ?`, docID)

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit incremental update: %w", err)
	}

	log.Printf("[ontology] revise %s: incremental update — added %d, removed %d engrams", docID, len(added), len(removed))

	// Generate edges for newly added engrams
	if err := LinkDocument(ctx, database, llmClient, embedder, docID); err != nil {
		log.Printf("[ontology] revise %s: edge generation error: %v", docID, err)
	}

	// Update heat scores
	if err := ComputeAllHeat(database); err != nil {
		log.Printf("[ontology] heat scoring error: %v", err)
	}

	// Synthesize stale engram articles
	if n, err := SynthesizeStaleArticles(ctx, database, llmClient, 5); err != nil {
		log.Printf("[ontology] article synthesis error: %v", err)
	} else if n > 0 {
		log.Printf("[ontology] synthesized %d engram articles", n)
	}

	// Run lint checks
	if _, err := RunLint(database); err != nil {
		log.Printf("[ontology] lint error: %v", err)
	}

	return nil
}

// getDocumentEngramIDs returns the set of engram IDs linked to a document.
func getDocumentEngramIDs(database *db.DB, docID string) (map[string]bool, error) {
	rows, err := database.Query(`SELECT engram_id FROM document_engrams WHERE document_id = ?`, docID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	ids := make(map[string]bool)
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids[id] = true
	}
	return ids, rows.Err()
}

// removeDocumentAssociations deletes all engram links, edges, and embeddings for a document.
func removeDocumentAssociations(database *db.DB, docID string) {
	database.Exec(`DELETE FROM edges WHERE source_document_id = ?`, docID)
	database.Exec(`DELETE FROM document_engrams WHERE document_id = ?`, docID)
}

// setDiff returns elements in a that are not in b.
func setDiff(a, b map[string]bool) map[string]bool {
	diff := make(map[string]bool)
	for k := range a {
		if !b[k] {
			diff[k] = true
		}
	}
	return diff
}

func setToSlice(s map[string]bool) []string {
	out := make([]string, 0, len(s))
	for k := range s {
		out = append(out, k)
	}
	return out
}

func makePlaceholders(n int) string {
	if n == 0 {
		return ""
	}
	return strings.Repeat("?,", n-1) + "?"
}

func uniqueValues(m map[string]string) []string {
	seen := make(map[string]bool)
	var out []string
	for _, v := range m {
		v = strings.TrimSpace(v)
		if v != "" && !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out
}
