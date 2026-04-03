package db

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"fmt"
	"time"

	sqlite_vec "github.com/asg017/sqlite-vec-go-bindings/cgo"
	_ "github.com/mattn/go-sqlite3"
)

func init() {
	sqlite_vec.Auto()
}

// DB wraps *sql.DB with the encryption key for settings access.
type DB struct {
	*sql.DB
	CryptoKey []byte
}

// Open creates or opens the SQLite database with WAL mode, applies the schema,
// and returns a ready DB handle.
func Open(path string, cryptoKey []byte) (*DB, error) {
	dsn := fmt.Sprintf("file:%s?_journal_mode=WAL&_busy_timeout=5000&_foreign_keys=on", path)
	sqlDB, err := sql.Open("sqlite3", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	sqlDB.SetMaxOpenConns(1) // SQLite: single writer
	sqlDB.SetMaxIdleConns(1)

	if _, err := sqlDB.Exec(schema); err != nil {
		sqlDB.Close()
		return nil, fmt.Errorf("apply schema: %w", err)
	}

	return &DB{DB: sqlDB, CryptoKey: cryptoKey}, nil
}

// CreateVecTables creates the sqlite-vec virtual tables for embeddings.
func (db *DB) CreateVecTables(dim int) error {
	stmts := []string{
		fmt.Sprintf(`CREATE VIRTUAL TABLE IF NOT EXISTS engram_embeddings USING vec0(engram_id TEXT PRIMARY KEY, embedding float[%d])`, dim),
		fmt.Sprintf(`CREATE VIRTUAL TABLE IF NOT EXISTS document_embeddings USING vec0(document_id TEXT PRIMARY KEY, embedding float[%d])`, dim),
	}
	for _, s := range stmts {
		if _, err := db.Exec(s); err != nil {
			return fmt.Errorf("create vec table: %w", err)
		}
	}
	return nil
}

// DropVecTables removes the vec virtual tables (used during embedding provider change).
func (db *DB) DropVecTables() error {
	for _, t := range []string{"engram_embeddings", "document_embeddings"} {
		if _, err := db.Exec("DROP TABLE IF EXISTS " + t); err != nil {
			return err
		}
	}
	return nil
}

// Now returns the current UTC time in ISO 8601 format.
func Now() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// NewID generates a random 16-byte hex ID.
func NewID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic("crypto/rand failed: " + err.Error())
	}
	return hex.EncodeToString(b)
}

// NilIfEmpty returns nil for empty strings, or a pointer to the string.
func NilIfEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
