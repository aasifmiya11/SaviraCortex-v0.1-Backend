import os
from dotenv import load_dotenv

load_dotenv()


def get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"true", "1", "yes", "on"}


class Settings:
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL")

    OCR_ENGINE = os.getenv("OCR_ENGINE")
    OCR_LANGS = os.getenv("OCR_LANGS")

    RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
    MIN_NATIVE_CHARS = int(os.getenv("MIN_NATIVE_CHARS", "50"))

    OCR_ALL_PAGES = get_bool("OCR_ALL_PAGES")
    OCR_MERGE_WITH_NATIVE = get_bool("OCR_MERGE_WITH_NATIVE")

    FASTOCR_API_KEY = os.getenv("FASTOCR_API_KEY")

    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    QDRANT_API_ENDPOINT = os.getenv("QDRANT_API_ENDPOINT")
    QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME")

    # Firebase Admin SDK configuration for server-side ID-token verification.
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL")
    FIREBASE_SERVICE_ACCOUNT_PATH = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_PATH",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "app",
            "secrets",
            "firebase-service-account.json",
        ),
    )

    AIVEN_POSTGRES_URI = os.getenv("AIVEN_POSTGRES_URI")
    if AIVEN_POSTGRES_URI and AIVEN_POSTGRES_URI.startswith("postgres://"):
        AIVEN_POSTGRES_URI = AIVEN_POSTGRES_URI.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )

    AIVEN_REDIS_URI = os.getenv("AIVEN_REDIS_URI")

    # Organization invitation email delivery (SMTP).
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM")
    SMTP_USE_SSL = get_bool("SMTP_USE_SSL", False)
    SMTP_STARTTLS = get_bool("SMTP_STARTTLS", True)
    INVITATION_EXPIRY_DAYS = int(os.getenv("INVITATION_EXPIRY_DAYS", "7"))
    FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
    if INVITATION_EXPIRY_DAYS < 1:
        raise ValueError("INVITATION_EXPIRY_DAYS must be at least 1.")

    B2_KEY_ID = os.getenv("B2_KEY_ID")
    B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
    B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")
    B2_REGION = os.getenv("B2_REGION")
    B2_ENDPOINT_URL = os.getenv("B2_ENDPOINT_URL")
    B2_STORAGE_PREFIX = os.getenv("B2_STORAGE_PREFIX", "voice-ai/")

    QDRANT_SUMMARY_COLLECTION_NAME = os.getenv(
        "QDRANT_SUMMARY_COLLECTION_NAME",
        f"{QDRANT_COLLECTION_NAME}_summaries" if QDRANT_COLLECTION_NAME else None,
    )

    # Isolated retrieval-evaluation resources. Keep these separate from the
    # production Qdrant collections and B2 storage prefix.
    EVAL_ORGANIZATION_ID = os.getenv("SAVIRACORTEX_EVAL_ORGANIZATION_ID")
    EVAL_USER_ID = os.getenv("SAVIRACORTEX_EVAL_USER_ID")
    EVAL_QDRANT_COLLECTION_NAME = os.getenv(
        "SAVIRACORTEX_EVAL_QDRANT_COLLECTION"
    )
    EVAL_QDRANT_SUMMARY_COLLECTION_NAME = os.getenv(
        "SAVIRACORTEX_EVAL_QDRANT_SUMMARY_COLLECTION"
    )
    EVAL_B2_STORAGE_PREFIX = os.getenv("SAVIRACORTEX_EVAL_B2_STORAGE_PREFIX")


settings = Settings()
