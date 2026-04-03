package db

import (
	"fmt"
	"math"
	"strings"
)

// ScoredDocument is a search result with relevance score.
type ScoredDocument struct {
	Document
	Score     float64 `json:"score"`
	MatchType string  `json:"match_type"` // "keyword", "semantic", "hybrid"
}

// SearchDocumentsFTS performs FTS5 keyword search with BM25 scoring.
func (db *DB) SearchDocumentsFTS(query string, limit int) ([]ScoredDocument, error) {
	rows, err := db.Query(`
		SELECT d.id, d.source_type, d.title, d.text, d.mime_type, d.source_uri,
		    d.metadata, d.triaged, d.processed, d.revision, d.tidy_title, d.tidy_text,
		    d.tidy_level, d.annotation, d.heat_score, d.heat_tier, d.created_at, d.updated_at,
		    -rank AS score
		FROM documents_fts fts
		JOIN documents d ON d.rowid = fts.rowid
		WHERE documents_fts MATCH ?
		ORDER BY rank
		LIMIT ?`, query, limit)
	if err != nil {
		return nil, fmt.Errorf("fts search: %w", err)
	}
	defer rows.Close()

	var out []ScoredDocument
	for rows.Next() {
		var sd ScoredDocument
		if err := rows.Scan(&sd.ID, &sd.SourceType, &sd.Title, &sd.Text, &sd.MimeType,
			&sd.SourceURI, &sd.Metadata, &sd.Triaged, &sd.Processed, &sd.Revision,
			&sd.TidyTitle, &sd.TidyText, &sd.TidyLevel, &sd.Annotation,
			&sd.HeatScore, &sd.HeatTier, &sd.CreatedAt, &sd.UpdatedAt, &sd.Score); err != nil {
			return nil, err
		}
		sd.MatchType = "keyword"
		out = append(out, sd)
	}
	return out, rows.Err()
}

// SearchDocumentsVec performs vector similarity search via sqlite-vec.
func (db *DB) SearchDocumentsVec(embedding []float32, limit int) ([]ScoredDocument, error) {
	rows, err := db.Query(`
		SELECT de.document_id, de.distance
		FROM document_embeddings de
		WHERE de.embedding MATCH ?
		  AND k = ?
		ORDER BY de.distance`, SerializeVec(embedding), limit)
	if err != nil {
		return nil, fmt.Errorf("vec search: %w", err)
	}
	defer rows.Close()

	type vecResult struct {
		docID    string
		distance float64
	}
	var results []vecResult
	for rows.Next() {
		var r vecResult
		if err := rows.Scan(&r.docID, &r.distance); err != nil {
			return nil, err
		}
		results = append(results, r)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(results) == 0 {
		return nil, nil
	}

	// Batch fetch documents
	placeholders := make([]string, len(results))
	args := make([]any, len(results))
	for i, r := range results {
		placeholders[i] = "?"
		args[i] = r.docID
	}
	docRows, err := db.Query(`
		SELECT id, source_type, title, text, mime_type, source_uri,
		    metadata, triaged, processed, revision, tidy_title, tidy_text,
		    tidy_level, annotation, heat_score, heat_tier, created_at, updated_at
		FROM documents WHERE id IN (`+strings.Join(placeholders, ",")+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer docRows.Close()

	docs, err := scanDocuments(docRows)
	if err != nil {
		return nil, err
	}
	docMap := make(map[string]Document)
	for _, d := range docs {
		docMap[d.ID] = d
	}

	// Build scored results preserving KNN order
	var out []ScoredDocument
	for _, r := range results {
		doc, ok := docMap[r.docID]
		if !ok {
			continue
		}
		out = append(out, ScoredDocument{
			Document:  doc,
			Score:     l2ToCosine(r.distance),
			MatchType: "semantic",
		})
	}
	return out, nil
}

// l2ToCosine converts L2 distance to approximate cosine similarity.
func l2ToCosine(dist float64) float64 {
	return 1.0 - (dist*dist)/2.0
}

// KNNResult is a single KNN search result.
type KNNResult struct {
	EngramID   string
	Similarity float64
}

// KNNEngrams returns the k nearest engrams to the given embedding.
func (db *DB) KNNEngrams(embedding []float32, k int, minSimilarity float64) ([]KNNResult, error) {
	rows, err := db.Query(`
		SELECT engram_id, distance
		FROM engram_embeddings
		WHERE embedding MATCH ?
		  AND k = ?
		ORDER BY distance`, SerializeVec(embedding), k)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []KNNResult
	for rows.Next() {
		var r KNNResult
		var dist float64
		if err := rows.Scan(&r.EngramID, &dist); err != nil {
			return nil, err
		}
		r.Similarity = l2ToCosine(dist)
		if r.Similarity >= minSimilarity {
			out = append(out, r)
		}
	}
	return out, rows.Err()
}

// SerializeVec converts a float32 slice to the binary format sqlite-vec expects.
func SerializeVec(v []float32) []byte {
	buf := make([]byte, len(v)*4)
	for i, f := range v {
		bits := math.Float32bits(f)
		buf[i*4] = byte(bits)
		buf[i*4+1] = byte(bits >> 8)
		buf[i*4+2] = byte(bits >> 16)
		buf[i*4+3] = byte(bits >> 24)
	}
	return buf
}

// DeserializeVec converts the sqlite-vec binary format back to a float32 slice.
func DeserializeVec(b []byte) []float32 {
	n := len(b) / 4
	out := make([]float32, n)
	for i := range n {
		bits := uint32(b[i*4]) | uint32(b[i*4+1])<<8 | uint32(b[i*4+2])<<16 | uint32(b[i*4+3])<<24
		out[i] = math.Float32frombits(bits)
	}
	return out
}
