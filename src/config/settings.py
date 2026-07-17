"""Centralized application settings loaded from environment variables and .env files."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = Field(default="Anamnesis API", alias="APP_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_key: str = Field(default="change-me", alias="API_KEY")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost", "http://127.0.0.1"], alias="CORS_ORIGINS")
    max_text_length: int = Field(default=12000, alias="MAX_TEXT_LENGTH")
    nlp_provider_timeout_seconds: int = Field(default=10, alias="NLP_PROVIDER_TIMEOUT_SECONDS")
    database_dsn: str = Field(default="postgresql+psycopg://app:app@postgres:5432/anamnesis_db", alias="DATABASE_DSN")
    db_ssl_mode: str = Field(default="disable", alias="DB_SSL_MODE")
    db_ssl_ca: str = Field(default="", alias="DB_SSL_CA")
    db_ssl_cert: str = Field(default="", alias="DB_SSL_CERT")
    db_ssl_key: str = Field(default="", alias="DB_SSL_KEY")
    prompt_version: str = Field(default="v1", alias="PROMPT_VERSION")
    nlp_provider: str = Field(default="google", alias="NLP_PROVIDER")
    anonymizer_module: str = Field(default="", alias="ANONYMIZER_MODULE")
    anonymizer_class: str = Field(default="", alias="ANONYMIZER_CLASS")
    google_nlp_endpoint: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        alias="GOOGLE_NLP_ENDPOINT",
    )
    google_nlp_model: str = Field(default="gemini-1.5-flash", alias="GOOGLE_NLP_MODEL")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    google_nlp_max_retries: int = Field(default=3, alias="GOOGLE_NLP_MAX_RETRIES")
    google_nlp_base_backoff_seconds: float = Field(default=1.0, alias="GOOGLE_NLP_BASE_BACKOFF_SECONDS")
    google_nlp_max_backoff_seconds: float = Field(default=8.0, alias="GOOGLE_NLP_MAX_BACKOFF_SECONDS")
    qwen_nlp_endpoint: str = Field(default="http://ollama:11434/api/generate", alias="QWEN_NLP_ENDPOINT")
    qwen_nlp_model: str = Field(default="qwen2.5:7b-instruct", alias="QWEN_NLP_MODEL")
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return ["http://localhost", "http://127.0.0.1"]

    @field_validator("nlp_provider")
    @classmethod
    def validate_nlp_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"google", "qwen"}:
            raise ValueError("NLP_PROVIDER must be either 'google' or 'qwen'")
        return normalized


@lru_cache

def get_settings() -> Settings:
    return Settings()
