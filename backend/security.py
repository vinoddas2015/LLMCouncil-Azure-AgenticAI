"""
Security utilities — encryption at rest & PII redaction.

Provides:
  1. **Fernet encryption** for data at rest (conversation JSON files).
  2. **PII redaction** that scrubs sensitive patterns from text *before*
     it is dispatched to external model providers.

Configuration (via .env):
  ENCRYPTION_KEY   – A Fernet key (base64-encoded 32-byte key).
                     Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
                     If omitted, encryption at rest is disabled (plain JSON).
  PII_REDACTION    – "true" to enable PII scrubbing before external calls (default: true).
"""

import os
import re
import json
import logging
from typing import Optional

logger = logging.getLogger("llm_council.security")

# ═══════════════════════════════════════════════════════════════════════
# 1. Encryption at rest (Fernet symmetric encryption)
# ═══════════════════════════════════════════════════════════════════════

_fernet = None  # Lazy-initialised


def _get_fernet():
    """Return a Fernet instance if ENCRYPTION_KEY is configured, else None."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        logger.info("[Security] ENCRYPTION_KEY not set — encryption at rest DISABLED")
        return None

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        logger.info("[Security] Encryption at rest ENABLED (Fernet AES-128-CBC)")
        return _fernet
    except Exception as e:
        logger.error(f"[Security] Invalid ENCRYPTION_KEY — encryption DISABLED: {e}")
        return None


def encrypt_data(plaintext: str) -> str:
    """
    Encrypt a plaintext string.  Returns the ciphertext as a base64 string.
    If encryption is not configured, returns the plaintext unchanged.
    """
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_data(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string.  Returns the original plaintext.
    If encryption is not configured, returns the input unchanged.

    Gracefully handles unencrypted (legacy) data by returning it as-is
    when decryption fails — this allows transparent migration.
    """
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        # Data is not encrypted (legacy file) — return as-is
        logger.debug("[Security] Data not encrypted (legacy) — returning raw")
        return ciphertext


def is_encryption_enabled() -> bool:
    """Check whether encryption at rest is active."""
    return _get_fernet() is not None


# ═══════════════════════════════════════════════════════════════════════
# 2. PII Redaction — scrub before dispatching to external providers
# ═══════════════════════════════════════════════════════════════════════

# Whether PII redaction is enabled (default: true)
PII_REDACTION_ENABLED = os.getenv("PII_REDACTION", "true").strip().lower() in ("true", "1", "yes")

# Redaction placeholder
_REDACTED = "[REDACTED]"

# ── PII patterns (order matters — more specific first) ───────────────

_PII_REDACTION_PATTERNS = [
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b'), "[EMAIL-REDACTED]"),

    # Phone numbers (international & US formats)
    (re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,5}\b'), "[PHONE-REDACTED]"),

    # SSN (US Social Security Number)
    (re.compile(r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b'), "[SSN-REDACTED]"),

    # Medical Record Number (MRN)
    (re.compile(r'\bMRN\s*(?::|is|=)\s*\d{5,}', re.IGNORECASE), "[MRN-REDACTED]"),

    # Date of Birth patterns
    (re.compile(
        r'\b(?:date\s+of\s+birth|DOB|d\.o\.b\.?)\s*(?::|is|=)\s*'
        r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}',
        re.IGNORECASE,
    ), "[DOB-REDACTED]"),

    # Patient / subject name attribution
    (re.compile(
        r'\b(?:patient|subject|client)\s+(?:name|id)\s*(?:is|:)\s*'
        r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+',
        re.IGNORECASE,
    ), "[PATIENT-ID-REDACTED]"),

    # Credit card numbers (Visa, MC, Amex, etc.)
    (re.compile(r'\b(?:\d{4}[-\s]?){3}\d{1,4}\b'), "[CC-REDACTED]"),

    # IP addresses (v4)
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "[IP-REDACTED]"),

    # Passport numbers (generic: 1-2 letters + 6-9 digits)
    (re.compile(r'\b(?:passport\s*(?:no|number|#|:)\s*)[A-Z]{0,2}\d{6,9}\b', re.IGNORECASE), "[PASSPORT-REDACTED]"),
]


def redact_pii(text: str) -> str:
    """
    Scrub PII patterns from *text* and return the sanitized version.

    This runs **before** queries are dispatched to external model providers,
    ensuring that even if the prompt guard allows the message through
    (because it's on-topic), any embedded PII is removed.

    Returns the original text if PII_REDACTION is disabled.
    """
    if not PII_REDACTION_ENABLED:
        return text

    if not text:
        return text

    redacted = text
    pii_found = False

    for pattern, replacement in _PII_REDACTION_PATTERNS:
        new_text = pattern.sub(replacement, redacted)
        if new_text != redacted:
            pii_found = True
            redacted = new_text

    if pii_found:
        logger.info("[Security] PII redacted from outgoing text before external dispatch")

    return redacted


def get_security_status() -> dict:
    """Return current security configuration status for the /api/health endpoint."""
    return {
        "encryption_at_rest": is_encryption_enabled(),
        "pii_redaction": PII_REDACTION_ENABLED,
        "tls_in_transit": True,  # External API uses HTTPS
    }
