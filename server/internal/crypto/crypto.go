// Package crypto provides API key encryption (AES-CBC + HMAC, Fernet-compatible layout)
// and passphrase hashing (PBKDF2-SHA256) for session auth.
package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/crypto/pbkdf2"
)

// Fernet-like token layout: version(1) | timestamp(8) | iv(16) | ciphertext(N) | hmac(32)
// Compatible with Python cryptography.fernet for reading existing encrypted values.

const (
	fernetVersion    = 0x80
	hmacLen          = 32
	ivLen            = 16
	timestampLen     = 8
	versionLen       = 1
	headerLen        = versionLen + timestampLen + ivLen
	pbkdf2Iterations = 600_000
	saltLen          = 16
)

// LoadOrCreateKey reads the Fernet key from disk, or generates one if absent.
func LoadOrCreateKey(dbPath string) ([]byte, error) {
	keyPath := filepath.Join(filepath.Dir(dbPath), ".hypomnema_key")

	data, err := os.ReadFile(keyPath)
	if err == nil {
		return base64.URLEncoding.DecodeString(string(data))
	}
	if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("read key: %w", err)
	}

	// Generate 32 bytes: 16 for HMAC signing, 16 for AES-128-CBC encryption.
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, fmt.Errorf("generate key: %w", err)
	}

	encoded := base64.URLEncoding.EncodeToString(key)
	if err := os.WriteFile(keyPath, []byte(encoded), 0600); err != nil {
		return nil, fmt.Errorf("write key: %w", err)
	}
	return key, nil
}

// Encrypt produces a Fernet token from plaintext.
func Encrypt(plaintext string, key []byte) (string, error) {
	signingKey := key[:16]
	encryptionKey := key[16:]

	iv := make([]byte, ivLen)
	if _, err := rand.Read(iv); err != nil {
		return "", err
	}

	padded := pkcs7Pad([]byte(plaintext), aes.BlockSize)
	block, err := aes.NewCipher(encryptionKey)
	if err != nil {
		return "", err
	}
	ct := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ct, padded)

	// Assemble: version | timestamp | iv | ciphertext
	now := make([]byte, timestampLen)
	binary.BigEndian.PutUint64(now, uint64(time.Now().Unix()))

	payload := make([]byte, 0, headerLen+len(ct))
	payload = append(payload, fernetVersion)
	payload = append(payload, now...)
	payload = append(payload, iv...)
	payload = append(payload, ct...)

	// HMAC-SHA256 over payload
	mac := hmac.New(sha256.New, signingKey)
	mac.Write(payload)
	payload = append(payload, mac.Sum(nil)...)

	return base64.URLEncoding.EncodeToString(payload), nil
}

// Decrypt verifies and decrypts a Fernet token.
func Decrypt(token string, key []byte) (string, error) {
	signingKey := key[:16]
	encryptionKey := key[16:]

	data, err := base64.URLEncoding.DecodeString(token)
	if err != nil {
		return "", fmt.Errorf("decode token: %w", err)
	}
	if len(data) < headerLen+hmacLen+aes.BlockSize {
		return "", errors.New("token too short")
	}

	payload := data[:len(data)-hmacLen]
	expectedMAC := data[len(data)-hmacLen:]

	mac := hmac.New(sha256.New, signingKey)
	mac.Write(payload)
	if !hmac.Equal(mac.Sum(nil), expectedMAC) {
		return "", errors.New("HMAC mismatch")
	}

	iv := payload[versionLen+timestampLen : headerLen]
	ct := payload[headerLen:]

	block, err := aes.NewCipher(encryptionKey)
	if err != nil {
		return "", err
	}
	plain := make([]byte, len(ct))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plain, ct)

	unpadded, err := pkcs7Unpad(plain, aes.BlockSize)
	if err != nil {
		return "", err
	}
	return string(unpadded), nil
}

// HashPassphrase returns "salt_hex:derived_hex" using PBKDF2-SHA256.
func HashPassphrase(passphrase string) (string, error) {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	derived := pbkdf2.Key([]byte(passphrase), salt, pbkdf2Iterations, 32, sha256.New)
	return hex.EncodeToString(salt) + ":" + hex.EncodeToString(derived), nil
}

// VerifyPassphrase checks a passphrase against a "salt_hex:derived_hex" hash.
func VerifyPassphrase(passphrase, stored string) (bool, error) {
	parts := splitOnce(stored, ':')
	if len(parts) != 2 {
		return false, errors.New("invalid hash format")
	}
	salt, err := hex.DecodeString(parts[0])
	if err != nil {
		return false, err
	}
	expected, err := hex.DecodeString(parts[1])
	if err != nil {
		return false, err
	}
	derived := pbkdf2.Key([]byte(passphrase), salt, pbkdf2Iterations, 32, sha256.New)
	return hmac.Equal(derived, expected), nil
}

// SignSession creates an HMAC-signed session token: "timestamp:hmac_hex".
func SignSession(key []byte) string {
	ts := fmt.Sprintf("%d", time.Now().Unix())
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(ts))
	return ts + ":" + hex.EncodeToString(mac.Sum(nil))
}

// VerifySession checks an HMAC-signed session token and its age.
func VerifySession(token string, key []byte, maxAge time.Duration) bool {
	parts := splitOnce(token, ':')
	if len(parts) != 2 {
		return false
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(parts[0]))
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(parts[1])) {
		return false
	}
	var ts int64
	if _, err := fmt.Sscanf(parts[0], "%d", &ts); err != nil {
		return false
	}
	return time.Since(time.Unix(ts, 0)) < maxAge
}

func pkcs7Pad(data []byte, blockSize int) []byte {
	pad := blockSize - len(data)%blockSize
	padding := make([]byte, pad)
	for i := range padding {
		padding[i] = byte(pad)
	}
	return append(data, padding...)
}

func pkcs7Unpad(data []byte, blockSize int) ([]byte, error) {
	if len(data) == 0 || len(data)%blockSize != 0 {
		return nil, errors.New("invalid padding")
	}
	pad := int(data[len(data)-1])
	if pad == 0 || pad > blockSize {
		return nil, errors.New("invalid padding byte")
	}
	for i := len(data) - pad; i < len(data); i++ {
		if data[i] != byte(pad) {
			return nil, errors.New("invalid padding")
		}
	}
	return data[:len(data)-pad], nil
}

func splitOnce(s string, sep byte) []string {
	for i := range len(s) {
		if s[i] == sep {
			return []string{s[:i], s[i+1:]}
		}
	}
	return []string{s}
}
