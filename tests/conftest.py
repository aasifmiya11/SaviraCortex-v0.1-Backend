import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db, get_verified_firebase_claims
from app.core.database import Base
from app.main import app
from app.models import (
    Organization, OrganizationDepartment, OrganizationDepartmentMembership,
    OrganizationInvitation, OrganizationMembership, OrganizationRole,
    User, UserRoleAssignment, Document, DocumentVersion,
    DocumentIngestionSession,
)

TEST_TABLES = [
    User.__table__, Organization.__table__, OrganizationMembership.__table__,
    OrganizationRole.__table__, UserRoleAssignment.__table__,
    OrganizationDepartment.__table__, OrganizationDepartmentMembership.__table__,
    OrganizationInvitation.__table__, Document.__table__,
    DocumentVersion.__table__, DocumentIngestionSession.__table__,
]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine, tables=TEST_TABLES)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield testing_session
    finally:
        testing_session.close()
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            Base.metadata.drop_all(bind=connection, tables=TEST_TABLES)
        engine.dispose()


@pytest.fixture
def firebase_claims():
    return {"uid": "firebase-owner-uid"}


@pytest.fixture
def client(db_session, firebase_claims):
    def override_db():
        yield db_session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_verified_firebase_claims] = lambda: firebase_claims
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(db_session):
    def override_db():
        yield db_session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides.pop(get_verified_firebase_claims, None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def organization_context(db_session):
    from uuid import uuid4

    owner = User(id=uuid4(), firebase_uid="firebase-owner-uid", email="owner@example.com", display_name="Organization Owner")
    organization = Organization(id=uuid4(), name="Savira Labs")
    db_session.add_all([owner, organization])
    db_session.flush()
    owner_membership = OrganizationMembership(id=uuid4(), organization_id=organization.id, user_id=owner.id, role="owner")
    member_role = OrganizationRole(
        id=uuid4(), organization_id=organization.id, name="Member",
        description="Default role for organization members.",
    )
    db_session.add_all([owner_membership, member_role])
    db_session.commit()
    return {"owner": owner, "organization": organization, "owner_membership": owner_membership, "member_role": member_role}
