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
				if err := q.processJob(ctx, job); err != nil {
					log.Printf("[ontology] error processing %s: %v", job.DocumentID, err)
				}
			}
		}
	}()
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

func (q *Queue) processJob(ctx context.Context, job PipelineJob) error {
	if job.Incremental {
		return ReviseDocument(ctx, q.db, q.llm, q.emb, job.DocumentID)
	}
	return ProcessDocument(ctx, q.db, q.llm, q.emb, job.DocumentID)
}
