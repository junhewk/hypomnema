package ontology

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log"
	"strings"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
)

const similarityThreshold = 0.91

// GetOrCreateEngram implements the multi-stage dedup pipeline:
// exact name → alias index → concept hash → vector similarity → create new.
func GetOrCreateEngram(ctx context.Context, database *db.DB, embedder embeddings.Embedder,
	canonicalName, description string, embedding []float32) (*db.Engram, error) {

	// Stage 1: exact canonical name match
	if e, err := database.FindEngramByName(canonicalName); err != nil {
		return nil, err
	} else if e != nil {
		return e, nil
	}

	// Stage 2: alias index lookup
	for _, alias := range generateAliases(canonicalName) {
		if e, err := database.FindEngramByAlias(alias); err != nil {
			return nil, err
		} else if e != nil {
			return e, nil
		}
	}

	// Stage 3: concept hash
	hash := conceptHash(embedding)
	var existing db.Engram
	err := database.QueryRow(`SELECT id, canonical_name, concept_hash, description, article, article_updated_at, created_at
		FROM engrams WHERE concept_hash = ?`, hash).
		Scan(&existing.ID, &existing.CanonicalName, &existing.ConceptHash, &existing.Description, &existing.Article, &existing.ArticleUpdatedAt, &existing.CreatedAt)
	if err == nil {
		return &existing, nil
	}

	// Stage 4: vector similarity via KNN
	if embedding != nil {
		neighbors, err := database.KNNEngrams(embedding, 5, similarityThreshold)
		if err == nil && len(neighbors) > 0 {
			// Best match above threshold
			e, err := database.GetEngram(neighbors[0].EngramID)
			if err == nil && e != nil {
				return e, nil
			}
		}
	}

	// Stage 5: create new engram
	engram := &db.Engram{
		CanonicalName: canonicalName,
		ConceptHash:   &hash,
		Description:   db.NilIfEmpty(description),
	}
	if err := database.InsertEngram(engram); err != nil {
		return nil, fmt.Errorf("insert engram: %w", err)
	}

	// Store embedding
	if embedding != nil {
		if _, err := database.Exec(`INSERT OR REPLACE INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)`,
			engram.ID, db.SerializeVec(embedding)); err != nil {
			return nil, fmt.Errorf("store embedding for %s: %w", canonicalName, err)
		}
	}

	// Register aliases
	for _, alias := range generateAliases(canonicalName) {
		if err := database.InsertAlias(engram.ID, alias, aliasKind(alias, canonicalName)); err != nil {
			log.Printf("[ontology] alias insert error for %q: %v", alias, err)
		}
	}

	return engram, nil
}

// conceptHash binarizes the embedding (sign pattern) and hashes with SHA-256.
func conceptHash(embedding []float32) string {
	if len(embedding) == 0 {
		return ""
	}
	bits := make([]byte, (len(embedding)+7)/8)
	for i, v := range embedding {
		if v > 0 {
			bits[i/8] |= 1 << (7 - i%8)
		}
	}
	h := sha256.Sum256(bits)
	return hex.EncodeToString(h[:])
}

// generateAliases produces deterministic alias keys for dedup lookup.
func generateAliases(name string) []string {
	aliases := []string{name}

	// Strip parenthetical Latin/other gloss: "name (latin)" → "name"
	if idx := strings.Index(name, "("); idx > 0 {
		stripped := strings.TrimSpace(name[:idx])
		if stripped != "" && stripped != name {
			aliases = append(aliases, stripped)
		}
	}

	// Compact whitespace variant
	compact := strings.Join(strings.Fields(name), "")
	if compact != name {
		aliases = append(aliases, compact)
	}

	return aliases
}

func aliasKind(alias, canonical string) string {
	if alias == canonical {
		return "canonical_name"
	}
	if !strings.Contains(alias, " ") {
		return "compact_whitespace"
	}
	return "stripped_latin_gloss"
}
