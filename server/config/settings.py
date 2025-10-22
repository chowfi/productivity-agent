"""
Configuration Management System

Simple settings for the task scheduler server.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Simple server settings for task scheduler."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MCP_",
        extra="ignore",
    )
    
    data_dir: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent / "data",
        description="Data storage directory",
    )


# ============= Singleton Pattern =============

# Global settings instance for application-wide access
_settings: Optional[ServerSettings] = None


def get_settings() -> ServerSettings:
    """
    Get or create the global settings singleton instance.

    Implements lazy initialization of the settings object.
    The first call creates the instance, subsequent calls
    return the same instance for consistency.

    Returns:
        ServerSettings: The global settings instance
    """
    global _settings
    if _settings is None:
        _settings = ServerSettings()
    return _settings
