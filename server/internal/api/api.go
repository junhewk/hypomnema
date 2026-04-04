// Package api provides the HTTP API layer.
package api

import (
	"encoding/json"
	"io/fs"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/junhewk/hypomnema/internal/config"
	"github.com/junhewk/hypomnema/internal/crypto"
	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
	"github.com/junhewk/hypomnema/internal/llm"
	"github.com/junhewk/hypomnema/internal/ontology"
	"github.com/junhewk/hypomnema/internal/scheduler"
)

// EmbeddingChangeStatus tracks progress of an embedding provider change.
type EmbeddingChangeStatus struct {
	Status    string `json:"status"` // "idle", "in_progress", "complete", "failed"
	Total     int    `json:"total"`
	Processed int    `json:"processed"`
	Error     string `json:"error,omitempty"`
}

// Server holds all dependencies for the API.
type Server struct {
	DB        *db.DB
	LLM       llm.Client
	Embedder  embeddings.Embedder
	Queue     *ontology.Queue
	Scheduler *scheduler.Scheduler
	Config    *config.Config
	mu        sync.RWMutex           // protects LLM/Embedder hot-swap
	EmbStatus *EmbeddingChangeStatus // embedding change progress
}

// authMiddleware returns a chi middleware that enforces session auth in server mode.
func (s *Server) authMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.Config.IsServer() {
			next.ServeHTTP(w, r)
			return
		}

		path := r.URL.Path
		if strings.HasPrefix(path, "/api/auth/") || path == "/api/health" {
			next.ServeHTTP(w, r)
			return
		}

		// Skip auth if no passphrase configured (covers fresh installs and setup)
		hasPass, _ := s.DB.GetSetting("auth_passphrase_hash")
		if hasPass == "" {
			next.ServeHTTP(w, r)
			return
		}

		cookie, err := r.Cookie("hypomnema_session")
		if err != nil || !crypto.VerifySession(cookie.Value, s.DB.CryptoKey, 30*24*time.Hour) {
			writeJSON(w, 401, map[string]string{"error": "authentication required"})
			return
		}

		next.ServeHTTP(w, r)
	})
}

// NewRouter builds the chi router with all API routes and static file serving.
func NewRouter(s *Server, staticFS fs.FS) http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Compress(5))

	// API routes
	r.Route("/api", func(r chi.Router) {
		r.Use(s.authMiddleware)

		// Auth
		r.Get("/auth/status", s.authStatus)
		r.Post("/auth/setup", s.authSetup)
		r.Post("/auth/login", s.authLogin)
		r.Post("/auth/logout", s.authLogout)

		// Health
		r.Get("/health", s.health)

		// Documents
		r.Get("/documents", s.listDocuments)
		r.Get("/documents/count", s.countDocuments)
		r.Get("/documents/drafts", s.listDrafts)
		r.Post("/documents/scribbles", s.createScribble)
		r.Post("/documents/urls", s.createFromURL)
		r.Post("/documents/files", s.uploadFile)
		r.Get("/documents/{id}", s.getDocument)
		r.Get("/documents/{id}/related", s.getRelatedDocuments)
		r.Get("/documents/{id}/revisions", s.getRevisions)
		r.Patch("/documents/{id}", s.updateDocument)
		r.Delete("/documents/{id}", s.deleteDocument)

		// Engrams
		r.Get("/engrams", s.listEngrams)
		r.Get("/engrams/{id}", s.getEngram)
		r.Get("/engrams/{id}/cluster", s.getEngramCluster)
		r.Post("/engrams/{id}/article/regenerate", s.regenerateArticle)

		// Search
		r.Get("/search/documents", s.searchDocuments)
		r.Get("/search/knowledge", s.searchKnowledge)
		r.Post("/search/synthesize", s.synthesizeSearch)

		// Lint
		r.Get("/lint/issues", s.listLintIssues)
		r.Get("/lint/count", s.lintIssueCount)
		r.Post("/lint/issues/{id}/resolve", s.resolveLintIssue)
		r.Post("/lint/run", s.triggerLint)

		// Feeds
		r.Get("/feeds", s.listFeeds)
		r.Post("/feeds", s.createFeed)
		r.Patch("/feeds/{id}", s.updateFeed)
		r.Delete("/feeds/{id}", s.deleteFeed)

		// Settings
		r.Get("/settings", s.getSettings)
		r.Put("/settings", s.updateSettings)
		r.Post("/settings/setup", s.setupComplete)
		r.Post("/settings/check-connection", s.checkConnection)
		r.Post("/settings/change-embedding", s.changeEmbedding)
		r.Get("/settings/embedding-status", s.embeddingStatus)
		r.Get("/settings/providers", s.listProviders)

		// Visualization
		r.Get("/viz/projections", s.getProjections)
		r.Get("/viz/clusters", s.getClusters)
		r.Get("/viz/gaps", s.getGaps)
		r.Get("/viz/edges", s.getVizEdges)
		r.Post("/viz/recompute", s.recomputeProjections)

		// Backup
		r.Get("/backup", s.downloadBackup)
	})

	// Serve static frontend files with SPA fallback
	if staticFS != nil {
		r.Handle("/*", spaHandler(staticFS))
	}

	return r
}

// JSON helpers

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("[api] json encode error: %v", err)
	}
}

func readJSON(r *http.Request, v any) error {
	defer r.Body.Close()
	return json.NewDecoder(r.Body).Decode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// spaHandler serves static files, falling back to index.html for SPA routes.
func spaHandler(staticFS fs.FS) http.HandlerFunc {
	fileServer := http.FileServer(http.FS(staticFS))
	return func(w http.ResponseWriter, r *http.Request) {
		// Try to serve the actual file first
		path := r.URL.Path
		if path == "/" {
			fileServer.ServeHTTP(w, r)
			return
		}
		// Check if the file exists in the static FS
		f, err := staticFS.Open(strings.TrimPrefix(path, "/"))
		if err == nil {
			f.Close()
			fileServer.ServeHTTP(w, r)
			return
		}
		// File doesn't exist — serve index.html for SPA routing
		r.URL.Path = "/"
		fileServer.ServeHTTP(w, r)
	}
}
