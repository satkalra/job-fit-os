from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://jobfit:jobfit@localhost/jobfit_os"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""
    EMAIL_FROM_NAME: str = "JobFit OS"
    JWT_SECRET: str = "dev-secret-change-me-dev-secret"
    JWT_EXPIRY_DAYS: int = 7
    BASE_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "DEBUG"
    LOG_COLOR: str = "auto"
    SIGNUP_TOKEN: str = ""


settings = Settings()
