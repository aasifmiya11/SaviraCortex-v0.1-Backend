## Run

The Twilio voice webhook must be reachable from the internet. Use two PowerShell
terminals. In terminal 1, start the tunnel:

```powershell
ngrok http 5000
```

The configured URL is `https://spookily-passover-purity.ngrok-free.dev`. Keep that
exact URL active in ngrok, or update `PUBLIC_URL` in `.env` whenever ngrok assigns a
new one. In terminal 2, start the FastAPI app with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe main.py
```

Set these environment variables before starting the app:

```powershell
$env:TWILIO_ACCOUNT_SID = "your-account-sid"
$env:TWILIO_AUTH_TOKEN = "your-auth-token"
$env:TWILIO_PHONE_NUMBER = "+15551234567"
$env:PHONE_NUMBER = "+15557654321"
$env:PUBLIC_URL = "https://spookily-passover-purity.ngrok-free.dev"
$env:MODEL_API_KEY = "your-model-api-key"
```

The app calls `PHONE_NUMBER`, asks for speech, sends each transcript to the model,
and reads the generated response back over the phone. It then listens for the next
question.
