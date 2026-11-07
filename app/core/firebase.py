from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

_FIREBASE_APP_NAME = "savirarag-auth"


@lru_cache(maxsize=1)
def _firebase_app() -> Any:
    """Initialize a dedicated Firebase Admin app from the configured service account.

    A named app prevents silently reusing the SDK's default app if another
    integration initialized that app with different credentials or a project.
    """
    import firebase_admin
    from firebase_admin import credentials

    service_account_path = Path(settings.FIREBASE_SERVICE_ACCOUNT_PATH).expanduser()
    if not service_account_path.is_absolute():
        service_account_path = Path(__file__).resolve().parents[2] / service_account_path

    if not service_account_path.is_file():
        raise RuntimeError("Firebase service-account file is missing or unreadable.")

    with service_account_path.open("r", encoding="utf-8") as service_account_file:
        service_account_info = json.load(service_account_file)

    service_account_project = service_account_info.get("project_id")
    configured_project = settings.FIREBASE_PROJECT_ID
    if configured_project and service_account_project != configured_project:
        raise RuntimeError(
            "FIREBASE_PROJECT_ID does not match the service-account project_id."
        )

    project_id = configured_project or service_account_project
    if not project_id:
        raise RuntimeError(
            "Firebase project ID is missing from both configuration and service account."
        )

    try:
        app = firebase_admin.get_app(_FIREBASE_APP_NAME)
    except ValueError:
        app = None

    if app is not None:
        if app.project_id != project_id:
            raise RuntimeError(
                "The initialized SaviraCortex Firebase Admin app uses a different project."
            )
        return app

    credential = credentials.Certificate(str(service_account_path))
    options: dict[str, str] = {"projectId": project_id}
    if settings.FIREBASE_DATABASE_URL:
        options["databaseURL"] = settings.FIREBASE_DATABASE_URL

    try:
        return firebase_admin.initialize_app(
            credential,
            options=options,
            name=_FIREBASE_APP_NAME,
        )
    except ValueError:
        # Handle a concurrent initializer without falling back to the default app.
        app = firebase_admin.get_app(_FIREBASE_APP_NAME)
        if app.project_id != project_id:
            raise RuntimeError(
                "The initialized SaviraCortex Firebase Admin app uses a different project."
            )
        return app


def verify_firebase_id_token(token: str) -> dict[str, Any]:
    """Verify a client Firebase ID token and return its trusted claims."""
    import firebase_admin.auth

    app = _firebase_app()
    return firebase_admin.auth.verify_id_token(token, app=app, check_revoked=True)
