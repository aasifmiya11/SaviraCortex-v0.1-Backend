# Organization invitation storage and expiry

## Defaults

- Invitation acceptance window: 7 days.
- Configure with `INVITATION_EXPIRY_DAYS`.
- Invitation links contain a cryptographically random token; PostgreSQL stores only its SHA-256 hash.
- The invitation record is scoped to an organization and the user who sent it.
- Pending invitations past `expires_at` are removed. The API must still check `expires_at` when a link is opened; cleanup timing is not an authorization check.

## SMTP environment

Add these variables to the backend environment (never commit real credentials):

```dotenv
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_SSL=false
SMTP_STARTTLS=true
FRONTEND_BASE_URL=http://localhost:3000
INVITATION_EXPIRY_DAYS=7
```

Use either implicit SSL (usually port 465, `SMTP_USE_SSL=true`, `SMTP_STARTTLS=false`) or STARTTLS (usually port 587, `SMTP_USE_SSL=false`, `SMTP_STARTTLS=true`). Do not enable both.

## Create the table

`OrganizationInvitation` is registered in `app.models`, and `create_tables()` imports it before calling SQLAlchemy `Base.metadata.create_all`. That creates the new table when the project's database initialization function is run. `create_all` does not alter existing tables.

## Automatic cleanup

A PostgreSQL trigger cannot run merely because time passed. Triggers run in response to INSERT/UPDATE/DELETE events. The cleanup is therefore exposed as a small repeatable Python job:

```powershell
cd E:\\SaviraCortex\\backend
.venv\\Scripts\\python.exe scripts\\cleanup_expired_invitations.py
```

Schedule that command once per day using Windows Task Scheduler (or your deployment scheduler). Suggested run time: 02:15 server time. It deletes pending invitations where `expires_at <= NOW()`. It does not delete accepted or revoked invitation records.

The job is safe to run repeatedly. Do not rely on it to reject expired links; the invitation validation endpoint must independently reject expired records.
