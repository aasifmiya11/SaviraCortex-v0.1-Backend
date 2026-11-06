from uuid import UUID, uuid4

from app.models import Organization, OrganizationMembership, OrganizationRole, User


def test_create_organization_creates_owner_and_member_role(client, db_session):
    owner = User(id=uuid4(), firebase_uid="firebase-owner-uid", email="owner@example.com", display_name="Owner")
    db_session.add(owner)
    db_session.commit()

    response = client.post("/api/v1/organizations", json={"name": "  Savira Labs  "})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Savira Labs"
    assert body["role"] == "owner"
    organization_id = UUID(body["id"])
    membership = db_session.query(OrganizationMembership).filter_by(organization_id=organization_id).one()
    assert membership.user_id == owner.id
    assert membership.role == "owner"
    member_role = db_session.query(OrganizationRole).filter_by(organization_id=organization_id, name="Member").one()
    assert member_role.name == "Member"


def test_list_and_get_organizations_require_membership(client, organization_context):
    organization_id = str(organization_context["organization"].id)

    listed = client.get("/api/v1/organizations")
    fetched = client.get(f"/api/v1/organizations/{organization_id}")

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["organization_name"] == "Savira Labs"
    assert fetched.status_code == 200
    assert fetched.json()["role"] == "owner"


def test_update_organization_owner_can_rename(client, organization_context):
    organization_id = str(organization_context["organization"].id)

    response = client.patch(f"/api/v1/organizations/{organization_id}", json={"name": "Savira Cortex"})

    assert response.status_code == 200
    assert response.json()["name"] == "Savira Cortex"


def test_update_organization_rejects_non_member(client, organization_context, firebase_claims):
    firebase_claims["uid"] = "unregistered-firebase-uid"
    response = client.patch(
        f"/api/v1/organizations/{organization_context['organization'].id}",
        json={"name": "Unauthorized"},
    )
    assert response.status_code == 404


def test_organization_endpoints_reject_missing_bearer_token(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/organizations")
    assert response.status_code == 401
