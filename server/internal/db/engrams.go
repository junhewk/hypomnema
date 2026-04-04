package db

import "database/sql"

type Engram struct {
	ID               string  `json:"id"`
	CanonicalName    string  `json:"canonical_name"`
	ConceptHash      *string `json:"concept_hash"`
	Description      *string `json:"description"`
	Article          *string `json:"article,omitempty"`
	ArticleUpdatedAt *string `json:"article_updated_at,omitempty"`
	CreatedAt        string  `json:"created_at"`
}

type Edge struct {
	ID               string  `json:"id"`
	SourceEngramID   string  `json:"source_engram_id"`
	TargetEngramID   string  `json:"target_engram_id"`
	Predicate        string  `json:"predicate"`
	Confidence       float64 `json:"confidence"`
	SourceDocumentID *string `json:"source_document_id"`
	CreatedAt        string  `json:"created_at"`
}

type EngramDetail struct {
	Engram
	Edges     []EdgeWithName `json:"edges"`
	Documents []Document     `json:"documents"`
}

type EdgeWithName struct {
	Edge
	SourceName string `json:"source_name"`
	TargetName string `json:"target_name"`
}

// ListEngrams returns a paginated list of engrams.
func (db *DB) ListEngrams(offset, limit int) ([]Engram, int, error) {
	var total int
	if err := db.QueryRow(`SELECT COUNT(*) FROM engrams`).Scan(&total); err != nil {
		return nil, 0, err
	}

	rows, err := db.Query(`
		SELECT id, canonical_name, concept_hash, description, article, article_updated_at, created_at
		FROM engrams ORDER BY canonical_name LIMIT ? OFFSET ?`, limit, offset)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()

	var out []Engram
	for rows.Next() {
		var e Engram
		if err := rows.Scan(&e.ID, &e.CanonicalName, &e.ConceptHash, &e.Description, &e.Article, &e.ArticleUpdatedAt, &e.CreatedAt); err != nil {
			return nil, 0, err
		}
		out = append(out, e)
	}
	return out, total, rows.Err()
}

// GetEngram fetches a single engram by ID.
func (db *DB) GetEngram(id string) (*Engram, error) {
	var e Engram
	err := db.QueryRow(`SELECT id, canonical_name, concept_hash, description, article, article_updated_at, created_at
		FROM engrams WHERE id = ?`, id).
		Scan(&e.ID, &e.CanonicalName, &e.ConceptHash, &e.Description, &e.Article, &e.ArticleUpdatedAt, &e.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &e, err
}

// GetEngramEdges returns all edges involving this engram, with canonical names.
func (db *DB) GetEngramEdges(engramID string) ([]EdgeWithName, error) {
	rows, err := db.Query(`
		SELECT e.id, e.source_engram_id, e.target_engram_id, e.predicate, e.confidence,
		       e.source_document_id, e.created_at,
		       s.canonical_name, t.canonical_name
		FROM edges e
		JOIN engrams s ON s.id = e.source_engram_id
		JOIN engrams t ON t.id = e.target_engram_id
		WHERE e.source_engram_id = ? OR e.target_engram_id = ?
		ORDER BY e.confidence DESC`, engramID, engramID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []EdgeWithName
	for rows.Next() {
		var ew EdgeWithName
		if err := rows.Scan(&ew.ID, &ew.SourceEngramID, &ew.TargetEngramID, &ew.Predicate,
			&ew.Confidence, &ew.SourceDocumentID, &ew.CreatedAt,
			&ew.SourceName, &ew.TargetName); err != nil {
			return nil, err
		}
		out = append(out, ew)
	}
	return out, rows.Err()
}

// GetEngramDocuments returns all documents linked to this engram.
func (db *DB) GetEngramDocuments(engramID string) ([]Document, error) {
	rows, err := db.Query(`
		SELECT d.id, d.source_type, d.title, d.text, d.mime_type, d.source_uri,
		    d.metadata, d.triaged, d.processed, d.revision, d.tidy_title, d.tidy_text,
		    d.tidy_level, d.annotation, d.heat_score, d.heat_tier, d.created_at, d.updated_at
		FROM documents d
		JOIN document_engrams de ON de.document_id = d.id
		WHERE de.engram_id = ?
		ORDER BY d.created_at DESC`, engramID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanDocuments(rows)
}

// InsertEngram creates a new engram.
func (db *DB) InsertEngram(e *Engram) error {
	if e.ID == "" {
		e.ID = NewID()
	}
	if e.CreatedAt == "" {
		e.CreatedAt = Now()
	}
	_, err := db.Exec(`INSERT INTO engrams (id, canonical_name, concept_hash, description, article, article_updated_at, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)`, e.ID, e.CanonicalName, e.ConceptHash, e.Description, e.Article, e.ArticleUpdatedAt, e.CreatedAt)
	return err
}

// LinkDocumentEngram creates a document-engram association.
func (db *DB) LinkDocumentEngram(docID, engramID string) error {
	_, err := db.Exec(`INSERT OR IGNORE INTO document_engrams (document_id, engram_id) VALUES (?, ?)`,
		docID, engramID)
	return err
}

// UpsertEdge creates or updates an edge.
func (db *DB) UpsertEdge(e *Edge) error {
	if e.ID == "" {
		e.ID = NewID()
	}
	if e.CreatedAt == "" {
		e.CreatedAt = Now()
	}
	_, err := db.Exec(`
		INSERT INTO edges (id, source_engram_id, target_engram_id, predicate, confidence, source_document_id, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(source_engram_id, target_engram_id, predicate) DO UPDATE SET
		    confidence = excluded.confidence,
		    source_document_id = excluded.source_document_id`,
		e.ID, e.SourceEngramID, e.TargetEngramID, e.Predicate, e.Confidence, e.SourceDocumentID, e.CreatedAt)
	return err
}

// FindEngramByName looks up an engram by exact canonical name.
func (db *DB) FindEngramByName(name string) (*Engram, error) {
	var e Engram
	err := db.QueryRow(`SELECT id, canonical_name, concept_hash, description, article, article_updated_at, created_at
		FROM engrams WHERE canonical_name = ?`, name).
		Scan(&e.ID, &e.CanonicalName, &e.ConceptHash, &e.Description, &e.Article, &e.ArticleUpdatedAt, &e.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &e, err
}

// FindEngramByAlias looks up an engram via the alias index.
func (db *DB) FindEngramByAlias(aliasKey string) (*Engram, error) {
	var e Engram
	err := db.QueryRow(`
		SELECT e.id, e.canonical_name, e.concept_hash, e.description, e.article, e.article_updated_at, e.created_at
		FROM engrams e
		JOIN engram_aliases a ON a.engram_id = e.id
		WHERE a.alias_key = ?
		LIMIT 1`, aliasKey).
		Scan(&e.ID, &e.CanonicalName, &e.ConceptHash, &e.Description, &e.Article, &e.ArticleUpdatedAt, &e.CreatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &e, err
}

// UpdateEngramArticle stores a synthesized article for an engram.
func (db *DB) UpdateEngramArticle(engramID, article string) error {
	_, err := db.Exec(`UPDATE engrams SET article = ?, article_updated_at = ? WHERE id = ?`,
		article, Now(), engramID)
	return err
}

// InsertAlias adds an alias key for an engram.
func (db *DB) InsertAlias(engramID, aliasKey, aliasKind string) error {
	_, err := db.Exec(`INSERT OR IGNORE INTO engram_aliases (engram_id, alias_key, alias_kind)
		VALUES (?, ?, ?)`, engramID, aliasKey, aliasKind)
	return err
}
