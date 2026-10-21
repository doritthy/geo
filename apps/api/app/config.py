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

    # Autodesk Platform Services (optional). Without credentials the
    # integration endpoints report "not configured" and RVT uploads ask for IFC.
    APS_CLIENT_ID: str = ""
    APS_CLIENT_SECRET: str = ""
    APS_CALLBACK_URL: str = "http://localhost:8000/api/integrations/autodesk/callback"
    APS_WEBHOOK_URL: str = ""  # public URL of /api/integrations/autodesk/webhook
    APS_WEBHOOK_SECRET: str = ""  # per-hook token; callbacks verified via x-adsk-signature
    APS_BASE_URL: str = "https://developer.api.autodesk.com"
    PUBLIC_WEB_URL: str = "http://localhost:3000"

    @property
    def aps_configured(self) -> bool:
        return bool(self.APS_CLIENT_ID and self.APS_CLIENT_SECRET)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
