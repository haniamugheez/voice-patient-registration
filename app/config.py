"""Application configuration, loaded from environment variables.

Nothing sensitive is hardcoded here — every secret comes from the environment
(see .env.example). In local development a .env file is loaded automatically.
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # SQLite by default so the project runs with zero infrastructure.
    # Set DATABASE_URL to a Postgres URL in production for durable storage.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/patients.db")

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    # Shared secret that Vapi sends back on every webhook request in the
    # `x-vapi-secret` header. If unset, webhook auth is skipped (dev only).
    VAPI_SERVER_SECRET: str | None = os.getenv("VAPI_SERVER_SECRET")

    # Optional API key required on write endpoints of the public REST API.
    # If unset, the API is open (fine for a graded take-home demo).
    API_KEY: str | None = os.getenv("API_KEY")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    APP_NAME: str = "Voice AI Patient Registration"
    ENV: str = os.getenv("ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    SEED_ON_STARTUP: bool = os.getenv("SEED_ON_STARTUP", "true").lower() == "true"


settings = Settings()
