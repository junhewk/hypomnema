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

// ValidPredicates are the allowed relationship types.
var ValidPredicates = map[string]bool{
	"is_a": true, "part_of": true, "related_to": true,
	"contradicts": true, "supports": true, "provides_methodology_for": true,
	"exemplifies": true, "derives_from": true, "influences": true,
	"precedes": true, "co_occurs_with": true, "subsumes": true,
}

const linkerSystem = `You are a knowledge graph edge generator. Given a source concept and candidate target concepts, assign typed predicates.

Valid predicates: is_a, part_of, related_to, contradicts, supports, provides_methodology_for, exemplifies, derives_from, influences, precedes, co_occurs_with, subsumes

Return JSON:
{"edges": [{"target": "target concept name", "predicate": "predicate", "confidence": 0.0-1.0}]}

Rules:
- Only create edges where a meaningful relationship exists
- confidence should reflect how certain the relationship is
- Prefer specific predicates over "related_to"
- Omit weak or uncertain relationships (confidence < 0.3)
- Use concept names exactly as given — do NOT translate them`

// LinkDocument generates edges between engrams linked to a document.
func LinkDocument(ctx context.Context, database *db.DB, llmClient llm.Client, embedder embeddings.Embedder, docID string) error {
	engramSummaries, err := database.GetDocumentEngrams(docID)
	if err != nil {
		return err
	}
	if len(engramSummaries) < 2 {
		database.Exec(`UPDATE documents SET processed = 2 WHERE id = ?`, docID)
		return nil
	}

	for _, es := range engramSummaries {
		// Find neighbors via KNN
		neighbors, err := findNeighbors(database, es.ID, 10, 0.5)
		if err != nil {
			log.Printf("[linker] neighbor search failed for %s: %v", es.CanonicalName, err)
			continue
		}
		if len(neighbors) == 0 {
			continue
		}

		// Ask LLM to assign predicates
		targetNames := make([]string, len(neighbors))
		targetIDs := make(map[string]string) // name → id
		for i, n := range neighbors {
			targetNames[i] = n.CanonicalName
			targetIDs[n.CanonicalName] = n.ID
		}

		edges, err := assignPredicates(ctx, llmClient, es.CanonicalName, targetNames)
		if err != nil {
			log.Printf("[linker] predicate assignment failed for %s: %v", es.CanonicalName, err)
			continue
		}

		for _, edge := range edges {
			targetID, ok := targetIDs[edge.Target]
			if !ok {
				continue
			}
			if !ValidPredicates[edge.Predicate] {
				continue
			}
			docIDPtr := &docID
			database.UpsertEdge(&db.Edge{
				SourceEngramID:   es.ID,
				TargetEngramID:   targetID,
				Predicate:        edge.Predicate,
				Confidence:       edge.Confidence,
				SourceDocumentID: docIDPtr,
			})
		}
	}

	database.Exec(`UPDATE documents SET processed = 2 WHERE id = ?`, docID)
	return nil
}

type neighborResult struct {
	ID            string
	CanonicalName string
}

func findNeighbors(database *db.DB, engramID string, k int, minSim float64) ([]neighborResult, error) {
	// Get the engram's embedding
	var embBytes []byte
	err := database.QueryRow(`SELECT embedding FROM engram_embeddings WHERE engram_id = ?`, engramID).Scan(&embBytes)
	if err != nil {
		return nil, err
	}

	results, err := database.KNNEngrams(db.DeserializeVec(embBytes), k, minSim)
	if err != nil {
		return nil, err
	}

	var out []neighborResult
	for _, r := range results {
		if r.EngramID == engramID {
			continue // skip self
		}
		e, err := database.GetEngram(r.EngramID)
		if err != nil || e == nil {
			continue
		}
		out = append(out, neighborResult{ID: e.ID, CanonicalName: e.CanonicalName})
	}
	return out, nil
}

type proposedEdge struct {
	Target     string  `json:"target"`
	Predicate  string  `json:"predicate"`
	Confidence float64 `json:"confidence"`
}

func assignPredicates(ctx context.Context, client llm.Client, source string, targets []string) ([]proposedEdge, error) {
	prompt := fmt.Sprintf("Source concept: %s\nTarget concepts: %s\n\nAssign predicates.",
		source, strings.Join(targets, ", "))

	result, err := client.CompleteJSON(ctx, prompt, linkerSystem)
	if err != nil {
		return nil, err
	}

	var edges []proposedEdge
	if raw, ok := result["edges"].([]any); ok {
		for _, item := range raw {
			if m, ok := item.(map[string]any); ok {
				e := proposedEdge{
					Target:    toString(m["target"]),
					Predicate: toString(m["predicate"]),
				}
				if c, ok := m["confidence"].(float64); ok {
					e.Confidence = c
				}
				if e.Target != "" && e.Predicate != "" && e.Confidence >= 0.3 {
					edges = append(edges, e)
				}
			}
		}
	}
	return edges, nil
}

