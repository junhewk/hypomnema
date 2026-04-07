package main

import (
	"context"
	"embed"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/junhewk/hypomnema/internal/api"
	"github.com/junhewk/hypomnema/internal/config"
	"github.com/junhewk/hypomnema/internal/crypto"
	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
	"github.com/junhewk/hypomnema/internal/llm"
	"github.com/junhewk/hypomnema/internal/ontology"
	"github.com/junhewk/hypomnema/internal/scheduler"
)

//go:embed all:static
var staticFS embed.FS

func main() {
	cfg := config.Load()

	// Ensure data directory exists
	if err := os.MkdirAll(cfg.DataDir, 0755); err != nil {
		log.Fatalf("create data dir: %v", err)
	}

	// Load or create encryption key
	cryptoKey, err := crypto.LoadOrCreateKey(cfg.DBPath)
	if err != nil {
		log.Fatalf("crypto key: %v", err)
	}

	// Open database
	database, err := db.Open(cfg.DBPath, cryptoKey)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer database.Close()

	// Extract static files sub-FS (strip "static/" prefix)
	staticSub, err := fs.Sub(staticFS, "static")
	if err != nil {
		log.Fatalf("static fs: %v", err)
	}

	// Build server
	srv := &api.Server{
		DB:     database,
		Config: cfg,
	}

	// Try to initialize LLM and embedder from stored settings
	initFromSettings(srv, database)

	// Build router
	handler := api.NewRouter(srv, staticSub)

	// Start HTTP server
	httpSrv := &http.Server{
		Addr:         cfg.Addr(),
		Handler:      handler,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		log.Printf("hypomnema server listening on %s (mode=%s)", cfg.Addr(), cfg.Mode)
		if err := httpSrv.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("server error: %v", err)
		}
	}()

	<-ctx.Done()
	log.Println("shutting down...")

	if srv.Scheduler != nil {
		srv.Scheduler.Stop()
	}

	if srv.Queue != nil {
		srv.Queue.Stop()
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpSrv.Shutdown(shutdownCtx); err != nil {
		log.Printf("shutdown error: %v", err)
	}

	fmt.Println("goodbye")
}

func initFromSettings(srv *api.Server, database *db.DB) {
	setupDone, _ := database.GetSettingBool("setup_complete")
	if !setupDone {
		log.Println("setup not complete — skipping LLM/embedder init")
		return
	}

	// Initialize LLM
	provider, _ := database.GetSetting("llm_provider")
	model, _ := database.GetSetting("llm_model")
	apiKey := getProviderKey(database, provider)
	baseURL, _ := database.GetSetting(provider + "_base_url")

	if provider != "" {
		client, err := llm.New(provider, model, apiKey, baseURL)
		if err != nil {
			log.Printf("warning: could not init LLM (%s): %v", provider, err)
		} else {
			srv.LLM = client
			log.Printf("LLM: %s / %s", provider, model)
		}
	}

	// Initialize embedder
	embProvider, _ := database.GetSetting("embedding_provider")
	embModel, _ := database.GetSetting("embedding_model")
	embKey := getProviderKey(database, embProvider)
	embBaseURL, _ := database.GetSetting(embProvider + "_base_url")

	if embProvider != "" {
		embedder, err := embeddings.New(embProvider, embModel, embKey, embBaseURL)
		if err != nil {
			log.Printf("warning: could not init embedder (%s): %v", embProvider, err)
		} else {
			srv.Embedder = embedder
			log.Printf("embedder: %s / %s (dim=%d)", embProvider, embModel, embedder.Dimension())

			// Create vec tables if needed
			if err := database.CreateVecTables(embedder.Dimension()); err != nil {
				log.Printf("warning: vec tables: %v", err)
			}
		}
	}

	// Start ontology queue if both are available
	if srv.LLM != nil && srv.Embedder != nil {
		queue := ontology.NewQueue(database, srv.LLM, srv.Embedder)
		queue.Start(context.Background())
		srv.Queue = queue
		log.Println("ontology processing queue started")

		// Recover any documents orphaned by a previous crash
		queue.RecoverPending()

		// Start feed scheduler
		sched := scheduler.New(database, queue)
		n, err := sched.LoadJobs()
		if err != nil {
			log.Printf("warning: loading feed jobs: %v", err)
		} else if n > 0 {
			log.Printf("feed scheduler: loaded %d job(s)", n)
		}
		sched.Start()
		srv.Scheduler = sched
		log.Println("feed scheduler started")
	}
}

func getProviderKey(database *db.DB, provider string) string {
	if key := db.ProviderAPIKey(provider); key != "" {
		val, _ := database.GetSetting(key)
		return val
	}
	return ""
}
