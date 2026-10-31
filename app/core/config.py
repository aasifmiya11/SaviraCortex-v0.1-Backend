from dotenv import load_dotenv
import os
load_dotenv()

class Settings:
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL")
    OCR_ENGINE: str = os.getenv("OCR_ENGINE")
    OCR_LANGS: str = os.getenv("OCR_LANGS")
    RENDER_DPI: int = int(os.getenv("RENDER_DPI"))
    MIN_NATIVE_CHARS: int = int(os.getenv("MIN_NATIVE_CHARS"))
    OCR_ALL_PAGES: bool = os.getenv("OCR_ALL_PAGES")
    OCR_MERGE_WITH_NATIVE: bool = os.getenv("OCR_MERGE_WITH_NATIVE")
    FASTOCR_API_KEY: str = os.getenv("FASTOCR_API_KEY")
settings = Settings()
