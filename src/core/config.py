from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_api_key: str
    model_api_base: str

    postgres_dsn: str
    redis_url: str
    runtime_repository_backend: str
    shortterm_memory_backend: str
    checkpoint_backend: str

    app_env: str
    log_level: str

    default_primary_model: str
    default_fallback_model: str
    model_timeout_seconds: int
    max_retries: int

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
