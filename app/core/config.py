
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

    AIVEN_POSTGRES_URI = os.getenv("AIVEN_POSTGRES_URI")
    if AIVEN_POSTGRES_URI and AIVEN_POSTGRES_URI.startswith("postgres://"):
        AIVEN_POSTGRES_URI = AIVEN_POSTGRES_URI.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )


settings = Settings()
