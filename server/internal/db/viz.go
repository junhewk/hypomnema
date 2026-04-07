package db

type ProjectionPoint struct {
	EngramID      string  `json:"engram_id"`
	CanonicalName string  `json:"canonical_name"`
	Description   *string `json:"description"`
	X             float64 `json:"x"`
	Y             float64 `json:"y"`
	Z             float64 `json:"z"`
	ClusterID     *int    `json:"cluster_id"`
}

type Cluster struct {
	ClusterID   int     `json:"cluster_id"`
	EngramCount int     `json:"engram_count"`
	CentroidX   float64 `json:"centroid_x"`
	CentroidY   float64 `json:"centroid_y"`
	CentroidZ   float64 `json:"centroid_z"`
}

type VizEdge struct {
	SourceEngramID string  `json:"source_engram_id"`
	TargetEngramID string  `json:"target_engram_id"`
	Predicate      string  `json:"predicate"`
	Confidence     float64 `json:"confidence"`
}

// GetProjections returns all projection points with engram names.
func (db *DB) GetProjections() ([]ProjectionPoint, error) {
	rows, err := db.Query(`
		SELECT p.engram_id, e.canonical_name, e.description, p.x, p.y, p.z, p.cluster_id
		FROM projections p
		JOIN engrams e ON e.id = p.engram_id
		ORDER BY e.canonical_name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []ProjectionPoint
	for rows.Next() {
		var p ProjectionPoint
		if err := rows.Scan(&p.EngramID, &p.CanonicalName, &p.Description, &p.X, &p.Y, &p.Z, &p.ClusterID); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

// GetClusters computes cluster metadata from projections.
func (db *DB) GetClusters() ([]Cluster, error) {
	rows, err := db.Query(`
		SELECT cluster_id, COUNT(*) as cnt,
		       AVG(x) as cx, AVG(y) as cy, AVG(z) as cz
		FROM projections
		WHERE cluster_id IS NOT NULL
		GROUP BY cluster_id
		ORDER BY cluster_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Cluster
	for rows.Next() {
		var c Cluster
		if err := rows.Scan(&c.ClusterID, &c.EngramCount, &c.CentroidX, &c.CentroidY, &c.CentroidZ); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// GetVizEdges returns edges for visualization overlay.
func (db *DB) GetVizEdges(limit int) ([]VizEdge, error) {
	rows, err := db.Query(`
		SELECT source_engram_id, target_engram_id, predicate, confidence
		FROM edges
		ORDER BY confidence DESC
		LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []VizEdge
	for rows.Next() {
		var e VizEdge
		if err := rows.Scan(&e.SourceEngramID, &e.TargetEngramID, &e.Predicate, &e.Confidence); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// SaveProjections writes projection points, replacing all existing.
func (db *DB) SaveProjections(points []ProjectionPoint) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(`DELETE FROM projections`); err != nil {
		return err
	}

	stmt, err := tx.Prepare(`INSERT INTO projections (engram_id, x, y, z, cluster_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)`)
	if err != nil {
		return err
	}
	defer stmt.Close()

	now := Now()
	for _, p := range points {
		if _, err := stmt.Exec(p.EngramID, p.X, p.Y, p.Z, p.ClusterID, now); err != nil {
			return err
		}
	}
	return tx.Commit()
}
