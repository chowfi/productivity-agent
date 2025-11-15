"""
User Configuration Service

Manages per-user configuration including OpenRouter API keys.
Note: OpenRouter API keys are optional and only for local FastAgent client usage.
Not needed for ChatGPT integration - ChatGPT uses its own LLM.
"""

import json
from pathlib import Path
from typing import Optional, Dict
from fastmcp.utilities.logging import get_logger
from config.settings import get_settings

logger = get_logger("UserConfigService")


class UserConfigService:
    """
    Service for managing per-user configuration.
    
    Currently stores OpenRouter API keys (optional, only for local FastAgent client).
    Not needed for ChatGPT integration - ChatGPT uses its own LLM.
    """
    
    def __init__(self):
        """Initialize user config service."""
        self.logger = get_logger("UserConfigService")
        self.settings = get_settings()
        self.config_dir = self.settings.data_dir / "user_configs"
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def get_user_config_path(self, user_id: str) -> Path:
        """Get path to user's config file."""
        return self.config_dir / f"{user_id}.json"
    
    def set_openrouter_api_key(self, user_id: str, api_key: str) -> bool:
        """
        Store OpenRouter API key for a user.
        
        Args:
            user_id: User identifier
            api_key: OpenRouter API key
            
        Returns:
            True if successful
        """
        try:
            config_path = self.get_user_config_path(user_id)
            config = {}
            
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            config['openrouter_api_key'] = api_key
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            return True
        except Exception as e:
            self.logger.error(f"Error storing OpenRouter API key: {e}")
            return False
    
    def get_openrouter_api_key(self, user_id: str) -> Optional[str]:
        """
        Get stored OpenRouter API key for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            OpenRouter API key or None if not set
        """
        try:
            config_path = self.get_user_config_path(user_id)
            
            if not config_path.exists():
                return None
            
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            return config.get('openrouter_api_key')
        except Exception as e:
            self.logger.error(f"Error reading OpenRouter API key: {e}")
            return None
    
    def get_user_config(self, user_id: str) -> Dict:
        """
        Get full user configuration.
        
        Args:
            user_id: User identifier
            
        Returns:
            User configuration dictionary
        """
        try:
            config_path = self.get_user_config_path(user_id)
            
            if not config_path.exists():
                return {}
            
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error reading user config: {e}")
            return {}

