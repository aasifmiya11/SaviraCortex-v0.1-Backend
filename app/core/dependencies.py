import logging
from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.firebase import verify_firebase_id_token

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    with get_db_session() as session:
        yield session


def get_verified_firebase_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A Firebase ID token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_firebase_id_token(credentials.credentials)
    except ImportError as exc:
        logger.exception("Firebase Admin SDK dependency is unavailable.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication dependencies are not installed.",
        ) from exc
    except ValueError as exc:
        logger.warning(
            "Firebase token verification/configuration failed: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Firebase ID token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        # Log the SDK exception type and code, never the token or credential data.
        error_code = getattr(exc, "code", None)
        logger.warning(
            "Firebase ID token verification failed: exception=%s error_code=%s",
            type(exc).__name__,
            error_code,
            exc_info=True,
        )

        from firebase_admin import auth, exceptions

        invalid_token_errors = (
            auth.InvalidIdTokenError,
            auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError,
            auth.UserDisabledError,
        )
        if isinstance(exc, invalid_token_errors):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The Firebase ID token is invalid, expired, or revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        if isinstance(exc, exceptions.FirebaseError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase authentication is temporarily unavailable.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication could not be initialized.",
        ) from exc
