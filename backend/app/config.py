import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


class Settings:
    APP_TITLE: str = os.getenv("APP_TITLE", "ShopEase Refund Agent API")
    GEMINI_API_KEY: str = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", os.getenv("MODEL_NAME", "gemini-2.5-flash"))
    GEMINI_FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite").strip()
    GEMINI_MAX_OUTPUT_TOKENS: int = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
    GEMINI_THINKING_BUDGET: int = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
    MODEL_NAME: str = GEMINI_MODEL
    POLICY_EVALUATION_DATE: str = os.getenv("POLICY_EVALUATION_DATE", "2024-06-18")
    ALLOWED_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
        if origin.strip()
    ]
    DATA_DIR = PROJECT_ROOT / "data"

    @property
    def is_api_key_configured(self) -> bool:
        placeholders = {
            "YOUR_GEMINI_API_KEY_HERE",
            "YOUR_GOOGLE_API_KEY_HERE",
        }
        return bool(self.GEMINI_API_KEY and self.GEMINI_API_KEY not in placeholders)

    @property
    def use_gemini_only(self) -> bool:
        return True


settings = Settings()
