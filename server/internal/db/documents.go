package db

import (
	"database/sql"
	"errors"
	"strings"
	"time"
)

type Document struct {
	ID         string  `json:"id"`
	SourceType string  `json:"source_type"`
	Title      *string `json:"title"`
	Text       string  `json:"text"`
	MimeType   *string `json:"mime_type"`
	SourceURI  *string `json:"source_uri"`
	Metadata   *string `json:"metadata"`
	Triaged    int     `json:"triaged"`
	Processed  int     `json:"processed"`
	Revision   int     `json:"revision"`
	TidyTitle  *string `json:"tidy_title"`
	TidyText   *string `json:"tidy_text"`
	TidyLevel  *string `json:"tidy_level"`
	Annotation *string `json:"annotation"`
	HeatScore  *float64 `json:"heat_score"`
	HeatTier   *string `json:"heat_tier"`
	CreatedAt  string  `json:"created_at"`
	UpdatedAt  string  `json:"updated_at"`
}

type EngramSummary struct {
	ID            string `json:"id"`
	CanonicalName string `json:"canonical_name"`
}

// InsertDocument creates a new document.
func (db *DB) InsertDocument(doc *Document) error {
	now := Now()
	if doc.ID == "" {
		doc.ID = NewID()
	}
	doc.CreatedAt = now
	doc.UpdatedAt = now

	_, err := db.Exec(`
		INSERT INTO documents (id, source_type, title, text, mime_type, source_uri,
		    metadata, triaged, processed, revision, annotation, created_at, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		doc.ID, doc.SourceType, doc.Title, doc.Text, doc.MimeType, doc.SourceURI,
		doc.Metadata, doc.Triaged, doc.Processed, doc.Revision, doc.Annotation,
		doc.CreatedAt, doc.UpdatedAt,
	)
	return err
}

// GetDocument fetches a single document by ID.
func (db *DB) GetDocument(id string) (*Document, error) {
	row := db.QueryRow(`SELECT id, source_type, title, text, mime_type, source_uri,
		metadata, triaged, processed, revision, tidy_title, tidy_text, tidy_level,
		annotation, heat_score, heat_tier, created_at, updated_at
		FROM documents WHERE id = ?`, id)
	return scanDocument(row)
}

// ListRecentDocuments returns documents from the last N days, excluding drafts.
func (db *DB) ListRecentDocuments(days int) ([]Document, error) {
	cutoff := time.Now().UTC().AddDate(0, 0, -days).Format(time.RFC3339)
	rows, err := db.Query(`
		SELECT id, source_type, title, text, mime_type, source_uri,
		    metadata, triaged, processed, revision, tidy_title, tidy_text, tidy_level,
		    annotation, heat_score, heat_tier, created_at, updated_at
		FROM documents
		WHERE created_at >= ?
		ORDER BY created_at DESC`, cutoff)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanDocuments(rows)
}

// ListDrafts returns unprocessed scribble documents.
func (db *DB) ListDrafts() ([]Document, error) {
	rows, err := db.Query(`
		SELECT id, source_type, title, text, mime_type, source_uri,
		    metadata, triaged, processed, revision, tidy_title, tidy_text, tidy_level,
		    annotation, heat_score, heat_tier, created_at, updated_at
		FROM documents
		WHERE processed = 0 AND source_type = 'scribble'
		ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanDocuments(rows)
}

// CountDocuments returns total non-draft document count.
func (db *DB) CountDocuments() (int, error) {
	var n int
	err := db.QueryRow(`SELECT COUNT(*) FROM documents WHERE processed > 0 OR source_type != 'scribble'`).Scan(&n)
	return n, err
}

// DeleteDocument removes a document and all its associations.
func (db *DB) DeleteDocument(id string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Remove edges sourced from this document
	if _, err := tx.Exec(`DELETE FROM edges WHERE source_document_id = ?`, id); err != nil {
		return err
	}
	// Remove document-engram links
	if _, err := tx.Exec(`DELETE FROM document_engrams WHERE document_id = ?`, id); err != nil {
		return err
	}
	// Remove document embeddings
	if _, err := tx.Exec(`DELETE FROM document_embeddings WHERE document_id = ?`, id); err != nil {
		// vec table may not exist yet; ignore
	}
	// Remove revisions
	if _, err := tx.Exec(`DELETE FROM document_revisions WHERE document_id = ?`, id); err != nil {
		return err
	}
	// Remove document
	if _, err := tx.Exec(`DELETE FROM documents WHERE id = ?`, id); err != nil {
		return err
	}

	// Clean up orphaned engrams (no document links, no edges)
	if _, err := tx.Exec(`
		DELETE FROM engram_aliases WHERE engram_id IN (
			SELECT e.id FROM engrams e
			LEFT JOIN document_engrams de ON e.id = de.engram_id
			LEFT JOIN edges es ON e.id = es.source_engram_id
			LEFT JOIN edges et ON e.id = et.target_engram_id
			WHERE de.document_id IS NULL AND es.id IS NULL AND et.id IS NULL
		)`); err != nil {
		return err
	}
	if _, err := tx.Exec(`
		DELETE FROM projections WHERE engram_id IN (
			SELECT e.id FROM engrams e
			LEFT JOIN document_engrams de ON e.id = de.engram_id
			LEFT JOIN edges es ON e.id = es.source_engram_id
			LEFT JOIN edges et ON e.id = et.target_engram_id
			WHERE de.document_id IS NULL AND es.id IS NULL AND et.id IS NULL
		)`); err != nil {
		return err
	}
	if _, err := tx.Exec(`
		DELETE FROM engram_embeddings WHERE engram_id IN (
			SELECT e.id FROM engrams e
			LEFT JOIN document_engrams de ON e.id = de.engram_id
			LEFT JOIN edges es ON e.id = es.source_engram_id
			LEFT JOIN edges et ON e.id = et.target_engram_id
			WHERE de.document_id IS NULL AND es.id IS NULL AND et.id IS NULL
		)`); err != nil {
		// vec table may not exist yet
	}
	if _, err := tx.Exec(`
		DELETE FROM engrams WHERE id IN (
			SELECT e.id FROM engrams e
			LEFT JOIN document_engrams de ON e.id = de.engram_id
			LEFT JOIN edges es ON e.id = es.source_engram_id
			LEFT JOIN edges et ON e.id = et.target_engram_id
			WHERE de.document_id IS NULL AND es.id IS NULL AND et.id IS NULL
		)`); err != nil {
		return err
	}

	return tx.Commit()
}

// GetDocumentEngrams returns engram summaries linked to a document.
func (db *DB) GetDocumentEngrams(docID string) ([]EngramSummary, error) {
	rows, err := db.Query(`
		SELECT e.id, e.canonical_name
		FROM engrams e
		JOIN document_engrams de ON de.engram_id = e.id
		WHERE de.document_id = ?
		ORDER BY e.canonical_name`, docID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []EngramSummary
	for rows.Next() {
		var s EngramSummary
		if err := rows.Scan(&s.ID, &s.CanonicalName); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// GetDocumentEngramsBatch returns engram summaries for multiple documents in one query.
func (db *DB) GetDocumentEngramsBatch(docIDs []string) (map[string][]EngramSummary, error) {
	if len(docIDs) == 0 {
		return map[string][]EngramSummary{}, nil
	}
	placeholders := make([]string, len(docIDs))
	args := make([]any, len(docIDs))
	for i, id := range docIDs {
		placeholders[i] = "?"
		args[i] = id
	}
	query := `SELECT de.document_id, e.id, e.canonical_name
		FROM engrams e
		JOIN document_engrams de ON de.engram_id = e.id
		WHERE de.document_id IN (` + strings.Join(placeholders, ",") + `)
		ORDER BY e.canonical_name`

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make(map[string][]EngramSummary)
	for rows.Next() {
		var docID string
		var s EngramSummary
		if err := rows.Scan(&docID, &s.ID, &s.CanonicalName); err != nil {
			return nil, err
		}
		result[docID] = append(result[docID], s)
	}
	return result, rows.Err()
}

// RelatedDocument is a document that shares engrams with another.
type RelatedDocument struct {
	ID    string `json:"id"`
	Title string `json:"title"`
}

// GetRelatedDocuments returns documents sharing engrams with the given document.
func (db *DB) GetRelatedDocuments(docID string) ([]RelatedDocument, error) {
	rows, err := db.Query(`
		SELECT DISTINCT d.id, COALESCE(d.tidy_title, d.title, 'Untitled')
		FROM documents d
		JOIN document_engrams de ON de.document_id = d.id
		WHERE de.engram_id IN (SELECT engram_id FROM document_engrams WHERE document_id = ?)
		  AND d.id != ?
		ORDER BY d.created_at DESC`, docID, docID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []RelatedDocument
	for rows.Next() {
		var r RelatedDocument
		if err := rows.Scan(&r.ID, &r.Title); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// SnapshotAndUpdate snapshots the current state to document_revisions, then applies updates.
func (db *DB) SnapshotAndUpdate(id string, text, title, annotation *string) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Read current state
	var curText, curTitle, curAnnotation sql.NullString
	var curRevision int
	err = tx.QueryRow(`SELECT text, title, annotation, revision FROM documents WHERE id = ?`, id).
		Scan(&curText, &curTitle, &curAnnotation, &curRevision)
	if err != nil {
		return err
	}

	// Snapshot
	now := Now()
	snapID := NewID()
	_, err = tx.Exec(`INSERT INTO document_revisions (id, document_id, revision, text, annotation, title, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)`,
		snapID, id, curRevision, curText.String, curAnnotation.String, curTitle.String, now)
	if err != nil {
		return err
	}

	// Apply update
	if text != nil {
		if _, err := tx.Exec(`UPDATE documents SET text = ?, tidy_text = NULL, tidy_title = NULL, tidy_level = NULL, revision = revision + 1 WHERE id = ?`, *text, id); err != nil {
			return err
		}
	}
	if title != nil {
		if _, err := tx.Exec(`UPDATE documents SET title = ? WHERE id = ?`, *title, id); err != nil {
			return err
		}
	}
	if annotation != nil {
		if _, err := tx.Exec(`UPDATE documents SET annotation = ?, revision = revision + 1 WHERE id = ?`, *annotation, id); err != nil {
			return err
		}
	}

	return tx.Commit()
}

func scanDocument(row *sql.Row) (*Document, error) {
	var d Document
	err := row.Scan(&d.ID, &d.SourceType, &d.Title, &d.Text, &d.MimeType, &d.SourceURI,
		&d.Metadata, &d.Triaged, &d.Processed, &d.Revision, &d.TidyTitle, &d.TidyText,
		&d.TidyLevel, &d.Annotation, &d.HeatScore, &d.HeatTier, &d.CreatedAt, &d.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return &d, err
}

func scanDocuments(rows *sql.Rows) ([]Document, error) {
	var out []Document
	for rows.Next() {
		var d Document
		if err := rows.Scan(&d.ID, &d.SourceType, &d.Title, &d.Text, &d.MimeType, &d.SourceURI,
			&d.Metadata, &d.Triaged, &d.Processed, &d.Revision, &d.TidyTitle, &d.TidyText,
			&d.TidyLevel, &d.Annotation, &d.HeatScore, &d.HeatTier, &d.CreatedAt, &d.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}
