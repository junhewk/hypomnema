package api

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/junhewk/hypomnema/internal/crypto"
	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
	"github.com/junhewk/hypomnema/internal/ingestion"
	"github.com/junhewk/hypomnema/internal/llm"
	"github.com/junhewk/hypomnema/internal/ontology"
	"github.com/junhewk/hypomnema/internal/projection"
)

// --- Health ---

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	setupDone, _ := s.DB.GetSettingBool("setup_complete")
	writeJSON(w, 200, map[string]any{
		"status":      "ok",
		"needs_setup": !setupDone,
		"mode":        s.Config.Mode,
	})
}

// --- Auth ---

func (s *Server) authStatus(w http.ResponseWriter, r *http.Request) {
	hasPass, _ := s.DB.GetSetting("auth_passphrase_hash")

	authenticated := false
	if !s.Config.IsServer() {
		authenticated = true
	} else if cookie, err := r.Cookie("hypomnema_session"); err == nil {
		authenticated = crypto.VerifySession(cookie.Value, s.DB.CryptoKey, 30*24*time.Hour)
	}

	writeJSON(w, 200, map[string]any{
		"auth_required":  s.Config.IsServer(),
		"authenticated":  authenticated,
		"has_passphrase": hasPass != "",
	})
}

func (s *Server) authSetup(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Passphrase string `json:"passphrase"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	existing, _ := s.DB.GetSetting("auth_passphrase_hash")
	if existing != "" {
		writeError(w, 409, "passphrase already configured")
		return
	}

	if len(body.Passphrase) < 8 {
		writeError(w, 400, "passphrase must be at least 8 characters")
		return
	}

	hash, err := crypto.HashPassphrase(body.Passphrase)
	if err != nil {
		writeError(w, 500, "failed to hash passphrase")
		return
	}

	if err := s.DB.SetSetting("auth_passphrase_hash", hash, true); err != nil {
		writeError(w, 500, "failed to store passphrase")
		return
	}

	setSessionCookie(w, s.DB.CryptoKey)
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (s *Server) authLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Passphrase string `json:"passphrase"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	stored, _ := s.DB.GetSetting("auth_passphrase_hash")
	if stored == "" {
		writeError(w, 400, "no passphrase configured")
		return
	}

	ok, err := crypto.VerifyPassphrase(body.Passphrase, stored)
	if err != nil || !ok {
		writeError(w, 401, "invalid passphrase")
		return
	}

	setSessionCookie(w, s.DB.CryptoKey)
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

func (s *Server) authLogout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{
		Name:     "hypomnema_session",
		Value:    "",
		MaxAge:   -1,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		Path:     "/",
	})
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// --- Documents ---

func (s *Server) listDocuments(w http.ResponseWriter, r *http.Request) {
	days := 14
	if d := r.URL.Query().Get("days"); d != "" {
		if n, err := strconv.Atoi(d); err == nil {
			days = n
		}
	}
	docs, err := s.DB.ListRecentDocuments(days)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}

	// Attach engram summaries (batch to avoid N+1)
	type docWithEngrams struct {
		db.Document
		Engrams []db.EngramSummary `json:"engrams"`
	}
	docIDs := make([]string, len(docs))
	for i, d := range docs {
		docIDs[i] = d.ID
	}
	engramMap, _ := s.DB.GetDocumentEngramsBatch(docIDs)

	out := make([]docWithEngrams, len(docs))
	for i, d := range docs {
		out[i] = docWithEngrams{Document: d, Engrams: engramMap[d.ID]}
	}
	writeJSON(w, 200, out)
}

func (s *Server) countDocuments(w http.ResponseWriter, r *http.Request) {
	n, err := s.DB.CountDocuments()
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]int{"total": n})
}

func (s *Server) listDrafts(w http.ResponseWriter, r *http.Request) {
	docs, err := s.DB.ListDrafts()
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, docs)
}

func (s *Server) createScribble(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Text  string `json:"text"`
		Title string `json:"title"`
		Draft bool   `json:"draft"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}
	if body.Text == "" {
		writeError(w, 400, "text is required")
		return
	}

	doc := &db.Document{
		SourceType: "scribble",
		Text:       body.Text,
		Title:      db.NilIfEmpty(body.Title),
	}
	if err := s.DB.InsertDocument(doc); err != nil {
		writeError(w, 500, err.Error())
		return
	}

	if !body.Draft && s.Queue != nil {
		s.Queue.Enqueue(ontology.PipelineJob{DocumentID: doc.ID})
	}

	writeJSON(w, 201, doc)
}

func (s *Server) createFromURL(w http.ResponseWriter, r *http.Request) {
	var body struct {
		URL string `json:"url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	dup, err := ingestion.CheckDuplicateURL(s.DB, body.URL)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	if dup {
		writeError(w, 409, "URL already exists")
		return
	}

	text, title, err := ingestion.FetchURL(r.Context(), body.URL)
	if err != nil {
		writeError(w, 422, err.Error())
		return
	}

	uri := body.URL
	doc := &db.Document{
		SourceType: "url",
		Text:       text,
		Title:      db.NilIfEmpty(title),
		SourceURI:  &uri,
	}
	if err := s.DB.InsertDocument(doc); err != nil {
		writeError(w, 500, err.Error())
		return
	}

	if s.Queue != nil {
		s.Queue.Enqueue(ontology.PipelineJob{DocumentID: doc.ID})
	}
	writeJSON(w, 201, doc)
}

func (s *Server) uploadFile(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeError(w, 400, "invalid multipart form: "+err.Error())
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, 400, "file required")
		return
	}
	defer file.Close()

	data, err := io.ReadAll(file)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}

	parsed, err := ingestion.ParseFile(header.Filename, data)
	if err != nil {
		writeError(w, 422, err.Error())
		return
	}

	doc := &db.Document{
		SourceType: "file",
		Text:       parsed.Text,
		Title:      db.NilIfEmpty(parsed.Title),
		MimeType:   db.NilIfEmpty(parsed.MimeType),
	}
	if err := s.DB.InsertDocument(doc); err != nil {
		writeError(w, 500, err.Error())
		return
	}

	if s.Queue != nil {
		s.Queue.Enqueue(ontology.PipelineJob{DocumentID: doc.ID})
	}
	writeJSON(w, 201, doc)
}

func (s *Server) getDocument(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	doc, err := s.DB.GetDocument(id)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	if doc == nil {
		writeError(w, 404, "not found")
		return
	}
	engrams, _ := s.DB.GetDocumentEngrams(id)
	writeJSON(w, 200, map[string]any{"document": doc, "engrams": engrams})
}

func (s *Server) getRelatedDocuments(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	related, err := s.DB.GetRelatedDocuments(id)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, related)
}

func (s *Server) getRevisions(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	rows, err := s.DB.Query(`SELECT id, document_id, revision, text, annotation, title, created_at
		FROM document_revisions WHERE document_id = ? ORDER BY revision DESC`, id)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	defer rows.Close()

	type revision struct {
		ID         string  `json:"id"`
		DocumentID string  `json:"document_id"`
		Revision   int     `json:"revision"`
		Text       string  `json:"text"`
		Annotation *string `json:"annotation"`
		Title      *string `json:"title"`
		CreatedAt  string  `json:"created_at"`
	}
	var out []revision
	for rows.Next() {
		var rev revision
		if err := rows.Scan(&rev.ID, &rev.DocumentID, &rev.Revision, &rev.Text,
			&rev.Annotation, &rev.Title, &rev.CreatedAt); err != nil {
			writeError(w, 500, err.Error())
			return
		}
		out = append(out, rev)
	}
	writeJSON(w, 200, out)
}

func (s *Server) updateDocument(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	var body struct {
		Text       *string `json:"text"`
		Title      *string `json:"title"`
		Annotation *string `json:"annotation"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	doc, err := s.DB.GetDocument(id)
	if err != nil || doc == nil {
		writeError(w, 404, "not found")
		return
	}

	// Enforce source-type rules
	if doc.SourceType != "scribble" && body.Text != nil {
		writeError(w, 400, "non-scribble text is immutable")
		return
	}
	if doc.SourceType == "scribble" && body.Annotation != nil {
		writeError(w, 400, "scribbles do not have annotations")
		return
	}

	if err := s.DB.SnapshotAndUpdate(id, body.Text, body.Title, body.Annotation); err != nil {
		writeError(w, 500, err.Error())
		return
	}

	if s.Queue != nil {
		s.Queue.Enqueue(ontology.PipelineJob{DocumentID: id, Incremental: true})
	}

	updated, _ := s.DB.GetDocument(id)
	writeJSON(w, 200, updated)
}

func (s *Server) deleteDocument(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if err := s.DB.DeleteDocument(id); err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "deleted"})
}

// --- Engrams ---

func (s *Server) listEngrams(w http.ResponseWriter, r *http.Request) {
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	limit := 20
	if l := r.URL.Query().Get("limit"); l != "" {
		limit, _ = strconv.Atoi(l)
	}

	engrams, total, err := s.DB.ListEngrams(offset, limit)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"items": engrams, "total": total, "offset": offset, "limit": limit})
}

func (s *Server) getEngram(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	engram, err := s.DB.GetEngram(id)
	if err != nil || engram == nil {
		writeError(w, 404, "not found")
		return
	}
	edges, _ := s.DB.GetEngramEdges(id)
	docs, _ := s.DB.GetEngramDocuments(id)
	writeJSON(w, 200, map[string]any{"engram": engram, "edges": edges, "documents": docs})
}

func (s *Server) getEngramCluster(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	docs, err := s.DB.GetEngramDocuments(id)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, docs)
}

func (s *Server) regenerateArticle(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	s.mu.RLock()
	llmClient := s.LLM
	s.mu.RUnlock()
	if llmClient == nil {
		writeError(w, 503, "LLM not configured")
		return
	}
	article, err := ontology.SynthesizeArticle(r.Context(), s.DB, llmClient, id)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"status": "ok", "article": article})
}

// --- Lint ---

func (s *Server) listLintIssues(w http.ResponseWriter, r *http.Request) {
	issues, err := ontology.GetLintIssues(s.DB, false, 100)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	if issues == nil {
		issues = []ontology.LintIssue{}
	}
	writeJSON(w, 200, issues)
}

func (s *Server) lintIssueCount(w http.ResponseWriter, r *http.Request) {
	count, err := ontology.GetUnresolvedCount(s.DB)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]int{"count": count})
}

func (s *Server) resolveLintIssue(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if err := ontology.ResolveLintIssue(s.DB, id); err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "resolved"})
}

func (s *Server) triggerLint(w http.ResponseWriter, r *http.Request) {
	issues, err := ontology.RunLint(s.DB)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"new_issues": len(issues)})
}

// --- Search ---

func (s *Server) searchDocuments(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query().Get("q")
	if q == "" {
		writeJSON(w, 200, []any{})
		return
	}

	// Keyword search
	ftsResults, _ := s.DB.SearchDocumentsFTS(q, 20)

	// Semantic search (if embedder available)
	var vecResults []db.ScoredDocument
	if s.Embedder != nil {
		vecs, err := s.Embedder.Embed(r.Context(), []string{q})
		if err == nil && len(vecs) > 0 {
			vecResults, _ = s.DB.SearchDocumentsVec(vecs[0], 20)
		}
	}

	// RRF fusion
	results := rrfFuse(ftsResults, vecResults)
	writeJSON(w, 200, results)
}

func (s *Server) searchKnowledge(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query().Get("q")
	if q == "" {
		writeJSON(w, 200, []any{})
		return
	}

	// Search engram names
	rows, err := s.DB.Query(`
		SELECT e.id, e.canonical_name, ed.source_engram_id, ed.target_engram_id,
		       ed.predicate, ed.confidence, s.canonical_name, t.canonical_name
		FROM engrams e
		JOIN edges ed ON ed.source_engram_id = e.id OR ed.target_engram_id = e.id
		JOIN engrams s ON s.id = ed.source_engram_id
		JOIN engrams t ON t.id = ed.target_engram_id
		WHERE e.canonical_name LIKE ?
		LIMIT 50`, "%"+q+"%")
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	defer rows.Close()

	type knowledgeResult struct {
		EngramID   string  `json:"engram_id"`
		EngramName string  `json:"engram_name"`
		SourceName string  `json:"source_name"`
		TargetName string  `json:"target_name"`
		Predicate  string  `json:"predicate"`
		Confidence float64 `json:"confidence"`
	}
	var out []knowledgeResult
	for rows.Next() {
		var kr knowledgeResult
		var sourceID, targetID string
		if err := rows.Scan(&kr.EngramID, &kr.EngramName, &sourceID, &targetID,
			&kr.Predicate, &kr.Confidence, &kr.SourceName, &kr.TargetName); err != nil {
			continue
		}
		out = append(out, kr)
	}
	writeJSON(w, 200, out)
}

// rrfFuse combines keyword and semantic results using Reciprocal Rank Fusion.
func rrfFuse(fts, vec []db.ScoredDocument) []db.ScoredDocument {
	const k = 60.0
	scores := make(map[string]float64)
	docs := make(map[string]db.ScoredDocument)

	for i, d := range fts {
		scores[d.ID] += 1.0 / (k + float64(i+1))
		d.MatchType = "keyword"
		docs[d.ID] = d
	}
	for i, d := range vec {
		scores[d.ID] += 1.0 / (k + float64(i+1))
		if _, exists := docs[d.ID]; exists {
			d.MatchType = "hybrid"
		} else {
			d.MatchType = "semantic"
		}
		docs[d.ID] = d
	}

	// Sort by RRF score
	type scored struct {
		doc   db.ScoredDocument
		score float64
	}
	var sorted []scored
	for id, doc := range docs {
		doc.Score = scores[id]
		sorted = append(sorted, scored{doc: doc, score: scores[id]})
	}
	// Simple insertion sort (small N)
	for i := 1; i < len(sorted); i++ {
		for j := i; j > 0 && sorted[j].score > sorted[j-1].score; j-- {
			sorted[j], sorted[j-1] = sorted[j-1], sorted[j]
		}
	}

	out := make([]db.ScoredDocument, len(sorted))
	for i, s := range sorted {
		out[i] = s.doc
	}
	return out
}

func (s *Server) synthesizeSearch(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Query       string   `json:"query"`
		DocumentIDs []string `json:"document_ids"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}
	if body.Query == "" || len(body.DocumentIDs) == 0 {
		writeError(w, 400, "query and document_ids required")
		return
	}

	s.mu.RLock()
	llmClient := s.LLM
	s.mu.RUnlock()
	if llmClient == nil {
		writeError(w, 503, "LLM not configured")
		return
	}

	// Fetch source documents
	ph := make([]string, len(body.DocumentIDs))
	args := make([]any, len(body.DocumentIDs))
	for i, id := range body.DocumentIDs {
		ph[i] = "?"
		args[i] = id
	}
	placeholders := strings.Join(ph, ",")
	rows, err := s.DB.Query(
		`SELECT id, title, tidy_title, text, tidy_text FROM documents WHERE id IN (`+placeholders+`)`, args...)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	defer rows.Close()

	type srcDoc struct {
		title, text string
	}
	var docs []srcDoc
	for rows.Next() {
		var id string
		var title, tidyTitle, text, tidyText *string
		if err := rows.Scan(&id, &title, &tidyTitle, &text, &tidyText); err != nil {
			continue
		}
		t := db.Deref(tidyTitle, db.Deref(title, "Untitled"))
		tx := db.Deref(tidyText, db.Deref(text, ""))
		if len(tx) > 2000 {
			tx = tx[:2000]
		}
		docs = append(docs, srcDoc{title: t, text: tx})
	}

	if len(docs) == 0 {
		writeError(w, 404, "no documents found")
		return
	}

	// Build prompt
	prompt := fmt.Sprintf("Query: \"%s\"\n\n", body.Query)
	for i, doc := range docs {
		prompt += fmt.Sprintf("### Source %d: %s\n%s\n\n", i+1, doc.title, doc.text)
	}
	prompt += "Synthesize a comprehensive answer to the query based on these sources.\n"

	system := "You are a research synthesis engine. Given a query and excerpts from multiple documents, write a clear synthesis in markdown that addresses the query, cites sources by title, notes tensions, and identifies gaps. 200-600 words."

	synthesis, err := llmClient.Complete(r.Context(), prompt, system)
	if err != nil {
		writeError(w, 500, fmt.Sprintf("LLM error: %v", err))
		return
	}

	// Store as new document
	docTitle := "Synthesis: " + body.Query
	if len(docTitle) > 200 {
		docTitle = docTitle[:200]
	}
	newDoc := &db.Document{
		SourceType: "synthesis",
		Title:      &docTitle,
		Text:       synthesis,
	}
	if err := s.DB.InsertDocument(newDoc); err != nil {
		writeError(w, 500, err.Error())
		return
	}

	if s.Queue != nil {
		s.Queue.Enqueue(ontology.PipelineJob{DocumentID: newDoc.ID})
	}

	writeJSON(w, 201, map[string]any{"status": "ok", "document_id": newDoc.ID})
}

// --- Feeds ---

func (s *Server) listFeeds(w http.ResponseWriter, r *http.Request) {
	feeds, err := s.DB.ListFeeds()
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, feeds)
}

func (s *Server) createFeed(w http.ResponseWriter, r *http.Request) {
	var body db.FeedSource
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}
	body.Active = 1
	if err := s.DB.InsertFeed(&body); err != nil {
		writeError(w, 500, err.Error())
		return
	}
	if s.Scheduler != nil && body.Active == 1 {
		if err := s.Scheduler.AddJob(body.ID, body.Schedule); err != nil {
			log.Printf("[api] createFeed: could not schedule job for %s: %v", body.ID, err)
		}
	}
	writeJSON(w, 201, body)
}

func (s *Server) updateFeed(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	var body struct {
		Name     *string `json:"name"`
		URL      *string `json:"url"`
		Schedule *string `json:"schedule"`
		Active   *int    `json:"active"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}
	if err := s.DB.UpdateFeed(id, body.Name, body.URL, body.Schedule, body.Active); err != nil {
		writeError(w, 500, err.Error())
		return
	}
	feed, _ := s.DB.GetFeed(id)
	// Re-register or remove the cron job based on the updated feed state
	if s.Scheduler != nil && feed != nil {
		s.Scheduler.RemoveJob(id)
		if feed.Active == 1 {
			if err := s.Scheduler.AddJob(feed.ID, feed.Schedule); err != nil {
				log.Printf("[api] updateFeed: could not schedule job for %s: %v", id, err)
			}
		}
	}
	writeJSON(w, 200, feed)
}

func (s *Server) deleteFeed(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if s.Scheduler != nil {
		s.Scheduler.RemoveJob(id)
	}
	if err := s.DB.DeleteFeed(id); err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "deleted"})
}

// --- Settings ---

func (s *Server) getSettings(w http.ResponseWriter, r *http.Request) {
	provider, _ := s.DB.GetSetting("llm_provider")
	model, _ := s.DB.GetSetting("llm_model")
	embProvider, _ := s.DB.GetSetting("embedding_provider")
	embModel, _ := s.DB.GetSetting("embedding_model")
	embDim, _ := s.DB.GetSetting("embedding_dim")

	anthropicKey, _ := s.DB.GetSetting("anthropic_api_key")
	googleKey, _ := s.DB.GetSetting("google_api_key")
	openaiKey, _ := s.DB.GetSetting("openai_api_key")

	writeJSON(w, 200, map[string]any{
		"llm_provider":       provider,
		"llm_model":          model,
		"embedding_provider": embProvider,
		"embedding_model":    embModel,
		"embedding_dim":      embDim,
		"anthropic_api_key":  db.MaskedKey(anthropicKey),
		"google_api_key":     db.MaskedKey(googleKey),
		"openai_api_key":     db.MaskedKey(openaiKey),
	})
}

func (s *Server) listProviders(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{
		"llm_providers": []map[string]any{
			{"id": "google", "name": "Google Gemini", "models": []string{"gemini-2.5-flash", "gemini-2.0-flash"}, "default": "gemini-2.5-flash"},
			{"id": "claude", "name": "Anthropic Claude", "models": []string{"claude-sonnet-4-20250514"}, "default": "claude-sonnet-4-20250514"},
			{"id": "openai", "name": "OpenAI", "models": []string{"gpt-4o", "gpt-4o-mini"}, "default": "gpt-4o"},
			{"id": "ollama", "name": "Ollama (local)", "models": []string{}, "default": ""},
		},
		"embedding_providers": []map[string]any{
			{"id": "openai", "name": "OpenAI", "models": []string{"text-embedding-3-small", "text-embedding-3-large"}, "default": "text-embedding-3-small", "dimension": 1536},
			{"id": "google", "name": "Google", "models": []string{"gemini-embedding-001", "text-embedding-004"}, "default": "gemini-embedding-001", "dimension": 3072},
		},
	})
}

func (s *Server) checkConnection(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Kind     string `json:"kind"`
		Provider string `json:"provider"`
		Model    string `json:"model"`
		APIKey   string `json:"api_key"`
		BaseURL  string `json:"base_url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	if body.Kind != "llm" && body.Kind != "embedding" {
		writeError(w, 400, "kind must be 'llm' or 'embedding'")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	if body.Kind == "llm" {
		client, err := llm.New(body.Provider, body.Model, body.APIKey, body.BaseURL)
		if err != nil {
			writeError(w, 400, fmt.Sprintf("failed to create LLM client: %v", err))
			return
		}
		reply, err := client.Complete(ctx, "Reply with exactly: wired.", "You are a connectivity probe.")
		if err != nil {
			writeError(w, 400, fmt.Sprintf("connection failed: %v", err))
			return
		}
		writeJSON(w, 200, map[string]any{
			"status":   "ok",
			"provider": body.Provider,
			"model":    body.Model,
			"reply":    reply,
		})
		return
	}

	// kind == "embedding"
	embedder, err := embeddings.New(body.Provider, body.Model, body.APIKey, body.BaseURL)
	if err != nil {
		writeError(w, 400, fmt.Sprintf("failed to create embedder: %v", err))
		return
	}
	vecs, err := embedder.Embed(ctx, []string{"wired"})
	if err != nil {
		writeError(w, 400, fmt.Sprintf("connection failed: %v", err))
		return
	}
	dim := 0
	if len(vecs) > 0 {
		dim = len(vecs[0])
	}
	writeJSON(w, 200, map[string]any{
		"status":    "ok",
		"provider":  body.Provider,
		"model":     body.Model,
		"dimension": dim,
	})
}

func (s *Server) updateSettings(w http.ResponseWriter, r *http.Request) {
	var body struct {
		LLMProvider   *string `json:"llm_provider"`
		LLMModel      *string `json:"llm_model"`
		AnthropicKey  *string `json:"anthropic_api_key"`
		GoogleKey     *string `json:"google_api_key"`
		OpenAIKey     *string `json:"openai_api_key"`
		OllamaBaseURL *string `json:"ollama_base_url"`
		OpenAIBaseURL *string `json:"openai_base_url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	// Persist each non-nil field
	if body.LLMProvider != nil {
		if err := s.DB.SetSetting("llm_provider", *body.LLMProvider, false); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store llm_provider: %v", err))
			return
		}
	}
	if body.LLMModel != nil {
		if err := s.DB.SetSetting("llm_model", *body.LLMModel, false); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store llm_model: %v", err))
			return
		}
	}
	if body.AnthropicKey != nil {
		if err := s.DB.SetSetting("anthropic_api_key", *body.AnthropicKey, true); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store anthropic_api_key: %v", err))
			return
		}
	}
	if body.GoogleKey != nil {
		if err := s.DB.SetSetting("google_api_key", *body.GoogleKey, true); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store google_api_key: %v", err))
			return
		}
	}
	if body.OpenAIKey != nil {
		if err := s.DB.SetSetting("openai_api_key", *body.OpenAIKey, true); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store openai_api_key: %v", err))
			return
		}
	}
	if body.OllamaBaseURL != nil {
		if err := s.DB.SetSetting("ollama_base_url", *body.OllamaBaseURL, false); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store ollama_base_url: %v", err))
			return
		}
	}
	if body.OpenAIBaseURL != nil {
		if err := s.DB.SetSetting("openai_base_url", *body.OpenAIBaseURL, false); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to store openai_base_url: %v", err))
			return
		}
	}

	// Rebuild LLM client with current settings
	provider, _ := s.DB.GetSetting("llm_provider")
	model, _ := s.DB.GetSetting("llm_model")
	apiKey := s.getProviderKey(provider)
	baseURL, _ := s.DB.GetSetting(provider + "_base_url")

	if provider != "" {
		newClient, err := llm.New(provider, model, apiKey, baseURL)
		if err != nil {
			log.Printf("[settings] warning: could not rebuild LLM client: %v", err)
		} else {
			s.mu.Lock()
			s.LLM = newClient
			s.mu.Unlock()
			log.Printf("[settings] LLM client rebuilt: %s / %s", provider, model)

			// Restart queue if embedder is also available
			s.mu.RLock()
			hasEmbedder := s.Embedder != nil
			s.mu.RUnlock()
			if hasEmbedder && s.Queue == nil {
				queue := ontology.NewQueue(s.DB, newClient, s.Embedder)
				queue.Start(context.Background())
				s.Queue = queue
			}
		}
	}

	// Return updated settings with masked keys
	anthropicKey, _ := s.DB.GetSetting("anthropic_api_key")
	googleKey, _ := s.DB.GetSetting("google_api_key")
	openaiKey, _ := s.DB.GetSetting("openai_api_key")
	embProvider, _ := s.DB.GetSetting("embedding_provider")
	embModel, _ := s.DB.GetSetting("embedding_model")
	embDim, _ := s.DB.GetSetting("embedding_dim")

	writeJSON(w, 200, map[string]any{
		"llm_provider":       provider,
		"llm_model":          model,
		"embedding_provider": embProvider,
		"embedding_model":    embModel,
		"embedding_dim":      embDim,
		"anthropic_api_key":  db.MaskedKey(anthropicKey),
		"google_api_key":     db.MaskedKey(googleKey),
		"openai_api_key":     db.MaskedKey(openaiKey),
	})
}

func (s *Server) setupComplete(w http.ResponseWriter, r *http.Request) {
	var body struct {
		EmbeddingProvider string `json:"embedding_provider"`
		EmbeddingModel    string `json:"embedding_model"`
		LLMProvider       string `json:"llm_provider"`
		LLMModel          string `json:"llm_model"`
		AnthropicKey      string `json:"anthropic_api_key"`
		GoogleKey         string `json:"google_api_key"`
		OpenAIKey         string `json:"openai_api_key"`
		OllamaBaseURL     string `json:"ollama_base_url"`
		OpenAIBaseURL     string `json:"openai_base_url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	// Check if already set up
	done, _ := s.DB.GetSettingBool("setup_complete")
	if done {
		writeError(w, 409, "setup already complete")
		return
	}

	// Store embedding settings
	if body.EmbeddingProvider != "" {
		s.DB.SetSetting("embedding_provider", body.EmbeddingProvider, false)
	}
	if body.EmbeddingModel != "" {
		s.DB.SetSetting("embedding_model", body.EmbeddingModel, false)
	}

	// Store API keys (encrypted)
	if body.AnthropicKey != "" {
		s.DB.SetSetting("anthropic_api_key", body.AnthropicKey, true)
	}
	if body.GoogleKey != "" {
		s.DB.SetSetting("google_api_key", body.GoogleKey, true)
	}
	if body.OpenAIKey != "" {
		s.DB.SetSetting("openai_api_key", body.OpenAIKey, true)
	}
	if body.OllamaBaseURL != "" {
		s.DB.SetSetting("ollama_base_url", body.OllamaBaseURL, false)
	}
	if body.OpenAIBaseURL != "" {
		s.DB.SetSetting("openai_base_url", body.OpenAIBaseURL, false)
	}

	// Create embedder
	embKey := s.getProviderKey(body.EmbeddingProvider)
	embBaseURL, _ := s.DB.GetSetting(body.EmbeddingProvider + "_base_url")
	embedder, err := embeddings.New(body.EmbeddingProvider, body.EmbeddingModel, embKey, embBaseURL)
	if err != nil {
		writeError(w, 400, fmt.Sprintf("failed to create embedder: %v", err))
		return
	}

	dim := embedder.Dimension()
	s.DB.SetSetting("embedding_dim", strconv.Itoa(dim), false)

	// Create vec tables
	if err := s.DB.CreateVecTables(dim); err != nil {
		writeError(w, 500, fmt.Sprintf("failed to create vec tables: %v", err))
		return
	}

	// Store LLM settings
	if body.LLMProvider != "" {
		s.DB.SetSetting("llm_provider", body.LLMProvider, false)
	}
	if body.LLMModel != "" {
		s.DB.SetSetting("llm_model", body.LLMModel, false)
	}

	// Create LLM client
	llmKey := s.getProviderKey(body.LLMProvider)
	llmBaseURL, _ := s.DB.GetSetting(body.LLMProvider + "_base_url")
	var llmClient llm.Client
	if body.LLMProvider != "" {
		client, err := llm.New(body.LLMProvider, body.LLMModel, llmKey, llmBaseURL)
		if err != nil {
			log.Printf("[setup] warning: could not create LLM client: %v", err)
		} else {
			llmClient = client
		}
	}

	// Swap in new clients
	s.mu.Lock()
	s.Embedder = embedder
	s.LLM = llmClient
	s.mu.Unlock()

	// Init queue if both available
	if llmClient != nil && embedder != nil {
		queue := ontology.NewQueue(s.DB, llmClient, embedder)
		queue.Start(context.Background())
		s.Queue = queue
		log.Println("[setup] ontology processing queue started")
	}

	// Mark setup complete
	s.DB.SetSetting("setup_complete", "1", false)

	// Set session cookie so the user is authenticated immediately after setup
	setSessionCookie(w, s.DB.CryptoKey)

	writeJSON(w, 200, map[string]any{
		"status":        "ok",
		"embedding_dim": dim,
	})
}

func (s *Server) changeEmbedding(w http.ResponseWriter, r *http.Request) {
	var body struct {
		EmbeddingProvider string `json:"embedding_provider"`
		EmbeddingModel    string `json:"embedding_model"`
		AnthropicKey      string `json:"anthropic_api_key"`
		GoogleKey         string `json:"google_api_key"`
		OpenAIKey         string `json:"openai_api_key"`
		OpenAIBaseURL     string `json:"openai_base_url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeError(w, 400, "invalid JSON")
		return
	}

	// Check if an embedding change is already in progress
	s.mu.RLock()
	inProgress := s.EmbStatus != nil && s.EmbStatus.Status == "in_progress"
	s.mu.RUnlock()
	if inProgress {
		writeError(w, 409, "embedding change already in progress")
		return
	}

	// Store any new API keys first
	if body.AnthropicKey != "" {
		s.DB.SetSetting("anthropic_api_key", body.AnthropicKey, true)
	}
	if body.GoogleKey != "" {
		s.DB.SetSetting("google_api_key", body.GoogleKey, true)
	}
	if body.OpenAIKey != "" {
		s.DB.SetSetting("openai_api_key", body.OpenAIKey, true)
	}
	if body.OpenAIBaseURL != "" {
		s.DB.SetSetting("openai_base_url", body.OpenAIBaseURL, false)
	}

	// Create new embedder and validate connection
	embKey := s.getProviderKey(body.EmbeddingProvider)
	embBaseURL, _ := s.DB.GetSetting(body.EmbeddingProvider + "_base_url")
	newEmbedder, err := embeddings.New(body.EmbeddingProvider, body.EmbeddingModel, embKey, embBaseURL)
	if err != nil {
		writeError(w, 400, fmt.Sprintf("failed to create embedder: %v", err))
		return
	}

	// Validate connection
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	_, err = newEmbedder.Embed(ctx, []string{"connection test"})
	if err != nil {
		writeError(w, 400, fmt.Sprintf("embedding connection failed: %v", err))
		return
	}

	dim := newEmbedder.Dimension()

	// Reset knowledge graph
	tables := []string{"edges", "engrams", "projections", "engram_aliases", "document_engrams"}
	for _, t := range tables {
		if _, err := s.DB.Exec("DELETE FROM " + t); err != nil {
			writeError(w, 500, fmt.Sprintf("failed to clear %s: %v", t, err))
			return
		}
	}

	// Drop and recreate vec tables with new dimension
	if err := s.DB.DropVecTables(); err != nil {
		writeError(w, 500, fmt.Sprintf("failed to drop vec tables: %v", err))
		return
	}
	if err := s.DB.CreateVecTables(dim); err != nil {
		writeError(w, 500, fmt.Sprintf("failed to create vec tables: %v", err))
		return
	}

	// Update embedding settings in DB
	s.DB.SetSetting("embedding_provider", body.EmbeddingProvider, false)
	if body.EmbeddingModel != "" {
		s.DB.SetSetting("embedding_model", body.EmbeddingModel, false)
	}
	s.DB.SetSetting("embedding_dim", strconv.Itoa(dim), false)

	// Swap embedder
	s.mu.Lock()
	s.Embedder = newEmbedder
	s.mu.Unlock()

	// Reset all documents to unprocessed
	if _, err := s.DB.Exec(`UPDATE documents SET processed = 0`); err != nil {
		writeError(w, 500, fmt.Sprintf("failed to reset documents: %v", err))
		return
	}

	// Count total documents to reprocess
	var total int
	if err := s.DB.QueryRow(`SELECT COUNT(*) FROM documents`).Scan(&total); err != nil {
		writeError(w, 500, fmt.Sprintf("failed to count documents: %v", err))
		return
	}

	// Set initial status
	s.mu.Lock()
	s.EmbStatus = &EmbeddingChangeStatus{
		Status: "in_progress",
		Total:  total,
	}
	s.mu.Unlock()

	// Launch background reprocessing goroutine
	go func() {
		rows, err := s.DB.Query(`SELECT id FROM documents ORDER BY created_at ASC`)
		if err != nil {
			s.mu.Lock()
			s.EmbStatus.Status = "failed"
			s.EmbStatus.Error = fmt.Sprintf("failed to list documents: %v", err)
			s.mu.Unlock()
			return
		}
		defer rows.Close()

		var docIDs []string
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				s.mu.Lock()
				s.EmbStatus.Status = "failed"
				s.EmbStatus.Error = fmt.Sprintf("failed to scan document id: %v", err)
				s.mu.Unlock()
				return
			}
			docIDs = append(docIDs, id)
		}
		if err := rows.Err(); err != nil {
			s.mu.Lock()
			s.EmbStatus.Status = "failed"
			s.EmbStatus.Error = fmt.Sprintf("failed to iterate documents: %v", err)
			s.mu.Unlock()
			return
		}

		s.mu.RLock()
		llmClient := s.LLM
		curEmbedder := s.Embedder
		s.mu.RUnlock()

		for _, docID := range docIDs {
			if llmClient == nil || curEmbedder == nil {
				s.mu.Lock()
				s.EmbStatus.Status = "failed"
				s.EmbStatus.Error = "LLM or embedder not available"
				s.mu.Unlock()
				return
			}
			if err := ontology.ProcessDocument(context.Background(), s.DB, llmClient, curEmbedder, docID); err != nil {
				log.Printf("[embedding-change] error reprocessing %s: %v", docID, err)
				// Continue processing remaining documents despite individual failures
			}
			s.mu.Lock()
			s.EmbStatus.Processed++
			s.mu.Unlock()
		}

		s.mu.Lock()
		s.EmbStatus.Status = "complete"
		log.Printf("[embedding-change] reprocessing complete: %d/%d documents", s.EmbStatus.Processed, s.EmbStatus.Total)
		s.mu.Unlock()
	}()

	s.mu.RLock()
	writeJSON(w, 200, s.EmbStatus)
	s.mu.RUnlock()
}

func (s *Server) embeddingStatus(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.EmbStatus == nil {
		writeJSON(w, 200, map[string]string{"status": "idle"})
		return
	}
	writeJSON(w, 200, s.EmbStatus)
}

// getProviderKey returns the API key for the given provider from the DB.
func (s *Server) getProviderKey(provider string) string {
	if key := db.ProviderAPIKey(provider); key != "" {
		val, _ := s.DB.GetSetting(key)
		return val
	}
	return ""
}

// --- Visualization ---

func (s *Server) getProjections(w http.ResponseWriter, r *http.Request) {
	points, err := s.DB.GetProjections()
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, points)
}

func (s *Server) getClusters(w http.ResponseWriter, r *http.Request) {
	clusters, err := s.DB.GetClusters()
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	// Enrich with overviews
	overviews, _ := projection.GetClusterOverviews(s.DB)
	overviewMap := make(map[int]projection.ClusterOverview)
	for _, o := range overviews {
		overviewMap[o.ClusterID] = o
	}

	type enrichedCluster struct {
		db.Cluster
		Label   string `json:"label,omitempty"`
		Summary string `json:"summary,omitempty"`
	}
	out := make([]enrichedCluster, len(clusters))
	for i, c := range clusters {
		ec := enrichedCluster{Cluster: c}
		if o, ok := overviewMap[c.ClusterID]; ok {
			ec.Label = o.Label
			ec.Summary = o.Summary
		}
		out[i] = ec
	}
	writeJSON(w, 200, out)
}

func (s *Server) getGaps(w http.ResponseWriter, r *http.Request) {
	gaps, err := projection.RecomputeGaps(s.DB)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	if gaps == nil {
		gaps = []projection.GapRegion{}
	}
	writeJSON(w, 200, gaps)
}

func (s *Server) getVizEdges(w http.ResponseWriter, r *http.Request) {
	edges, err := s.DB.GetVizEdges(5000)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, edges)
}

func (s *Server) recomputeProjections(w http.ResponseWriter, r *http.Request) {
	points, err := projection.Recompute(s.DB)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}

	// Synthesize cluster overviews if LLM available
	s.mu.RLock()
	llmClient := s.LLM
	s.mu.RUnlock()
	if llmClient != nil {
		if n, err := projection.SynthesizeClusterOverviews(r.Context(), s.DB, llmClient); err != nil {
			log.Printf("[viz] cluster synthesis error: %v", err)
		} else if n > 0 {
			log.Printf("[viz] synthesized %d cluster overviews", n)
		}
	}

	writeJSON(w, 200, points)
}

// --- Backup ---

func (s *Server) downloadBackup(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", "attachment; filename=hypomnema.db")
	// Copy the DB file
	_, err := s.DB.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`)
	if err != nil {
		writeError(w, 500, err.Error())
		return
	}
	http.ServeFile(w, r, s.Config.DBPath)
}

// --- Helpers ---

func setSessionCookie(w http.ResponseWriter, cryptoKey []byte) {
	http.SetCookie(w, &http.Cookie{
		Name:     "hypomnema_session",
		Value:    crypto.SignSession(cryptoKey),
		MaxAge:   30 * 24 * 3600,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
		Path:     "/",
	})
}

