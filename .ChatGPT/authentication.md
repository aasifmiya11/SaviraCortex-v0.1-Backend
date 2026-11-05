# SaviraCortex Authentication & Authorization Architecture

**Document:** Authentication architecture handoff  
**Date:** 5 November 2026  
**Status:** Core architecture agreed; implementation pending code inspection and development  
**Purpose:** Durable project memory for future GPT instances: agreed behavior, architecture, implementation responsibilities, and current progress.

> **Progress accuracy:** The architecture below is agreed with the user. Authentication code has not yet been implemented or verified. Do not describe endpoints, models, Firebase Admin initialization, invitation flow, or sessions as already existing. Inspect the backend workspace before coding.

## 1. Product and architectural context

SaviraCortex is a multi-tenant, organization-centric AI/chatbot platform. Organizations manage members, roles, departments, and knowledge/content operations. Chatbot requests require trustworthy identity and tenant context—particularly internal user_id and organization_id—so users must not access another organization's data.

Architecture patterns:
- Identity provider: Firebase Authentication.
- Application backend: FastAPI.
- Application identity and tenancy: internal User, Organization, and Organization Membership entities with distinct UUIDs.
- Authorization: membership-scoped Role-Based Access Control (RBAC).
- Browser session: secure server-managed cookie approach (details to be selected after inspecting existing backend stack).
- Multi-tenancy: every organization-scoped API/data operation validates membership and access rights.

PostgreSQL is a proposed database choice, not confirmed by inspecting project configuration. Do not assume a specific ORM, migration framework, or session implementation until backend inspection.

## 2. Frozen core decisions

1. Public signup is Organization Signup only.
2. The person initiating signup is a User and creates an Organization as part of the same signup process.
3. That person becomes the organization's initial administrator (org_admin).
4. Signup logically creates three linked records: User, Organization, and Organization Membership.
5. User ID and Organization ID are distinct UUIDs. Membership links the user to the organization and carries the role.
6. An admin is a User—not a separate identity class or Firebase account type.
7. An organization can have multiple admins.
8. Ordinary members are invited by an organization admin; no public self-signup for ordinary members.
9. Invited members receive an email activation/verification link (Firebase email-link or suitable verified invitation flow), and the invitee completes authentication themselves. Admins must not set or know invitees' passwords.
10. Sign-in uses the same Firebase identity mechanism for members and admins. A user may have memberships in multiple organizations; after authentication the application resolves/selects an authorized organization context.
11. A nonexistent account must not be silently created during sign-in. Direct the person to organization signup or invitation-based activation.
12. Authorization roles are assigned to memberships, not globally to the user.
13. Chatbot access requires authenticated user context and a validated organization membership.
14. Frontend code is not required to start backend API development; frontend integration follows after API contracts are defined and tested.

## 3. Entity model

### User
Represents a person, independent of role. Proposed fields:
- id: internal UUID primary key.
- firebase_uid: Firebase identity UID, unique.
- email: verified/normalized email.
- full_name.
- status (pending verification, active, suspended, disabled).
- created_at, updated_at.

### Organization
Represents a company or institution. Proposed fields:
- id: UUID primary key.
- name.
- organization_type (if supported by product requirements).
- status (pending, active, suspended, disabled).
- created_at, updated_at.

### Organization Membership
Association between User and Organization; role belongs here. Proposed fields:
- id: UUID primary key.
- user_id: FK to User.
- organization_id: FK to Organization.
- role: org_admin, member, viewer, etc.
- status: pending, active, suspended, revoked.
- department_id: optional FK (with department feature).
- created_at.

Add a uniqueness constraint for the user/organization membership pair, subject to business rules.

### Invitation
Tracks admin-issued member invitations. Proposed fields:
- id: UUID.
- organization_id.
- email (normalized).
- role (admin-authorized role).
- department_id (optional).
- invited_by (User UUID).
- status (pending, accepted, expired, revoked).
- expires_at, created_at.

### Department
Future organization substructure:
- id: UUID.
- organization_id: FK.
- name.
- created_at.

## 4. Role and permissions model

Initial roles:

### org_admin
Organization-scoped administrator. Intended permissions:
- Access organization admin dashboard.
- Invite/manage members and assign permitted roles.
- Create/manage departments.
- Ingest knowledge/content.
- Delete authorized content.
- Archive and unarchive content.
- Manage organization settings.
- Access organization-scoped chatbot resources.

### member
- Use chatbot and access authorized organization content/resources.
- No organization administration by default.

### viewer
- Read-only access to explicitly permitted resources.

### Future super_admin
A platform-level role may be added later. It is distinct from organization admin and is not part of initial implementation.

Authorization must be enforced server-side. Never trust a role from signup/invite payload without policy checks. During public organization signup, backend explicitly assigns org_admin to the initial membership.

## 5. Signup workflow — Organization Signup

Public signup asks for both registering person's details and organization details. Example fields (final schema aligned with code/product requirements):
- organization name (and optionally organization type)
- registering person's full name
- email address
- Firebase-supported authentication credential/flow

Flow:
1. Person chooses Organization Signup and submits required person/organization fields.
2. Pydantic schema validates payload.
3. Firebase Authentication establishes/validates identity and email verification according to chosen flow.
4. FastAPI verifies Firebase ID token/identity using Firebase Admin SDK.
5. Backend resolves or creates internal User record using trusted Firebase UID and normalized email.
6. Backend creates Organization record.
7. Backend creates Organization Membership connecting User to Organization.
8. Backend assigns org_admin to this initial membership.
9. Backend commits DB-side records consistently and establishes session after successful authentication.
10. User enters organization admin dashboard.

Illustrative request (exact fields and credential exchange TBD):

    {
      "organization_name": "Acme Corporation",
      "organization_type": "enterprise",
      "admin_name": "John Doe",
      "email": "john@acme.com"
    }

Illustrative response:

    {
      "message": "Organization registered successfully",
      "user_id": "<user-uuid>",
      "organization_id": "<organization-uuid>",
      "role": "org_admin"
    }

Credential safety: do not store plaintext passwords in SaviraCortex application DB. Firebase client SDK should handle password/email-link authentication according to Firebase-supported flow. Backend receives and verifies trusted token evidence. Keep Firebase service-account secrets outside source control and never log/print them.

Distributed consistency: Firebase and application DB do not share one transaction. Signup must be designed for idempotency and partial-failure recovery. Use DB transactions for User + Organization + Membership; choose a recovery strategy (e.g. pending registration state/retry/compensation) after examining stack. Avoid orphaned or duplicate organizations on retry.

## 6. Member invitation and activation workflow

1. Authenticated admin enters invitee email, role, and optional department in dashboard.
2. FastAPI verifies caller's active membership and invitation/role permissions in target organization.
3. Backend creates pending invitation with expiry and organization binding.
4. Invitation/activation email is sent through Firebase-supported email-link flow or appropriate secure invitation mechanism.
5. Invitee opens link and proves control of invited email through Firebase authentication/verification.
6. Backend validates invitation token/state, expiry, recipient email, and organization.
7. Backend resolves/creates User record and creates/activates membership with invited role.
8. Invitation becomes accepted; member accesses only that organization according to role.

Invitees complete their own activation. Do not treat a raw client-supplied email as proof of identity. Invitations must be revocable and expire.

## 7. Sign-in, session, and identity resolution

Sign-in flow:
1. User authenticates through Firebase (password or email-link, depending on enabled Firebase methods).
2. Frontend sends Firebase ID token to FastAPI session endpoint.
3. FastAPI verifies token with Firebase Admin SDK.
4. Backend maps Firebase UID to internal User UUID and verifies account status.
5. Backend retrieves active memberships and organizations.
6. If one membership exists, select according to policy; if multiple, client can request/select one, and backend validates it against memberships.
7. Backend establishes session and responds with current identity/membership context.

A user without an existing account gets a clear authentication failure/instruction; do not auto-create user or organization during login.

### Cookie/session security
Preferred browser session:
- HttpOnly cookie.
- Secure in production.
- Appropriate SameSite policy based on frontend/backend origins.
- Expiration and logout invalidation.
- CSRF protection for state-changing requests authenticated by cookies.
- Session rotation/revocation and server-side session storage policy selected after code inspection.

Do not assume storing Firebase ID token directly in a cookie is final implementation; decide based on existing dependencies and threat model.

## 8. Trusted organization context and chatbot authorization

Backend establishes trusted context from verified authentication and DB membership records:
- internal user_id
- organization_id
- membership ID
- role/permissions

Client may indicate desired organization context, but server validates membership and active status. Never trust supplied UUID or role as authorization proof.

Every organization-scoped endpoint and chatbot operation checks:
- session/token valid;
- user active;
- membership exists and is active;
- organization active;
- requested action allowed by role;
- resource belongs to authorized organization.

This is essential for tenant isolation, knowledge ingestion, retrieval, conversations, documents, archive/delete actions, and citations/document viewer. A citation/document ID is not an authorization grant; document access must be re-authorized on each request.

## 9. Planned API roadmap (not implemented)

1. POST /api/v1/auth/organizations/signup — create organization, registering user, and initial org_admin membership.
2. POST /api/v1/auth/session — verify Firebase identity and establish application session.
3. GET /api/v1/auth/me — return current user and authorized memberships/context.
4. POST /api/v1/auth/logout — invalidate session and clear cookie.
5. POST /api/v1/organizations/{organization_id}/invitations — admin invites member.
6. POST /api/v1/auth/invitations/accept — validate invitation and activate membership.
7. GET /api/v1/organizations/{organization_id}/members — list organization members.

Department CRUD, granular permissions, account recovery, admin role management, and further organization settings are later APIs.

## 10. Error semantics (proposed)

- 400 Bad Request: malformed/invalid business request.
- 401 Unauthorized: missing, expired, or invalid authentication.
- 403 Forbidden: authenticated but missing permission or membership.
- 404 Not Found: resource absent or intentionally concealed by access policy.
- 409 Conflict: duplicate/conflicting signup, invitation, or membership.
- 422 Unprocessable Entity: Pydantic schema validation errors.

Avoid leaking whether another tenant's resources exist.

## 11. Implementation plan

### Phase A — inspect backend (next action)
- Find actual backend workspace and FastAPI app entry point.
- Inspect configuration/env handling, database connection, ORM, migrations, existing API conventions, and installed dependencies.
- Inspect Firebase project configuration and service-account secret storage without exposing secrets.
- Confirm actual DB and session approach before selecting libraries or writing models.

### Phase B — organization signup
- Initialize Firebase Admin safely.
- Create Pydantic request/response schemas.
- Implement User, Organization, Membership models and migrations following repository conventions.
- Add uniqueness constraints and transactional consistency.
- Implement signup endpoint and assign initial org_admin.
- Add validation, idempotency/recovery, and focused tests.

### Phase C — session authentication
- Firebase ID token verification dependency.
- Establish secure application cookie session.
- /auth/me and logout.
- User status and organization membership resolution.
- Session and CSRF controls.

### Phase D — invitations and RBAC
- Invitation schema/model/service/API.
- Email-link activation/acceptance.
- Member listing and role checks.
- Organization-scoped authorization dependencies.

### Phase E — chatbot and tenant integration
- Add verified auth context to chat API/workflow.
- Scope retrieval, ingestion, conversation, and document access by organization.
- Integrate protected citation/document viewing.

Frontend can be built/integrated after backend API contract is established; it is not a prerequisite to backend endpoint development.

## 12. Handoff instructions for future GPT instances

- This file is the agreed authentication architecture memory.
- Architecture decisions are agreed; implementation is pending.
- Never claim code was written/tested unless inspected or verified in repository during that session.
- First inspect actual backend workspace and follow its existing patterns; do not assume PostgreSQL, SQLAlchemy, Alembic, cookie technology, or endpoint contracts are already configured.
- Begin with backend workspace inspection, then implement Organization Signup (User + Organization + initial admin membership) as the first milestone.
- Keep admin as a user and role on membership.
- Keep user UUID and organization UUID separate.
- Public signup creates organizations only; ordinary members join via admin invitation and self-activation.
- Firebase manages identity credentials; FastAPI/application DB manages internal identity mapping, organization, membership, and authorization.
- Enforce tenant authorization server-side on every organization-scoped operation.
