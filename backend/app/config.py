from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/evaluator"

    # Anthropic
    anthropic_api_key: str = ""
    sonnet_model: str = "claude-sonnet-4-6"
    opus_model: str = "claude-opus-4-6"

    # Gmail OAuth
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_address: str = ""
    gmail_label_processed: str = "evaluator/processed"

    # GitHub
    github_token: str = ""

    # Worker
    worker_poll_interval_seconds: int = 5
    inbox_poll_interval_minutes: int = 2

    # Auth (dashboard)
    allowed_emails: str = ""  # comma-separated allowlist
    nextauth_jwt_secret: str = ""

    # Branding
    company_name: str = "Plum"

    # Classifier — minimum confidence for routing an email to intake_review
    caveat_confidence_threshold: float = 0.7

    @property
    def allowed_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
