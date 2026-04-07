// Package ontology orchestrates entity extraction, dedup, linking, and heat scoring.
package ontology

import (
	"context"
	"log"
	"sync"

	"github.com/junhewk/hypomnema/internal/db"
	"github.com/junhewk/hypomnema/internal/embeddings"
	"github.com/junhewk/hypomnema/internal/llm"
)

// PipelineJob represents a document to process.
type PipelineJob struct {
	DocumentID  string
	Incremental bool
}

// Queue processes documents serially through the ontology pipeline.
type Queue struct {
	ch  chan PipelineJob
	db  *db.DB
	llm llm.Client
	emb embeddings.Embedder
	wg  sync.WaitGroup
}

// NewQueue creates a processing queue.
func NewQueue(database *db.DB, llmClient llm.Client, embedder embeddings.Embedder) *Queue {
	return &Queue{
		ch:  make(chan PipelineJob, 100),
		db:  database,
		llm: llmClient,
		emb: embedder,
	}
}

// Start begins processing jobs in the background.
func (q *Queue) Start(ctx context.Context) {
	q.wg.Add(1)
	go func() {
		defer q.wg.Done()
		for {
			select {
			case <-ctx.Done():
				return
			case job, ok := <-q.ch:
				if !ok {
					return // channel closed
				}
				q.safeProcessJob(ctx, job)
			}
		}
	}()
}

// safeProcessJob wraps processJob with panic recovery so a single
// crashing document (e.g. HDBSCAN index bug) doesn't kill the queue goroutine.
func (q *Queue) safeProcessJob(ctx context.Context, job PipelineJob) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("[ontology] PANIC processing %s (recovered): %v", job.DocumentID, r)
		}
	}()
	if err := q.processJob(ctx, job); err != nil {
		log.Printf("[ontology] error processing %s: %v", job.DocumentID, err)
	}
}

// Enqueue adds a document for processing.
func (q *Queue) Enqueue(job PipelineJob) {
	q.ch <- job
}

// Stop waits for the current job to finish.
func (q *Queue) Stop() {
	close(q.ch)
	q.wg.Wait()
}

// RecoverPending scans the database for unprocessed documents and enqueues them.
// Call after Start() to resume work that was lost due to a crash or restart.
func (q *Queue) RecoverPending() {
	rows, err := q.db.Query(`SELECT id FROM documents WHERE processed = 0 ORDER BY created_at ASC`)
	if err != nil {
		log.Printf("[ontology] recover scan failed: %v", err)
		return
	}
	defer rows.Close()

	count := 0
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			continue
		}
		q.Enqueue(PipelineJob{DocumentID: id})
		count++
	}
	if count > 0 {
		log.Printf("[ontology] recovered %d unprocessed document(s)", count)
	}
}

func (q *Queue) processJob(ctx context.Context, job PipelineJob) error {
	mode := "full"
	if job.Incremental {
		mode = "incremental"
	}
	log.Printf("[ontology] processing %s (%s)", job.DocumentID, mode)
	var err error
	if job.Incremental {
		err = ReviseDocument(ctx, q.db, q.llm, q.emb, job.DocumentID)
	} else {
		err = ProcessDocument(ctx, q.db, q.llm, q.emb, job.DocumentID)
	}
	if err != nil {
		log.Printf("[ontology] failed %s: %v", job.DocumentID, err)
	} else {
		log.Printf("[ontology] completed %s", job.DocumentID)
	}
	return err
}
