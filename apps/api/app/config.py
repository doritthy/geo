from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://subsurface:subsurface@localhost:5432/subsurface"
    JWT_SECRET: str = "change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 1440
    JWT_ALGORITHM: str = "HS256"

    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "subsurface"
    S3_SECRET_KEY: str = "subsurface123"
    S3_BUCKET: str = "subsurface-data"

    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
