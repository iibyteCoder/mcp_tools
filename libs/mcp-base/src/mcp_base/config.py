"""Configuration management for MCP servers."""

from abc import ABC
from typing import Any

from pydantic_settings import BaseSettings


class BaseConfig(BaseSettings, ABC):
    """Base configuration class for MCP servers.

    Subclasses should define their specific configuration fields.
    All fields can be overridden via environment variables.
    """

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def to_connection_params(self) -> dict[str, Any]:
        """Convert config to connection parameters.

        Override this method in subclasses to provide
        connection-specific parameters.
        """
        return self.model_dump(exclude_none=True)
