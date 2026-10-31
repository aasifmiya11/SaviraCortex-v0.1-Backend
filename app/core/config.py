from dotenv import load_dotenv
import os
load_dotenv()

class Settings:
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL")
    
settings = Settings()
