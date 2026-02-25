"""
Entra ID (Azure AD) JWT token validation for SSO.

Validates Bearer tokens issued by MSAL in the frontend against Microsoft's
JWKS (JSON Web Key Set) endpoint.  Extracts user identity (preferred_username /
CWID) from the token claims and injects it as the user-id.

Usage in main.py:
    from .auth import get_authenticated_user_id

    @app.get("/api/protected")
    async def protected(user_id: str = Depends(get_authenticated_user_id)):
        ...
"""

import logging
import time
from typing import Optional

import httpx
import jwt                              # PyJWT
from jwt import PyJWKClient, PyJWKClientError
from fastapi import Header, HTTPException, Request

from .config import (
    ENTRA_SSO_ENABLED,
    ENTRA_TENANT_ID,
    ENTRA_CLIENT_ID,
    ENTRA_AUDIENCE,
    ENTRA_ISSUER,
    ENTRA_JWKS_URI,
)

logger = logging.getLogger(__name__)

# ── JWKS client (caches keys for 1 hour) ────────────────────────────────
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    """Lazy-init a PyJWKClient that fetches Microsoft's signing keys and caches them."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            uri=ENTRA_JWKS_URI,
            cache_keys=True,
            lifespan=3600,  # refresh keys every hour
        )
        logger.info(f"[Auth] Initialized JWKS client → {ENTRA_JWKS_URI}")
    return _jwks_client


def validate_access_token(token: str) -> dict:
    """
    Validate an Entra ID v2.0 access token and return the decoded claims.

    Checks:
    - Signature (RS256, against Microsoft JWKS)
    - Issuer  (must match Bayer tenant v2.0 issuer)
    - Audience (must match api://<client_id>)
    - Expiration (exp), not-before (nbf)

    Returns:
        dict: Decoded JWT claims on success.

    Raises:
        HTTPException(401): On any validation failure.
    """
    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=ENTRA_AUDIENCE,
            issuer=ENTRA_ISSUER,
            options={
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
        return claims

    except jwt.ExpiredSignatureError:
        logger.warning("[Auth] Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidAudienceError:
        logger.warning("[Auth] Invalid audience")
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.InvalidIssuerError:
        logger.warning("[Auth] Invalid issuer")
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except (jwt.DecodeError, jwt.InvalidTokenError) as e:
        logger.warning(f"[Auth] Token validation failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except PyJWKClientError as e:
        logger.error(f"[Auth] JWKS fetch/key error: {e}")
        raise HTTPException(status_code=401, detail="Could not validate token signing key")
    except Exception as e:
        logger.error(f"[Auth] Unexpected auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


def extract_user_id_from_claims(claims: dict) -> str:
    """
    Extract a user identifier from JWT claims.

    Priority:
    1. preferred_username  — usually the UPN / email (e.g. CWID@bayer.com)
    2. upn                 — fallback (v1.0 tokens or optional claim)
    3. email               — fallback
    4. oid                 — object ID (always present, last resort)
    """
    user_id = (
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("email")
        or claims.get("oid")
    )
    if not user_id:
        raise HTTPException(status_code=401, detail="No user identifier in token")
    return user_id


async def get_authenticated_user_id(
    request: Request,
    user_id: Optional[str] = Header(None, alias="user-id"),
) -> str:
    """
    FastAPI dependency that returns a validated user-id.

    - When ENTRA_SSO_ENABLED=true:
        Extracts Bearer token from the Authorization header, validates it,
        and returns the user identity from the token claims.
        The `user-id` header is IGNORED (token is the source of truth).

    - When ENTRA_SSO_ENABLED=false (local dev):
        Falls back to the `user-id` header (same as before — "local-user"
        for dev, proxy-injected for non-SSO cloud).
    """
    if not ENTRA_SSO_ENABLED:
        # ── Legacy / local-dev: trust the header ──
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=422, detail="Missing user-id header")
        sanitized = user_id.strip()
        if "/" in sanitized or "\\" in sanitized or ".." in sanitized:
            raise HTTPException(status_code=400, detail="Invalid user-id header")
        return sanitized

    # ── SSO mode: validate Bearer token ──
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
        )

    token = auth_header[len("Bearer "):]
    claims = validate_access_token(token)
    user_id_from_token = extract_user_id_from_claims(claims)

    logger.info(f"[Auth] Authenticated user: {user_id_from_token}")
    return user_id_from_token
