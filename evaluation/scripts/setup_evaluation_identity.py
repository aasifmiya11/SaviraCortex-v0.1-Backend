"""Create an organization-scoped database identity for retrieval evaluation.

This creates a database-only service user (not a Firebase login), ensures the
user has an admin membership in the evaluation organization, and verifies the
effective document access through the application's authorization repository.

Run without --apply first to preview. Add --apply to commit the changes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from uuid import UUID, uuid5

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = logging.getLogger("evaluation.setup_identity")
EVALUATION_USER_NAMESPACE = "saviracortex-evaluation-service-user"


def _load_environment() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create/ensure the evaluation organization and its database-only "
            "admin service user."
        )
    )
    parser.add_argument(
        "--organization-id",
        default=os.getenv("SAVIRACORTEX_EVAL_ORGANIZATION_ID"),
        help="Existing evaluation organization UUID or configured environment value.",
    )
    parser.add_argument(
        "--organization-name",
        default=os.getenv(
            "SAVIRACORTEX_EVAL_ORGANIZATION_NAME",
            "SaviraCortex Evaluation",
        ),
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("SAVIRACORTEX_EVAL_USER_ID"),
        help=(
            "Optional stable user UUID. If omitted, a deterministic UUID is "
            "derived from the organization UUID."
        ),
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv(
            "SAVIRACORTEX_EVAL_USER_DISPLAY_NAME",
            "SaviraCortex Evaluation Runner",
        ),
    )
    parser.add_argument(
        "--email",
        default=os.getenv("SAVIRACORTEX_EVAL_USER_EMAIL"),
        help="Optional descriptive email; no email account is created.",
    )
    parser.add_argument(
        "--role",
        choices=("admin", "owner", "member"),
        default="admin",
        help="Organization membership role. Admin is recommended for evaluation.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes. Without this flag, the script only previews the plan.",
    )
    return parser.parse_args()


def main() -> int:
    _load_environment()
    args = _parse_args()

    if not args.organization_id:
        raise SystemExit(
            "Set SAVIRACORTEX_EVAL_ORGANIZATION_ID or pass --organization-id."
        )
    try:
        organization_id = UUID(args.organization_id)
    except ValueError as exc:
        raise SystemExit("--organization-id must be a valid UUID.") from exc

    if args.user_id:
        try:
            user_id = UUID(args.user_id)
        except ValueError as exc:
            raise SystemExit("--user-id must be a valid UUID.") from exc
    else:
        user_id = uuid5(organization_id, EVALUATION_USER_NAMESPACE)

    if not args.organization_name.strip():
        raise SystemExit("--organization-name cannot be empty.")
    if not args.display_name.strip():
        raise SystemExit("--display-name cannot be empty.")

    # Import only after loading .env so the application database settings exist.
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import Organization, OrganizationMembership, User
    from app.models.documents import Document
    from app.repositories.authorization_repository import AuthorizationRepository

    plan = {
        "organization_id": str(organization_id),
        "organization_name": args.organization_name.strip(),
        "user_id": str(user_id),
        "display_name": args.display_name.strip(),
        "email": args.email,
        "firebase_uid": None,
        "membership_role": args.role,
        "mode": "apply" if args.apply else "dry_run",
        "identity_type": "database-only service identity (not a login account)",
    }

    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        if organization is None:
            organization_action = "create"
        else:
            organization_action = "reuse"

        user = db.get(User, user_id)
        if user is None:
            user_action = "create"
        else:
            user_action = "reuse"

        membership = db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )
        membership_action = (
            "create" if membership is None
            else "update" if membership.role != args.role
            else "reuse"
        )

        plan["actions"] = {
            "organization": organization_action,
            "user": user_action,
            "membership": membership_action,
        }

        if not args.apply:
            print(json.dumps(plan, indent=2))
            print("\nDry run only. Re-run with --apply to commit.")
            return 0

        try:
            if organization is None:
                organization = Organization(
                    id=organization_id,
                    name=args.organization_name.strip(),
                )
                db.add(organization)
            elif organization.name != args.organization_name.strip():
                LOG.warning(
                    "Organization already exists with name %r; preserving it.",
                    organization.name,
                )

            if user is None:
                user = User(
                    id=user_id,
                    firebase_uid=None,
                    email=args.email,
                    display_name=args.display_name.strip(),
                )
                db.add(user)
            else:
                # Preserve an existing Firebase identity and existing email.
                # Only fill descriptive fields when they are currently empty.
                if not user.display_name:
                    user.display_name = args.display_name.strip()
                if args.email and not user.email:
                    user.email = args.email

            if membership is None:
                membership = OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user_id,
                    role=args.role,
                )
                db.add(membership)
            elif membership.role != args.role:
                membership.role = args.role

            db.commit()
        except Exception:
            db.rollback()
            raise

        # Verify effective access using the same repository used by the app.
        authorized_document_ids = AuthorizationRepository(db).get_authorized_document_ids(
            organization_id=organization_id,
            user_id=user_id,
        )
        organization_document_count = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.organization_id == organization_id,
                Document.archived.is_(False),
            )
        ) or 0

        result = {
            **plan,
            "status": "committed",
            "organization_document_count": organization_document_count,
            "authorized_document_count": len(authorized_document_ids),
            "authorization_check": (
                "all non-archived documents visible"
                if len(authorized_document_ids) == organization_document_count
                else (
                    "some documents are not visible; inspect explicit ACL denies "
                    "and membership state"
                )
            ),
            "note": (
                "Admin membership grants organization-wide access in the current "
                "authorization implementation, but explicit matching document "
                "ACL denies still override that grant."
            ),
        }
        print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("EVALUATION_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(main())
