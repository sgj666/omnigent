"""Environment-backed standalone Feishu configuration."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _data_dir() -> Path:
    configured = os.environ.get("OMNIGENT_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".omnigent"


_RUNTIME_KEYS = (
    "OMNIGENT_SERVER_URL",
    "OMNIGENT_FEISHU_CREDENTIAL_KEY",
    "OMNIGENT_FEISHU_DATABASE_PATH",
    "OMNIGENT_FEISHU_HOST",
    "OMNIGENT_FEISHU_PORT",
    "OMNIGENT_FEISHU_ACTION_SECRET",
    "OMNIGENT_FEISHU_CORE_BEARER",
)


def _load_runtime_settings() -> None:
    """Restore service settings before pydantic reads the process environment."""
    database = Path(
        os.environ.get("OMNIGENT_FEISHU_DATABASE_PATH", _data_dir() / "omnigent_feishu.sqlite3")
    ).expanduser()
    try:
        with sqlite3.connect(database) as db:
            rows = db.execute(
                "SELECT key, value FROM schema_meta WHERE key LIKE 'feishu.runtime.%'"
            ).fetchall()
    except sqlite3.Error:
        return
    for key, value in rows:
        name = str(key).removeprefix("feishu.runtime.")
        if name in _RUNTIME_KEYS and name not in os.environ:
            os.environ[name] = str(value)


class FeishuConfig(BaseSettings):
    """Settings for exactly one standalone Feishu service process."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    def __init__(self, **values: object) -> None:
        _load_runtime_settings()
        super().__init__(**values)

    server_url: str = Field(validation_alias="OMNIGENT_SERVER_URL")
    credential_key: str = Field(validation_alias="OMNIGENT_FEISHU_CREDENTIAL_KEY")
    database_path: Path = Field(
        default_factory=lambda: _data_dir() / "omnigent_feishu.sqlite3",
        validation_alias="OMNIGENT_FEISHU_DATABASE_PATH",
    )
    host: str = Field(default="127.0.0.1", validation_alias="OMNIGENT_FEISHU_HOST")
    port: int = Field(default=8011, ge=1, le=65535, validation_alias="OMNIGENT_FEISHU_PORT")
    verification_token: str | None = Field(
        default=None, validation_alias="OMNIGENT_FEISHU_VERIFICATION_TOKEN"
    )
    encrypt_key: str | None = Field(default=None, validation_alias="OMNIGENT_FEISHU_ENCRYPT_KEY")
    action_secret: str = Field(validation_alias="OMNIGENT_FEISHU_ACTION_SECRET")
    core_bearer: str | None = Field(default=None, validation_alias="OMNIGENT_FEISHU_CORE_BEARER")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://127.0.0.1", "http://localhost", "https://")):
            raise ValueError("OMNIGENT_SERVER_URL must use HTTPS or loopback HTTP")
        return normalized

    @field_validator("credential_key", "action_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("secret must contain at least 16 characters")
        return value

    def runtime_settings(self) -> dict[str, str]:
        values = {
            "OMNIGENT_SERVER_URL": self.server_url,
            "OMNIGENT_FEISHU_CREDENTIAL_KEY": self.credential_key,
            "OMNIGENT_FEISHU_DATABASE_PATH": str(self.database_path),
            "OMNIGENT_FEISHU_HOST": self.host,
            "OMNIGENT_FEISHU_PORT": str(self.port),
            "OMNIGENT_FEISHU_ACTION_SECRET": self.action_secret,
        }
        if self.core_bearer:
            values["OMNIGENT_FEISHU_CORE_BEARER"] = self.core_bearer
        return values


__all__ = ["FeishuConfig"]
