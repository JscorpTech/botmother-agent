"""JWT RS256 authentication — validates tokens issued by external auth service."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_security = HTTPBearer(auto_error=True)

# ── Public key loading ───────────────────────────────────────────────────

_public_key: str | None = None


def _load_public_key() -> str:
    global _public_key
    if _public_key:
        return _public_key

    # First try PUBLIC_KEY env var (base64-encoded or raw PEM from k8s secret)
    env_key = os.environ.get("PUBLIC_KEY")
    if env_key:
        import base64
        try:
            decoded = base64.b64decode(env_key).decode("utf-8")
            if "BEGIN PUBLIC KEY" in decoded:
                _public_key = decoded
                return _public_key
        except Exception:
            pass
        if "BEGIN PUBLIC KEY" in env_key:
            _public_key = env_key
            return _public_key

    # Fallback to file
    key_path = os.environ.get(
        "JWT_PUBLIC_KEY_PATH",
        str(Path(__file__).resolve().parent.parent / "keys" / "public.pem"),
    )
    with open(key_path, "r") as f:
        _public_key = f.read()
    return _public_key


# ── Token model ──────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    """Decoded JWT payload — fields from external auth service."""
    user_id: int | str
    email: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool = True
    role: str = "user"

    # raw claims
    exp: int | None = None
    iat: int | None = None


# ── Validation ───────────────────────────────────────────────────────────

def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token using RS256 public key."""
    try:
        public_key = _load_public_key()
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={
                "verify_exp": True,
                "verify_aud": False,
                "require": ["exp"],
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )

    # Manual exp safety check
    exp = payload.get("exp")
    if exp is not None and time.time() > exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )

    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> TokenPayload:
    """FastAPI dependency — extracts and validates JWT from Authorization header."""
    payload = decode_token(credentials.credentials)

    user_id = payload.get("user_id") or payload.get("sub") or payload.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
        )

    return TokenPayload(
        user_id=user_id,
        email=payload.get("email"),
        username=payload.get("username"),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        is_active=payload.get("is_active", True),
        role=payload.get("role", "user"),
        exp=payload.get("exp"),
        iat=payload.get("iat"),
    )
