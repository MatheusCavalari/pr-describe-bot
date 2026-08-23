from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
