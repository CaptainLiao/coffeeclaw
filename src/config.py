from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM Providers
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Database
    postgres_dsn: str = "postgresql+asyncpg://user:pass@localhost:5432/coffeeclaw"
    redis_url: str = "redis://localhost:6379/0"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # Agent Defaults
    default_primary_model: str = "gpt-4o"
    default_fallback_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
