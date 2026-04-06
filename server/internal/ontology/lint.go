package ontology

import (
	"encoding/json"
	"log"
	"sort"

	"github.com/junhewk/hypomnema/internal/db"
)

// Issue type constants.
const (
	IssueOrphan        = "orphan"
	IssueContradiction = "contradiction"
)

// LintIssue represents a knowledge graph quality issue.
type LintIssue struct {
	ID          string   `json:"id"`
	IssueType   string   `json:"issue_type"`
	EngramIDs   []string `json:"engram_ids"`
	Description string   `json:"description"`
	Severity    string   `json:"severity"`
	Resolved    int      `json:"resolved"`
	CreatedAt   string   `json:"created_at,omitempty"`
}

// RunLint executes all SQL-based lint checks and persists new issues.
func RunLint(database *db.DB) ([]LintIssue, error) {
	var issues []LintIssue

	orphans, err := checkOrphans(database)
	if err != nil {
		log.Printf("[lint] orphan check error: %v", err)
	} else {
		issues = append(issues, orphans...)
	}

	contradictions, err := checkContradictions(database)
	if err != nil {
		log.Printf("[lint] contradiction check error: %v", err)
	} else {
		issues = append(issues, contradictions...)
	}

	if len(issues) == 0 {
		return nil, nil
	}

	// Load existing unresolved to dedup
	existing := make(map[string]bool)
	rows, err := database.Query(`SELECT engram_ids, issue_type FROM lint_issues WHERE resolved = 0`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var ids, itype string
			if rows.Scan(&ids, &itype) == nil {
				existing[ids+"|"+itype] = true
			}
		}
	}

	var newIssues []LintIssue
	for _, issue := range issues {
		sorted := make([]string, len(issue.EngramIDs))
		copy(sorted, issue.EngramIDs)
		sort.Strings(sorted)
		idsJSON, _ := json.Marshal(sorted)
		key := string(idsJSON) + "|" + issue.IssueType
		if existing[key] {
			continue
		}
		_, err := database.Exec(
			`INSERT INTO lint_issues (id, issue_type, engram_ids, description, severity, created_at) VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))`,
			db.NewID(), issue.IssueType, string(idsJSON), issue.Description, issue.Severity,
		)
		if err != nil {
			log.Printf("[lint] insert error: %v", err)
			continue
		}
		newIssues = append(newIssues, issue)
	}

	if len(newIssues) > 0 {
		log.Printf("[lint] found %d new issues", len(newIssues))
	}
	return newIssues, nil
}

func checkOrphans(database *db.DB) ([]LintIssue, error) {
	rows, err := database.Query(`
		SELECT e.id, e.canonical_name
		FROM engrams e
		LEFT JOIN edges ed_s ON ed_s.source_engram_id = e.id
		LEFT JOIN edges ed_t ON ed_t.target_engram_id = e.id
		WHERE ed_s.id IS NULL AND ed_t.id IS NULL
		LIMIT 50`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var issues []LintIssue
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			continue
		}
		issues = append(issues, LintIssue{
			IssueType:   IssueOrphan,
			EngramIDs:   []string{id},
			Description: "Engram '" + name + "' has no edges",
			Severity:    "info",
		})
	}
	return issues, nil
}

func checkContradictions(database *db.DB) ([]LintIssue, error) {
	rows, err := database.Query(`
		SELECT e1.source_engram_id, e1.target_engram_id,
		       s.canonical_name AS source_name, t.canonical_name AS target_name
		FROM edges e1
		JOIN edges e2 ON e1.source_engram_id = e2.source_engram_id
		             AND e1.target_engram_id = e2.target_engram_id
		JOIN engrams s ON s.id = e1.source_engram_id
		JOIN engrams t ON t.id = e1.target_engram_id
		WHERE e1.predicate = 'supports' AND e2.predicate = 'contradicts'
		LIMIT 20`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var issues []LintIssue
	for rows.Next() {
		var sid, tid, sname, tname string
		if err := rows.Scan(&sid, &tid, &sname, &tname); err != nil {
			continue
		}
		issues = append(issues, LintIssue{
			IssueType:   IssueContradiction,
			EngramIDs:   []string{sid, tid},
			Description: "'" + sname + "' both supports and contradicts '" + tname + "'",
			Severity:    "error",
		})
	}
	return issues, nil
}

// GetLintIssues fetches lint issues from the database.
func GetLintIssues(database *db.DB, resolved bool, limit int) ([]LintIssue, error) {
	resolvedVal := 0
	if resolved {
		resolvedVal = 1
	}
	rows, err := database.Query(
		`SELECT id, issue_type, engram_ids, description, severity, resolved, created_at
		FROM lint_issues WHERE resolved = ? ORDER BY created_at DESC LIMIT ?`,
		resolvedVal, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []LintIssue
	for rows.Next() {
		var li LintIssue
		var idsJSON string
		if err := rows.Scan(&li.ID, &li.IssueType, &idsJSON, &li.Description, &li.Severity, &li.Resolved, &li.CreatedAt); err != nil {
			continue
		}
		json.Unmarshal([]byte(idsJSON), &li.EngramIDs)
		out = append(out, li)
	}
	return out, nil
}

// ResolveLintIssue marks an issue as resolved.
func ResolveLintIssue(database *db.DB, issueID string) error {
	_, err := database.Exec(`UPDATE lint_issues SET resolved = 1 WHERE id = ? AND resolved = 0`, issueID)
	return err
}

// GetUnresolvedCount returns the number of unresolved lint issues.
func GetUnresolvedCount(database *db.DB) (int, error) {
	var count int
	err := database.QueryRow(`SELECT COUNT(*) FROM lint_issues WHERE resolved = 0`).Scan(&count)
	return count, err
}
