from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.models import OrganizationInvitation


def delete_expired_invitations(session: Session) -> int:
    """Permanently remove pending invitations whose acceptance window elapsed."""
    statement = (
        delete(OrganizationInvitation)
        .where(
            OrganizationInvitation.status == "pending",
            OrganizationInvitation.expires_at <= func.now(),
        )
        .returning(OrganizationInvitation.id)
    )
    deleted_ids = session.scalars(statement).all()
    session.commit()
    return len(deleted_ids)
