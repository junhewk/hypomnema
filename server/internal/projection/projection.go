// Package projection handles UMAP dimensionality reduction, HDBSCAN clustering,
// and gap detection. Uses pure Go implementations — no Python, no CGo beyond SQLite.
package projection

import (
	"fmt"
	"log"
	"math"
	"sort"

	umap "github.com/nozzle/umap-go"
	umaprand "github.com/nozzle/umap-go/rand"

	"github.com/TrevorS/hdbscan"

	"github.com/junhewk/hypomnema/internal/db"
)

// UMAP parameters (matching Python reference)
const (
	umapNNeighbors = 15
	umapMinDist    = 0.1
	umapNComponents = 3
)

// HDBSCAN parameters
const (
	hdbscanMinClusterSize = 5
)

// Gap detection
const (
	gapMinDistance = 0.5
)

type engramEmb struct {
	ID   string
	Name string
	Vec  []float32
}

// GapRegion represents a sparse zone between clusters.
type GapRegion struct {
	X                    float64 `json:"x"`
	Y                    float64 `json:"y"`
	Z                    float64 `json:"z"`
	Radius               float64 `json:"radius"`
	NeighboringClusters []int   `json:"neighboring_clusters"`
}

// Recompute runs UMAP 3D + HDBSCAN + gap detection on all engram embeddings.
func Recompute(database *db.DB) ([]db.ProjectionPoint, error) {
	rows, err := database.Query(`
		SELECT ee.engram_id, e.canonical_name, ee.embedding
		FROM engram_embeddings ee
		JOIN engrams e ON e.id = ee.engram_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var items []engramEmb
	for rows.Next() {
		var id, name string
		var embBytes []byte
		if err := rows.Scan(&id, &name, &embBytes); err != nil {
			return nil, err
		}
		items = append(items, engramEmb{ID: id, Name: name, Vec: db.DeserializeVec(embBytes)})
	}

	n := len(items)
	if n < 2 {
		return nil, fmt.Errorf("need at least 2 engrams for projection, have %d", n)
	}

	// Convert to [][]float64 for UMAP
	data := make([][]float64, n)
	for i, item := range items {
		vec := make([]float64, len(item.Vec))
		for j, v := range item.Vec {
			vec[j] = float64(v)
		}
		data[i] = vec
	}

	// 1. UMAP 3D projection
	log.Printf("[projection] running UMAP on %d engrams (dim=%d)", n, len(data[0]))
	coords3D, err := runUMAP(data)
	if err != nil {
		log.Printf("[projection] UMAP failed, falling back to PCA: %v", err)
		coords3D = fallbackPCA(data)
	}

	// 2. HDBSCAN clustering on the 3D coordinates
	log.Printf("[projection] running HDBSCAN on %d points", len(coords3D))
	labels, err := runHDBSCAN(coords3D)
	if err != nil {
		log.Printf("[projection] HDBSCAN failed, all points unassigned: %v", err)
		labels = make([]int, n)
		for i := range labels {
			labels[i] = -1
		}
	}

	// 3. Build projection points
	points := make([]db.ProjectionPoint, n)
	for i, item := range items {
		var clusterID *int
		if labels[i] >= 0 {
			c := labels[i]
			clusterID = &c
		}
		points[i] = db.ProjectionPoint{
			EngramID:      item.ID,
			CanonicalName: item.Name,
			X:             coords3D[i][0],
			Y:             coords3D[i][1],
			Z:             coords3D[i][2],
			ClusterID:     clusterID,
		}
	}

	// Save projections
	if err := database.SaveProjections(points); err != nil {
		return nil, err
	}

	log.Printf("[projection] saved %d projections", len(points))
	return points, nil
}

// RecomputeGaps computes gap regions from stored projections.
func RecomputeGaps(database *db.DB) ([]GapRegion, error) {
	projections, err := database.GetProjections()
	if err != nil {
		return nil, err
	}
	clusters, err := database.GetClusters()
	if err != nil {
		return nil, err
	}

	if len(projections) == 0 || len(clusters) < 2 {
		return nil, nil
	}

	// Build 3D coordinate array
	coords := make([][]float64, len(projections))
	for i, p := range projections {
		coords[i] = []float64{p.X, p.Y, p.Z}
	}

	return detectGaps(coords, clusters), nil
}

// runUMAP performs UMAP dimensionality reduction to 3D.
func runUMAP(data [][]float64) ([][]float64, error) {
	n := len(data)
	nNeighbors := umapNNeighbors
	if nNeighbors >= n {
		nNeighbors = n - 1
	}
	if nNeighbors < 2 {
		nNeighbors = 2
	}

	opts := umap.DefaultOptions()
	opts.NComponents = umapNComponents
	opts.NNeighbors = nNeighbors
	opts.MinDist = umapMinDist
	opts.Metric = "cosine"
	seed := uint64(42)
	opts.RandSource = umaprand.NewProduction(&seed)

	model := umap.New(opts)
	embedding, err := model.FitTransform(data, nil)
	if err != nil {
		return nil, fmt.Errorf("UMAP fit: %w", err)
	}
	return embedding, nil
}

// runHDBSCAN clusters 3D coordinates. Returns label array (-1 = noise).
func runHDBSCAN(coords [][]float64) ([]int, error) {
	n := len(coords)
	minClusterSize := hdbscanMinClusterSize
	if minClusterSize > max(2, n/3) {
		minClusterSize = max(2, n/3)
	}

	cfg := hdbscan.DefaultConfig()
	cfg.MinClusterSize = minClusterSize
	cfg.Metric = hdbscan.EuclideanMetric{}

	result, err := hdbscan.Cluster(coords, cfg)
	if err != nil {
		return nil, fmt.Errorf("HDBSCAN: %w", err)
	}

	return result.Labels, nil
}

// detectGaps finds sparse regions between cluster centroids.
// For each pair of clusters, computes the midpoint and checks if
// the nearest data point is far enough away to indicate a gap.
func detectGaps(coords [][]float64, clusters []db.Cluster) []GapRegion {
	if len(clusters) < 2 || len(coords) == 0 {
		return nil
	}

	var gaps []GapRegion

	for i := 0; i < len(clusters); i++ {
		for j := i + 1; j < len(clusters); j++ {
			c1, c2 := clusters[i], clusters[j]
			midpoint := [3]float64{
				(c1.CentroidX + c2.CentroidX) / 2,
				(c1.CentroidY + c2.CentroidY) / 2,
				(c1.CentroidZ + c2.CentroidZ) / 2,
			}

			// Find nearest point to midpoint (brute force — fine for <10k points)
			minDist := math.Inf(1)
			for _, c := range coords {
				d := dist3D(midpoint, [3]float64{c[0], c[1], c[2]})
				if d < minDist {
					minDist = d
				}
			}

			if minDist >= gapMinDistance {
				gaps = append(gaps, GapRegion{
					X:                    midpoint[0],
					Y:                    midpoint[1],
					Z:                    midpoint[2],
					Radius:               minDist,
					NeighboringClusters: []int{c1.ClusterID, c2.ClusterID},
				})
			}
		}
	}

	// Sort by radius descending (largest gaps first)
	sort.Slice(gaps, func(i, j int) bool {
		return gaps[i].Radius > gaps[j].Radius
	})

	return gaps
}

// fallbackPCA is a simple 3D projection for when UMAP fails (e.g., too few points).
func fallbackPCA(data [][]float64) [][]float64 {
	n := len(data)
	if n == 0 {
		return nil
	}
	dim := len(data[0])
	if dim < 3 {
		// Pad to 3D
		out := make([][]float64, n)
		for i, row := range data {
			out[i] = make([]float64, 3)
			copy(out[i], row)
		}
		return out
	}

	// Compute mean
	mean := make([]float64, dim)
	for _, row := range data {
		for j, v := range row {
			mean[j] += v
		}
	}
	for j := range mean {
		mean[j] /= float64(n)
	}

	// Project onto 3 well-spaced dimension groups
	stride := dim / 3
	out := make([][]float64, n)
	scale := math.Sqrt(float64(dim) / 3.0)

	for i, row := range data {
		var x, y, z float64
		for j := range dim {
			centered := row[j] - mean[j]
			switch {
			case j < stride:
				x += centered
			case j < 2*stride:
				y += centered
			default:
				z += centered
			}
		}
		out[i] = []float64{x / scale, y / scale, z / scale}
	}

	return out
}

func dist3D(a, b [3]float64) float64 {
	dx := a[0] - b[0]
	dy := a[1] - b[1]
	dz := a[2] - b[2]
	return math.Sqrt(dx*dx + dy*dy + dz*dz)
}

// ComputePageRank runs power iteration on the edge graph.
func ComputePageRank(database *db.DB, damping float64, iterations int) (map[string]float64, error) {
	edges, err := database.GetVizEdges(10000)
	if err != nil {
		return nil, err
	}

	outDegree := make(map[string]float64)
	neighbors := make(map[string][]string)
	nodes := make(map[string]bool)

	for _, e := range edges {
		nodes[e.SourceEngramID] = true
		nodes[e.TargetEngramID] = true
		outDegree[e.SourceEngramID] += e.Confidence
		outDegree[e.TargetEngramID] += e.Confidence
		neighbors[e.SourceEngramID] = append(neighbors[e.SourceEngramID], e.TargetEngramID)
		neighbors[e.TargetEngramID] = append(neighbors[e.TargetEngramID], e.SourceEngramID)
	}

	nf := float64(len(nodes))
	if nf == 0 {
		return map[string]float64{}, nil
	}

	rank := make(map[string]float64)
	for id := range nodes {
		rank[id] = 1.0 / nf
	}

	for range iterations {
		newRank := make(map[string]float64)
		for id := range nodes {
			newRank[id] = (1 - damping) / nf
		}
		for id := range nodes {
			if deg := outDegree[id]; deg > 0 {
				share := damping * rank[id] / deg
				for _, nbr := range neighbors[id] {
					newRank[nbr] += share
				}
			}
		}
		rank = newRank
	}

	return rank, nil
}
