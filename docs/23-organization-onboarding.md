# Organization onboarding data model

Organization onboarding is saved as one transaction after the final wizard step.

## organization_departments

| Column | Purpose |
|---|---|
| id | UUID primary key for the department |
| organization_id | Owning organization, foreign key to organizations.id |
| name | Department name |
| description | Optional department description |
| created_by | User UUID of the creator, foreign key to users.id |

Database constraint: UNIQUE (organization_id, name). The same department name can be used by different organizations, but not twice in one organization.

## organization_roles

| Column | Purpose |
|---|---|
| id | UUID primary key for role assignments and references |
| organization_id | Owning organization, foreign key to organizations.id |
| name | Role name |
| description | Optional role description |

Database constraint: UNIQUE (organization_id, name). The same role name can be used by different organizations, but not twice in one organization.

No department-member rows are created during onboarding. Department membership assignments are added later through organization_department_memberships. User role assignments are added later through user_role_assignments.

## Signup payload

Departments and roles are sent as objects containing `name` and optional `description`. The backend assigns organization_id automatically from the organization being created, generates UUIDs, and sets department.created_by to the new owner user.

All organization, user, membership, department and role rows are committed together. Any failure rolls back the whole transaction.

## Fresh schema initialization

```powershell
cd backend
python -m scripts.init_database
```

The initializer calls SQLAlchemy `Base.metadata.create_all` after importing all models. This creates missing tables; it does not alter existing tables. If tables already exist with an older definition, reset only those affected tables in the development database or apply a deliberate schema migration before running the initializer.
