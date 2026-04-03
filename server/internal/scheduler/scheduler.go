// Package scheduler manages periodic feed polling via cron jobs.
package scheduler

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/ingestion"
	"github.com/junhewk/hypomnema/internal/ontology"
	"github.com/robfig/cron/v3"
)

// Scheduler manages cron jobs for active feed sources.
type Scheduler struct {
	cron  *cron.Cron
	db    *db.DB
	queue *ontology.Queue
	jobs  map[string]cron.EntryID // feedID → cron entry ID
	mu    sync.Mutex
}

// New creates a Scheduler that polls feeds and enqueues results for processing.
func New(database *db.DB, queue *ontology.Queue) *Scheduler {
	return &Scheduler{
		cron:  cron.New(),
		db:    database,
		queue: queue,
		jobs:  make(map[string]cron.EntryID),
	}
}

// LoadJobs reads all active feeds from the database and registers a cron job for
// each one. It returns the number of jobs loaded.
func (s *Scheduler) LoadJobs() (int, error) {
	feeds, err := s.db.ListFeeds()
	if err != nil {
		return 0, err
	}

	loaded := 0
	for _, f := range feeds {
		if f.Active != 1 {
			continue
		}
		if err := s.AddJob(f.ID, f.Schedule); err != nil {
			log.Printf("[scheduler] skipping feed %s (%s): %v", f.ID, f.Name, err)
			continue
		}
		loaded++
	}
	return loaded, nil
}

// AddJob registers (or replaces) a cron job for the given feed.
func (s *Scheduler) AddJob(feedID, schedule string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Remove any existing job for this feed
	if oldID, ok := s.jobs[feedID]; ok {
		s.cron.Remove(oldID)
		delete(s.jobs, feedID)
	}

	entryID, err := s.cron.AddFunc(schedule, func() {
		s.runFeedJob(feedID)
	})
	if err != nil {
		return err
	}
	s.jobs[feedID] = entryID
	return nil
}

// RemoveJob unregisters the cron job for the given feed.
func (s *Scheduler) RemoveJob(feedID string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if entryID, ok := s.jobs[feedID]; ok {
		s.cron.Remove(entryID)
		delete(s.jobs, feedID)
	}
}

// Start begins the cron scheduler in the background.
func (s *Scheduler) Start() {
	s.cron.Start()
}

// Stop gracefully stops the cron scheduler, waiting for running jobs to finish.
func (s *Scheduler) Stop() {
	ctx := s.cron.Stop()
	// Wait for any running jobs to complete (with a timeout).
	select {
	case <-ctx.Done():
	case <-time.After(30 * time.Second):
		log.Println("[scheduler] timed out waiting for running jobs")
	}
}

// runFeedJob is the callback executed by cron for a single feed.
func (s *Scheduler) runFeedJob(feedID string) {
	feed, err := s.db.GetFeed(feedID)
	if err != nil {
		log.Printf("[scheduler] feed %s: could not load from DB: %v", feedID, err)
		return
	}
	if feed.Active != 1 {
		log.Printf("[scheduler] feed %s: no longer active, skipping", feedID)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	items, err := ingestion.PollFeed(ctx, *feed)
	if err != nil {
		log.Printf("[scheduler] feed %s (%s): poll error: %v", feedID, feed.Name, err)
		return
	}

	inserted := 0
	for _, item := range items {
		if item.SourceURI == "" || item.Text == "" {
			continue
		}

		// De-duplicate by source_uri
		exists, err := ingestion.CheckDuplicateURL(s.db, item.SourceURI)
		if err != nil {
			log.Printf("[scheduler] feed %s: dedup check error: %v", feedID, err)
			continue
		}
		if exists {
			continue
		}

		uri := item.SourceURI
		title := item.Title
		doc := &db.Document{
			SourceType: "feed",
			Text:       item.Text,
			Title:      db.NilIfEmpty(title),
			SourceURI:  &uri,
		}
		if err := s.db.InsertDocument(doc); err != nil {
			log.Printf("[scheduler] feed %s: insert error: %v", feedID, err)
			continue
		}

		if s.queue != nil {
			s.queue.Enqueue(ontology.PipelineJob{DocumentID: doc.ID})
		}
		inserted++
	}

	// Update last_fetched timestamp
	if err := s.db.UpdateFeedLastFetched(feedID); err != nil {
		log.Printf("[scheduler] feed %s: could not update last_fetched: %v", feedID, err)
	}

	if inserted > 0 {
		log.Printf("[scheduler] feed %s (%s): inserted %d new document(s)", feedID, feed.Name, inserted)
	}
}

