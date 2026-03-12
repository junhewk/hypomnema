"""Fernet encryption for API keys at rest."""

import os
from pathlib import Path

from cryptography.fernet import Fernet


def get_or_create_key(data_dir: Path) -> bytes:
    """Read or create a Fernet key at {data_dir}/.hypomnema_key."""
    key_path = data_dir / ".hypomnema_key"
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)
    return key


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a string with Fernet."""
    return Fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, key: bytes) -> str:
    """Decrypt a Fernet-encrypted string."""
    return Fernet(key).decrypt(ciphertext.encode()).decode()


def mask_key(value: str) -> str:
    """Mask an API key, showing only last 4 chars."""
    if len(value) >= 4:
        return "****" + value[-4:]
    return "****"
