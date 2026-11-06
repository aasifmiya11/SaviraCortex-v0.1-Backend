from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import hashlib

from firebase_admin import auth as firebase_auth

from app.models import (
    OrganizationInvitation, OrganizationMembership, OrganizationRole,
    User, UserRoleAssignment,
)


def test_create_invitation_sends_email_and_lists_member_role(client, organization_context, monkeypatch):
    sent = {}
    def fake_send_invitation_email(**kwargs):
        sent.update(kwargs)
    monkeypatch.setattr("app.services.invitation_service.send_invitation_email", fake_send_invitation_email)
    org = organization_context["organization"]

    created = client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        json={"email": "  candidate@example.com ", "candidate_name": "Candidate Name", "role": "member"},
    )

    assert created.status_code == 201
    assert created.json()["email"] == "candidate@example.com"
    assert created.json()["custom_role"] == "Member"
    assert sent["to_email"] == "candidate@example.com"
    assert sent["token"]
    listed = client.get(f"/api/v1/organizations/{org.id}/invitations")
    assert listed.status_code == 200
    assert listed.json()[0]["custom_role"] == "Member"
    assert listed.json()[0]["status"] == "pending"


def test_admin_cannot_invite_another_admin(client, db_session, organization_context, firebase_claims, monkeypatch):
    from app.models import User

    org = organization_context["organization"]
    admin = User(id=uuid4(), firebase_uid="firebase-admin-uid", email="admin@example.com", display_name="Admin")
    db_session.add(admin)
    db_session.flush()
    db_session.add(OrganizationMembership(
        id=uuid4(), organization_id=org.id, user_id=admin.id, role="admin",
    ))
    db_session.commit()
    firebase_claims["uid"] = admin.firebase_uid
    monkeypatch.setattr("app.services.invitation_service.send_invitation_email", lambda **kwargs: None)

    response = client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        json={"email": "new-admin@example.com", "candidate_name": "New Admin", "role": "admin"},
    )

    assert response.status_code == 403


def test_invitation_preview_and_accept_assign_member_role(client, db_session, organization_context, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "app.services.invitation_service.send_invitation_email",
        lambda **kwargs: sent.update(kwargs),
    )
    org = organization_context["organization"]
    created = client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        json={"email": "member@example.com", "candidate_name": "New Employee"},
    )
    assert created.status_code == 201
    token = sent["token"]

    preview = client.get("/api/v1/invitations/preview", params={"token": token})
    assert preview.status_code == 200
    assert preview.json()["email"] == "member@example.com"
    assert preview.json()["organization_name"] == "Savira Labs"

    fake_firebase_user = SimpleNamespace(uid="firebase-member-uid")
    monkeypatch.setattr(firebase_auth, "create_user", lambda **kwargs: fake_firebase_user)
    monkeypatch.setattr(firebase_auth, "create_custom_token", lambda *args, **kwargs: b"custom-token")
    monkeypatch.setattr("app.services.invitation_service._firebase_app", lambda: object())

    accepted = client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "full_name": "New Employee", "password": "secure-pass-123"},
    )

    assert accepted.status_code == 201
    body = accepted.json()
    assert body["role"] == "member"
    assert body["custom_token"] == "custom-token"
    user = db_session.query(User).filter_by(email="member@example.com").one()
    membership = db_session.query(OrganizationMembership).filter_by(
        organization_id=org.id, user_id=user.id,
    ).one()
    assignment = db_session.query(UserRoleAssignment).filter_by(
        organization_id=org.id, user_id=user.id,
    ).one()
    member_role = db_session.query(OrganizationRole).filter_by(
        organization_id=org.id, name="Member",
    ).one()
    invitation = db_session.query(OrganizationInvitation).filter_by(email="member@example.com").one()
    assert membership.role == "member"
    assert assignment.role_id == member_role.id
    assert invitation.status == "accepted"

    replay = client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "full_name": "New Employee", "password": "secure-pass-123"},
    )
    assert replay.status_code == 410


def test_expired_invitation_is_rejected(client, db_session, organization_context):
    org = organization_context["organization"]
    raw_token = "expired-test-token-with-enough-length"
    invitation = OrganizationInvitation(
        id=uuid4(), organization_id=org.id,
        invited_by_user_id=organization_context["owner"].id,
        email="expired@example.com", candidate_name="Expired Candidate",
        invited_role="member", token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        status="pending", expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(invitation)
    db_session.commit()

    response = client.get("/api/v1/invitations/preview", params={"token": raw_token})
    assert response.status_code == 410
