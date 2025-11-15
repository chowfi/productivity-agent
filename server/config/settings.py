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
    
    # Google OAuth settings
    google_client_id: Optional[str] = Field(
        default=None,
        description="Google OAuth Client ID"
    )
    
    google_client_secret: Optional[str] = Field(
        default=None,
        description="Google OAuth Client Secret"
    )
    
    google_credentials_path: str = Field(
        default="credentials.json",
        description="Path to Google credentials JSON file"
    )
    
    oauth_redirect_uri: Optional[str] = Field(
        default=None,
        description="OAuth redirect URI (e.g., https://your-app.fly.dev/oauth/callback)"
    )
    
    # Server settings
    server_url: Optional[str] = Field(
        default=None,
        description="Public server URL for OAuth callbacks"
    )
    
    # Session/security
    session_secret: Optional[str] = Field(
        default=None,
        description="Secret key for session management"
    )
    
    # Note: OpenRouter API keys are only needed for local FastAgent client usage
    # When using ChatGPT, ChatGPT uses its own LLM - no OpenRouter keys needed


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
