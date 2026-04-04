package projection

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/llm"
)

// ClusterOverview holds a generated label and summary for a cluster.
type ClusterOverview struct {
	ClusterID   int    `json:"cluster_id"`
	Label       string `json:"label"`
	Summary     string `json:"summary"`
	EngramCount int    `json:"engram_count"`
	UpdatedAt   string `json:"updated_at"`
}

const clusterSystemPrompt = `You are a knowledge clustering engine. Given a list of concepts in a thematic cluster, generate:
1. A concise label (2-4 words) for the cluster theme
2. A paragraph summary (50-150 words) describing the theme, key concepts, and how they relate

Respond in JSON: {"label": "...", "summary": "..."}`

// SynthesizeClusterOverviews generates labels and summaries for all clusters.
func SynthesizeClusterOverviews(ctx context.Context, database *db.DB, llmClient llm.Client) (int, error) {
	rows, err := database.Query(
		"SELECT DISTINCT cluster_id FROM projections WHERE cluster_id IS NOT NULL ORDER BY cluster_id")
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	var clusterIDs []int
	for rows.Next() {
		var cid int
		if err := rows.Scan(&cid); err != nil {
			continue
		}
		clusterIDs = append(clusterIDs, cid)
	}

	if len(clusterIDs) == 0 {
		return 0, nil
	}

	count := 0
	for _, cid := range clusterIDs {
		if err := synthesizeOne(ctx, database, llmClient, cid); err != nil {
			log.Printf("[cluster-synthesis] cluster %d: %v", cid, err)
			continue
		}
		count++
	}

	if count > 0 {
		log.Printf("[cluster-synthesis] synthesized %d cluster overviews", count)
	}
	return count, nil
}

func synthesizeOne(ctx context.Context, database *db.DB, llmClient llm.Client, clusterID int) error {
	rows, err := database.Query(
		`SELECT e.canonical_name, e.description
		FROM engrams e JOIN projections p ON e.id = p.engram_id
		WHERE p.cluster_id = ? LIMIT 50`, clusterID)
	if err != nil {
		return err
	}
	defer rows.Close()

	var concepts []string
	engramCount := 0
	for rows.Next() {
		var name string
		var desc *string
		if err := rows.Scan(&name, &desc); err != nil {
			continue
		}
		engramCount++
		if desc != nil && *desc != "" {
			concepts = append(concepts, fmt.Sprintf("- %s: %s", name, *desc))
		} else {
			concepts = append(concepts, fmt.Sprintf("- %s", name))
		}
	}

	if engramCount == 0 {
		return nil
	}

	prompt := fmt.Sprintf("Cluster of %d concepts:\n%s", engramCount, strings.Join(concepts, "\n"))

	response, err := llmClient.Complete(ctx, prompt, clusterSystemPrompt)
	if err != nil {
		return fmt.Errorf("llm: %w", err)
	}

	// Parse JSON response
	var result struct {
		Label   string `json:"label"`
		Summary string `json:"summary"`
	}
	// Try to extract JSON from the response
	response = strings.TrimSpace(response)
	if err := json.Unmarshal([]byte(response), &result); err != nil {
		// Try to find JSON in the response
		start := strings.Index(response, "{")
		end := strings.LastIndex(response, "}")
		if start >= 0 && end > start {
			if err2 := json.Unmarshal([]byte(response[start:end+1]), &result); err2 != nil {
				return fmt.Errorf("parse response: %w", err2)
			}
		} else {
			return fmt.Errorf("no JSON in response")
		}
	}

	if result.Label == "" {
		result.Label = fmt.Sprintf("Cluster %d", clusterID)
	}
	if result.Summary == "" {
		return fmt.Errorf("empty summary")
	}

	_, err = database.Exec(
		`INSERT OR REPLACE INTO cluster_overviews (cluster_id, label, summary, engram_count, updated_at)
		VALUES (?, ?, ?, ?, ?)`,
		clusterID, result.Label, result.Summary, engramCount, db.Now())
	return err
}

// GetClusterOverviews fetches all stored cluster overviews.
func GetClusterOverviews(database *db.DB) ([]ClusterOverview, error) {
	rows, err := database.Query(
		"SELECT cluster_id, label, summary, engram_count, updated_at FROM cluster_overviews ORDER BY cluster_id")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []ClusterOverview
	for rows.Next() {
		var co ClusterOverview
		if err := rows.Scan(&co.ClusterID, &co.Label, &co.Summary, &co.EngramCount, &co.UpdatedAt); err != nil {
			continue
		}
		out = append(out, co)
	}
	return out, nil
}
