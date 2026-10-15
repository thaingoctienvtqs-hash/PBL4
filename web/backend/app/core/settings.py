from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

WEB_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=WEB_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    db_backend: Literal["mssql"] = "mssql"
    db_server: str = "localhost"
    db_instance: str = ""
    db_port: int | None = 1433
    db_name: str = "pbl4_art_guard"
    db_driver: str = "ODBC Driver 17 for SQL Server"
    db_trusted_connection: bool = True
    db_username: str = ""
    db_password: str = ""
    db_encrypt: bool = True
    db_trust_server_certificate: bool = False
    app_env: str = "development"
    jwt_secret_key: str = ""
    jwt_expire_minutes: int = 60
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @model_validator(mode="after")
    def validate_database_authentication(self):
        if self.db_trusted_connection and (self.db_username or self.db_password):
            raise ValueError("Leave DB_USERNAME and DB_PASSWORD empty when DB_TRUSTED_CONNECTION=true")
        if not self.db_trusted_connection and not self.db_username.strip():
            raise ValueError("DB_USERNAME is required when DB_TRUSTED_CONNECTION=false")
        if not self.db_trusted_connection and not self.db_password:
            raise ValueError("DB_PASSWORD is required when DB_TRUSTED_CONNECTION=false")
        if not self.db_server.strip():
            raise ValueError("DB_SERVER cannot be empty")
        if not self.db_driver.strip():
            raise ValueError("DB_DRIVER cannot be empty")
        if not self.db_name.strip():
            raise ValueError("DB_NAME cannot be empty")
        if not self.db_instance.strip() and self.db_port is None:
            raise ValueError("Set DB_PORT when DB_INSTANCE is empty")
        return self

    @field_validator("jwt_secret_key")
    @classmethod
    def require_secret_in_production(cls, value: str, info):
        environment = info.data.get("app_env", "development")
        if environment == "production" and (not value or value.startswith("replace-this")):
            raise ValueError("JWT_SECRET_KEY must be set to a strong random value in production")
        return value or "development-only-change-me-before-deploying"

    @property
    def database_url(self) -> URL:
        server = self.db_server.strip()
        instance = self.db_instance.strip()
        if instance:
            server = f"{server}\\{instance}"

        query = {
            "driver": self.db_driver,
            "Encrypt": "yes" if self.db_encrypt else "no",
            "TrustServerCertificate": "yes" if self.db_trust_server_certificate else "no",
        }
        if self.db_trusted_connection:
            query["Trusted_Connection"] = "yes"

        return URL.create(
            "mssql+pyodbc",
            username=None if self.db_trusted_connection else self.db_username,
            password=None if self.db_trusted_connection else self.db_password,
            host=server,
            port=None if instance else self.db_port,
            database=self.db_name,
            query=query,
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


settings = Settings()
