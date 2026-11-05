from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import settings


@lru_cache(maxsize=1)
def _firebase_app() -> Any:
    """Initialize Firebase Admin once using the configured service-account file."""
    import firebase_admin
    from firebase_admin import credentials

    try:
        return firebase_admin.get_app()
    except ValueError:
        credential = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        options: dict[str, str] = {}
        if settings.FIREBASE_PROJECT_ID:
            options["projectId"] = settings.FIREBASE_PROJECT_ID
        if settings.FIREBASE_DATABASE_URL:
            options["databaseURL"] = settings.FIREBASE_DATABASE_URL
        return firebase_admin.initialize_app(credential, options or None)


def verify_firebase_id_token(token: str) -> dict[str, Any]:
    """Verify a client Firebase ID token and return its trusted claims."""
    import firebase_admin.auth

    app = _firebase_app()
    return firebase_admin.auth.verify_id_token(token, app=app, check_revoked=True)
