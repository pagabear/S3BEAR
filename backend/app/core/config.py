from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "s3BEAR"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production-min-32-chars!!"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_PUBLIC_KEY: str = ""
    JWT_PRIVATE_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "change-me-in-production-min-32-chars!!":
            import warnings
            warnings.warn(
                "SECRET_KEY is using the default value! "
                "Set a strong SECRET_KEY in production via environment variable.",
                stacklevel=2,
            )
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/s3bear"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/s3bear"
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=500)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0, le=500)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=30, ge=1, le=300)

    # Azure Entra
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_REDIRECT_URI: str = "http://localhost:3000/auth/callback"
    AZURE_AUTHORITY: str = ""

    # Default admin seed (first-run only)
    DEFAULT_ADMIN_EMAIL: str = "admin@admin.com"
    DEFAULT_ADMIN_PASSWORD: str = ""

    # AWS / S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_ENDPOINT_URL: str = ""  # For MinIO / compatible S3
    S3_MAX_POOL_CONNECTIONS: int = Field(default=64, ge=1, le=1024)
    S3_STREAM_CHUNK_SIZE_KB: int = Field(default=1024, ge=64, le=16384)

    # Presigned / Multipart
    PRESIGNED_URL_BASE: str = ""  # External-facing S3 URL (e.g. http://localhost:9000). Falls back to AWS_ENDPOINT_URL
    MULTIPART_PART_SIZE_MB: int = 10
    PRESIGNED_URL_EXPIRY_SECONDS: int = 1800

    # Image transformation (on-the-fly resize/format via ?w=&h=&format=&q=&fit=)
    MAX_IMAGE_TRANSFORM_MB: int = 25  # source objects larger than this are served un-transformed

    # Public share access accounting
    SHARE_ACCESS_COUNTER_SHARDS: int = Field(default=16, ge=1, le=256)

    # Webhooks
    WEBHOOKS_ENABLED: bool = True
    WEBHOOK_MAX_ATTEMPTS: int = 4       # initial attempt + 3 retries
    WEBHOOK_TIMEOUT_SECONDS: int = 10
    WEBHOOK_DELIVERY_RETENTION_DAYS: int = 30

    # Audit Log
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_FILE_ENABLED: bool = True
    AUDIT_LOG_PATH: str = "/var/log/s3bear/audit"
    AUDIT_LOG_RETENTION_DAYS: int = 90

    @property
    def azure_authority_url(self) -> str:
        if self.AZURE_AUTHORITY:
            return self.AZURE_AUTHORITY
        return f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}"


settings = Settings()
