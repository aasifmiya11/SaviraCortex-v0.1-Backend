# 7. Authorization

Authorization is enforced at two distinct layers: Firebase establishes the caller's external identity, and SaviraCortex applies its own user, organization-membership and role rules.

## Firebase identity verification

Authenticated API routes use `get_verified_firebase_claims` from `app/core/dependencies.py`. It requires a Bearer token and verifies the Firebase ID token through Firebase Admin. Missing, invalid, expired or revoked credentials are rejected. Firebase service availability/configuration failures are returned as service errors rather than exposing SDK internals or token contents.

The verified Firebase `uid` is not itself a SaviraCortex authorization grant. Services resolve that UID to a row in the SaviraCortex `User` table.

## Organization signup and identity

- `POST /api/v1/auth/organizations/signup` creates the SaviraCortex user, organization and initial organization membership for an authenticated Firebase identity.
- Verified email identities and verified phone identities are accepted according to the signup service's provider/claim validation.
- `GET /api/v1/auth/me` resolves the authenticated user and returns organization membership summaries.
- The organization membership role is represented in the profile response (currently `owner`, `admin` or `member`).

## Department authorization

Department endpoints are organization-scoped:

- `GET /api/v1/organizations/{organization_id}/departments`: caller must resolve to a registered SaviraCortex user and have membership in the requested organization.
- `POST /api/v1/organizations/{organization_id}/departments`: same identity and membership checks, plus the membership role must be `owner` or `admin`.

Expected service behavior:
- Missing Firebase UID: 401.
- Firebase UID not registered in SaviraCortex: 404.
- No membership in requested organization: 404 (organization not found or caller is not a member).
- A non-admin member attempting creation: 403.
- Duplicate department name in the same organization: 409.
- Successful creation: 201.

The UI hides the department-creation form from ordinary members, but this is only a usability measure. The backend service is the security boundary and enforces the role check independently.

## Document authorization

The document retrieval authorization system remains separate from the department-management endpoints. `AuthorizationRepository` computes accessible logical document IDs and a version catalogue. `AuthorizationService` exposes these operations. Access sources include organization owner/admin membership, explicit user/role/department allows and department assignment. Explicit matching denies override allows, including the organization owner/admin implicit allow. A user without organization membership receives no document access.

`RetrievalOrchestrator` constrains retrieval to the authorized catalogue and exact version IDs. Vector similarity is not authorization. The separate Redis/Valkey-backed `AuthorizationCacheService` is implemented but is not currently wired into the retrieval orchestrator's direct authorization-service path.

## Security requirements and open verification

- Never trust a client-supplied organization ID without checking the authenticated user's membership.
- Never treat a Firebase-authenticated identity as automatically registered in SaviraCortex.
- Preserve tenant scope in relational queries and vector-store filters.
- Preserve deny-overrides-allow behavior for document ACLs.
- Keep secrets, Firebase tokens and document contents out of logs.
- Add service/API tests for department role checks, cross-organization access and duplicate handling before calling this feature fully integration-verified.
