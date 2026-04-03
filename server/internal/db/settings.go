package db

import (
	"database/sql"

	"github.com/junhewk/hypomnema/internal/crypto"
)

// GetSetting reads a setting value, decrypting if necessary.
func (db *DB) GetSetting(key string) (string, error) {
	var value sql.NullString
	var encrypted int
	err := db.QueryRow(`SELECT value, encrypted FROM settings WHERE key = ?`, key).
		Scan(&value, &encrypted)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if !value.Valid {
		return "", nil
	}
	if encrypted == 1 && db.CryptoKey != nil {
		return crypto.Decrypt(value.String, db.CryptoKey)
	}
	return value.String, nil
}

// SetSetting writes a setting value, encrypting if specified.
func (db *DB) SetSetting(key, value string, encrypt bool) error {
	storedValue := value
	encrypted := 0
	if encrypt && db.CryptoKey != nil {
		enc, err := crypto.Encrypt(value, db.CryptoKey)
		if err != nil {
			return err
		}
		storedValue = enc
		encrypted = 1
	}
	_, err := db.Exec(`
		INSERT INTO settings (key, value, encrypted, updated_at) VALUES (?, ?, ?, ?)
		ON CONFLICT(key) DO UPDATE SET value = excluded.value, encrypted = excluded.encrypted, updated_at = excluded.updated_at`,
		key, storedValue, encrypted, Now())
	return err
}

// GetSettingBool reads a setting as a boolean (empty/"0"/"false" = false).
func (db *DB) GetSettingBool(key string) (bool, error) {
	v, err := db.GetSetting(key)
	if err != nil {
		return false, err
	}
	return v != "" && v != "0" && v != "false", nil
}

// ProviderAPIKey returns the settings key name for a provider's API key.
func ProviderAPIKey(provider string) string {
	switch provider {
	case "claude":
		return "anthropic_api_key"
	case "google":
		return "google_api_key"
	case "openai":
		return "openai_api_key"
	default:
		return ""
	}
}

// MaskedKey returns "****last4" for an API key, or empty string.
func MaskedKey(key string) string {
	if len(key) <= 4 {
		return key
	}
	return "****" + key[len(key)-4:]
}
