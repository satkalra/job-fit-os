from pydantic_settings import BaseSettings, SettingsConfigDict


LLM_PRICING: dict[str, tuple[float, float]] = {
    # model: (input_usd_per_1m_tokens, output_usd_per_1m_tokens)
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "gpt-5.5": (2.00, 8.00),
}

WEB_SEARCH_COST_USD: float = 0.010


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://jobfit:jobfit@localhost/jobfit_os"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    JSEARCH_API_KEY: str = ""
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
    ENABLE_REACT_SEARCH: bool = True
    ENABLE_ATS_SEARCH: bool = False


settings = Settings()
