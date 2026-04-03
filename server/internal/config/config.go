package config

import (
	"os"
	"path/filepath"
)

type Config struct {
	Mode    string // "local" or "server"
	Host    string
	Port    string
	DBPath  string
	DataDir string
}

func Load() *Config {
	mode := envOr("HYPOMNEMA_MODE", "server")
	host := envOr("HYPOMNEMA_HOST", "127.0.0.1")
	if mode == "server" && os.Getenv("HYPOMNEMA_HOST") == "" {
		host = "0.0.0.0"
	}
	port := envOr("HYPOMNEMA_PORT", "8073")

	dataDir := envOr("HYPOMNEMA_DATA_DIR", "data")
	dbPath := envOr("HYPOMNEMA_DB_PATH", filepath.Join(dataDir, "hypomnema.db"))

	return &Config{
		Mode:    mode,
		Host:    host,
		Port:    port,
		DBPath:  dbPath,
		DataDir: dataDir,
	}
}

func (c *Config) Addr() string {
	return c.Host + ":" + c.Port
}

func (c *Config) IsServer() bool {
	return c.Mode == "server"
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
