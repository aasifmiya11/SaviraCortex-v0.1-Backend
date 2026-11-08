# Backend API Gateway environment settings

Add these two variables to `backend/.env`:

```dotenv
JINA_API_BASE_URL=http://127.0.0.1:8090/v1
JINA_API_KEY=replace-with-GATEWAY_API_KEY
```

Replace the placeholder with the value of `GATEWAY_API_KEY` from `api-gateway/.env`. Use the normal gateway client key only; **do not use `GATEWAY_ADMIN_API_KEY`**. Keep this backend copy in `backend/.env`; never commit real credentials or copy provider Jina keys into the backend.
