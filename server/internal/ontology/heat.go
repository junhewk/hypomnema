package ontology

import (
	"log"
	"math"
	"time"

	"github.com/junhewk/hypomnema/internal/db"
)

// Heat tier thresholds
const (
	activeThreshold    = 0.35
	referenceThreshold = 0.12
)

// Heat weights
const (
	recencyWeight    = 0.40
	coActivityWeight = 0.35
	revisionWeight   = 0.10
	centralityWeight = 0.15
)

// ComputeAllHeat scores every document and assigns heat tiers.
func ComputeAllHeat(database *db.DB) error {
	rows, err := database.Query(`
		WITH co_act AS (
			SELECT de1.document_id, COUNT(DISTINCT de2.document_id) as co_activity
			FROM document_engrams de1
			JOIN document_engrams de2 ON de2.engram_id = de1.engram_id AND de2.document_id != de1.document_id
			JOIN documents d2 ON d2.id = de2.document_id AND d2.created_at >= datetime('now', '-30 days')
			GROUP BY de1.document_id
		),
		edge_ct AS (
			SELECT de.document_id, COUNT(*) as edge_count
			FROM document_engrams de
			JOIN edges e ON e.source_engram_id = de.engram_id OR e.target_engram_id = de.engram_id
			GROUP BY de.document_id
		)
		SELECT d.id, d.created_at, d.revision,
		       COALESCE(ca.co_activity, 0),
		       COALESCE(ec.edge_count, 0)
		FROM documents d
		LEFT JOIN co_act ca ON ca.document_id = d.id
		LEFT JOIN edge_ct ec ON ec.document_id = d.id
		WHERE d.processed > 0`)
	if err != nil {
		return err
	}
	defer rows.Close()

	now := time.Now().UTC()
	tx, err := database.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	stmt, err := tx.Prepare(`UPDATE documents SET heat_score = ?, heat_tier = ? WHERE id = ?`)
	if err != nil {
		return err
	}
	defer stmt.Close()

	for rows.Next() {
		var id, createdAt string
		var revision, coActivity, edgeCount int
		if err := rows.Scan(&id, &createdAt, &revision, &coActivity, &edgeCount); err != nil {
			return err
		}

		created, err := time.Parse(time.RFC3339, createdAt)
		if err != nil {
			continue
		}

		// Recency: exponential decay, half-life ~23 days
		daysSince := now.Sub(created).Hours() / 24
		recency := math.Exp(-0.03 * daysSince)

		// Co-activity: capped at 5
		coAct := math.Min(float64(coActivity), 5) / 5

		// Revision: capped at 3
		rev := math.Min(float64(revision), 3) / 3

		// Centrality: capped at 10
		cent := math.Min(float64(edgeCount), 10) / 10

		score := recencyWeight*recency + coActivityWeight*coAct + revisionWeight*rev + centralityWeight*cent

		tier := "dormant"
		if score >= activeThreshold {
			tier = "active"
		} else if score >= referenceThreshold {
			tier = "reference"
		}

		if _, err := stmt.Exec(score, tier, id); err != nil {
			log.Printf("[heat] error scoring document %s: %v", id, err)
		}
	}

	return tx.Commit()
}
