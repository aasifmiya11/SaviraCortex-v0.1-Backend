# 7. Authorization

SaviraCortex uses Firebase to authenticate the external identity and PostgreSQL to authorize access inside an organization. Firebase authentication alone never grants access to organization data.

## Organization membership prerequisite

A caller must resolve to a SaviraCortex User and have an OrganizationMembership row for the requested organization. This membership check applies to every role, including owners and admins. Invitations do not grant access before account creation and membership acceptance; removing a member removes their membership and related assignments/ACL references.

All authorization predicates are tenant-scoped by the requested organization_id. Department and role assignments are also validated against that same organization.

## Document ACL data model

document_acl is the authoritative, normalized list of document access rules. A document may have any number of ACL rows for:
- principal_type = user with a specific organization member;
- principal_type = department with an organization department;
- principal_type = role with an organization-defined role.

Every row has effect = allow or effect = deny. This supports multiple departments, multiple roles, multiple users, and both positive and negative rules. The former singular documents.department_id field is not used; a document's department tags are the department-principal ACL rows. Member-to-department and member-to-role assignments remain many-to-many through organization_department_memberships and user_role_assignments.

Ingestion stores the selected allow/deny ID lists in document_ingestion_sessions while a file is awaiting review. Finalization validates that every selected principal still belongs to the organization, then writes the ACL rows together with the document registration transaction.

## Retrieval authorization formula

Let:
- M(u,o) mean user u has a membership row in organization o;
- R(u,o) be the roles assigned to the user in that organization;
- D(u,o) be the departments assigned to the user in that organization;
- AllowMatch(d,u,o) mean at least one allow ACL row for document d matches the user, one of their roles, or one of their departments;
- AnyAllow(d,o) mean the document has at least one allow ACL row of any principal type;
- DenyMatch(d,u,o) mean at least one deny ACL row matches the user, one of their roles, or one of their departments;
- OrgWide(d) be the document's organization_wide_access flag;
- Manager(u,o) mean the membership role is owner or admin.

Then:

    authorized(d,u,o) =
        M(u,o)
        AND NOT DenyMatch(d,u,o)
        AND (
            Manager(u,o)
            OR OrgWide(d)
            OR AllowMatch(d,u,o)
            OR NOT AnyAllow(d,o)
        )

The OR across user, role and department grants is intentional: matching any one assigned department or any one assigned role is sufficient. A user does not need to match every tag on a document.

### Precedence and default behavior

1. Organization membership is mandatory.
2. Any matching explicit deny wins over every allow, regardless of whether the deny is user-, role-, or department-level. It also blocks owners/admins from retrieving the document.
3. Otherwise, a matching explicit allow grants access even without a department or role match.
4. Otherwise, a matching department allow OR role allow grants access.
5. organization_wide_access = true grants retrieval access to every member of that organization, except members caught by a matching explicit deny.
6. If the document has no allow ACL rows and is not otherwise restricted by a matching deny, it is visible to all organization members. This includes a document with no department, role, or user tags. A deny-only document therefore remains visible to everyone except the denied principals.
7. If at least one allow ACL row exists, non-matching members are denied unless organization-wide access is enabled or they have an owner/admin implicit grant (still subject to deny).

Examples:
- A document allows Finance and Auditor. A member matching Finance OR Auditor can retrieve it.
- A document allows a specific user. Only that user receives the direct grant, unless another matching grant or organization-wide access also applies.
- A document allows the Auditor role but denies one user. The direct user deny wins even if that user is an Auditor.
- A document has no allow rows and no tags. Every member can retrieve it.
- A document is organization-wide but explicitly denies a department. Members of that department cannot retrieve it.

## Retrieval versus management

The deny rule is a retrieval restriction. An owner/admin who is an organization member can still manage the document, update its metadata or ACL, archive it, replace its version, or delete it even when a deny rule blocks retrieval. Management endpoints therefore enforce organization membership and owner/admin role, and use organization-scoped document lookup rather than the retrieval ACL predicate.

The PUT /api/v1/organizations/{organization_id}/documents/{document_id}/access endpoint replaces the full ACL set. It accepts department_allow_ids, department_deny_ids, role_allow_ids, role_deny_ids, user_allow_ids, user_deny_ids, and organization_wide_access. Only owners/admins may call it. Every supplied principal ID must belong to the same organization.

## Retrieval enforcement

AuthorizationRepository is the PostgreSQL source of truth. It returns authorized logical document IDs and a version catalogue. RetrievalOrchestrator constrains vector retrieval to those authorized IDs and exact version IDs; vector similarity, Qdrant metadata, or a client-supplied document ID is never an authorization grant. The Redis/Valkey authorization cache is not the source of truth and must not bypass the PostgreSQL check.

## Operational requirements

- Keep organization scope on every membership, principal validation, ACL and document query.
- Do not create membership rows for invitations before the invited user has completed account creation.
- Remove member-linked department/role assignments and ACL rows through the corresponding foreign-key cascades when membership is deleted.
- Never log secrets, Firebase tokens, or document contents.
- Re-run the authorization repository tests after any ACL change.
