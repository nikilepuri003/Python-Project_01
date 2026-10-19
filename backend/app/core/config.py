from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/codepulse", alias="DATABASE_URL")
    ai_provider: str = Field(default="", alias="AI_PROVIDER")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="", alias="AI_MODEL")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_owner: str = Field(default="", alias="GITHUB_OWNER")
    github_repository: str = Field(default="", alias="GITHUB_REPOSITORY")
    github_base_branch: str = Field(default="main", alias="GITHUB_BASE_BRANCH")
    jwt_secret_key: str = Field(default="change-me-in-development", alias="JWT_SECRET_KEY")
    monitor_scheduler_enabled: bool = Field(default=True, alias="MONITOR_SCHEDULER_ENABLED")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
