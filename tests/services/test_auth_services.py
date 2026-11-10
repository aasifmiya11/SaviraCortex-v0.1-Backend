from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.v1.auth import OrganizationSignupRequest
from app.services.auth import signup_service, identity_service


class FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def add_all(self, records):
        self.records = records

    def flush(self):
        self.flushed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeAuthRepository:
    user_by_uid = None
    user_by_email = None
    memberships = []

    def __init__(self, session):
        self.session = session
        self.created = None

    def get_user_by_firebase_uid(self, uid):
        return type(self).user_by_uid

    def get_user_by_email(self, email):
        return type(self).user_by_email

    def get_memberships_for_user(self, user_id):
        return type(self).memberships

    def create_signup_records(self, *, user, organization, membership):
        self.created = (user, organization, membership)


@pytest.fixture(autouse=True)
def reset_repository(monkeypatch):
    FakeAuthRepository.user_by_uid = None
    FakeAuthRepository.user_by_email = None
    FakeAuthRepository.memberships = []
    monkeypatch.setattr(signup_service, "AuthRepository", FakeAuthRepository)
    monkeypatch.setattr(identity_service, "AuthRepository", FakeAuthRepository)


@pytest.mark.parametrize(
    "claims",
    [
        {"uid": "email-uid", "email": "USER@example.com", "email_verified": True,
         "firebase": {"sign_in_provider": "password"}},
        {"uid": "google-uid", "email": "user@gmail.com", "email_verified": True,
         "firebase": {"sign_in_provider": "google.com"}},
        {"uid": "phone-uid", "phone_number": "+919876543210", "email_verified": False,
         "firebase": {"sign_in_provider": "phone"}},
    ],
)
def test_signup_accepts_verified_email_google_and_phone(claims):
    session = FakeSession()
    service = signup_service.OrganizationSignupService(session)
    payload = OrganizationSignupRequest(
        organization_name="Savira Labs",
        admin_name="Alex Admin",
        departments=[{"name":"Engineering","description":"Builds products"}],
        roles=[{"name":"Manager","description":"Team manager"}],
    )

    result = service.signup(payload, claims)

    assert result.message == "Organization registered successfully."
    assert result.role == "owner"
    assert session.committed is True
    assert session.rolled_back is False


def test_signup_normalizes_email():
    session = FakeSession()
    service = signup_service.OrganizationSignupService(session)
    service.signup(
        OrganizationSignupRequest(organization_name="Acme", admin_name="Alex", departments=[{"name":"Engineering"}], roles=[{"name":"Manager"}]),
        {"uid": "u1", "email": "  USER@Example.COM ", "email_verified": True},
    )
    assert session.committed is True


def test_signup_rejects_unverified_email_without_phone():
    service = signup_service.OrganizationSignupService(FakeSession())
    with pytest.raises(HTTPException) as exc:
        service.signup(
            OrganizationSignupRequest(organization_name="Acme", admin_name="Alex", departments=[{"name":"Engineering"}], roles=[{"name":"Manager"}]),
            {"uid": "u1", "email": "user@example.com", "email_verified": False},
        )
    assert exc.value.status_code == 403


def test_signup_rejects_missing_uid():
    service = signup_service.OrganizationSignupService(FakeSession())
    with pytest.raises(HTTPException) as exc:
        service.signup(
            OrganizationSignupRequest(organization_name="Acme", admin_name="Alex", departments=[{"name":"Engineering"}], roles=[{"name":"Manager"}]),
            {"email": "user@example.com", "email_verified": True},
        )
    assert exc.value.status_code == 401


def test_signup_rejects_existing_firebase_uid():
    FakeAuthRepository.user_by_uid = object()
    service = signup_service.OrganizationSignupService(FakeSession())
    with pytest.raises(HTTPException) as exc:
        service.signup(
            OrganizationSignupRequest(organization_name="Acme", admin_name="Alex", departments=[{"name":"Engineering"}], roles=[{"name":"Manager"}]),
            {"uid": "existing", "email": "user@example.com", "email_verified": True},
        )
    assert exc.value.status_code == 409


def test_signup_rolls_back_after_database_error(monkeypatch):
    session = FakeSession()
    def fail_create(records):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(session, "add_all", fail_create)
    service = signup_service.OrganizationSignupService(session)
    with pytest.raises(RuntimeError):
        service.signup(
            OrganizationSignupRequest(organization_name="Acme", admin_name="Alex", departments=[{"name":"Engineering"}], roles=[{"name":"Manager"}]),
            {"uid": "u1", "email": "user@example.com", "email_verified": True},
        )
    assert session.rolled_back is True


def test_identity_service_returns_organization_membership(monkeypatch):
    user_id = uuid4()
    org_id = uuid4()
    user = SimpleNamespace(
        id=user_id, firebase_uid="firebase-uid", email="user@gmail.com",
        phone_number=None, display_name="Alex",
    )
    membership = SimpleNamespace(
        organization_id=org_id, role="admin",
        organization=SimpleNamespace(name="Savira Labs", onboarding_completed_at=None),
    )
    monkeypatch.setattr(FakeAuthRepository, "get_user_by_firebase_uid", lambda self, uid: user)
    monkeypatch.setattr(FakeAuthRepository, "get_memberships_for_user", lambda self, uid: [membership])

    result = identity_service.AuthIdentityService(FakeSession()).get_current_user(
        {"uid": "firebase-uid", "firebase": {"sign_in_provider": "google.com"}}
    )

    assert result.firebase_uid == "firebase-uid"
    assert result.sign_in_provider == "google.com"
    assert result.organizations[0].organization_name == "Savira Labs"
    assert result.organizations[0].role == "admin"


def test_identity_service_rejects_unregistered_firebase_user():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(FakeAuthRepository, "get_user_by_firebase_uid", lambda self, uid: None)
    try:
        with pytest.raises(HTTPException) as exc:
            identity_service.AuthIdentityService(FakeSession()).get_current_user({"uid": "unknown"})
        assert exc.value.status_code == 404
    finally:
        monkeypatch.undo()
