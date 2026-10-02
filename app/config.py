from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    backboard_api_key: str | None = None
    backboard_assistant_id: str | None = None
    backboard_model_provider: str = "openrouter"
    backboard_model_name: str = "google/gemma-3-27b-it"
    app_env: str = "development"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
