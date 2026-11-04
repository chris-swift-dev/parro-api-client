"""PKCE (Proof Key for Code Exchange, RFC 7636) for the browser-style login.

The authorize request carries a *challenge*; the token exchange later proves it came from the same
client by sending the matching *verifier*. Only the S256 method is used.

The verifier is a secret until the login finishes, so it must never be logged.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field

# 32 random bytes give a 43-character verifier, the minimum length RFC 7636 §4.1 allows.
VERIFIER_RANDOM_BYTES = 32
CHALLENGE_METHOD = "S256"


@dataclass(frozen=True)
class PkcePair:
    """A verifier (kept locally) and its challenge (sent in the authorize URL)."""

    verifier: str = field(repr=False)
    challenge: str


def base64url_without_padding(raw: bytes) -> str:
    """URL-safe base64 without '=' padding, as RFC 7636 §3 requires."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def create_challenge(verifier: str) -> str:
    """S256 challenge: base64url(SHA-256(verifier))."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64url_without_padding(digest)


def create_pkce_pair() -> PkcePair:
    """A fresh random verifier with its challenge."""
    verifier = base64url_without_padding(secrets.token_bytes(VERIFIER_RANDOM_BYTES))
    return PkcePair(verifier=verifier, challenge=create_challenge(verifier))


def create_state() -> str:
    """Random value for the OAuth `state` parameter, checked again when the code comes back."""
    return secrets.token_urlsafe(16)
