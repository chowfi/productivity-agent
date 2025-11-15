"""
OAuth Service

Handles Google OAuth flow for web-based authentication.
Supports per-user token storage and management.
"""

import json
import secrets
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlencode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from fastmcp.utilities.logging import get_logger
from config.settings import get_settings

import os 

# Prefer environment variables from Fly secrets
ENV_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
ENV_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
ENV_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

logger = get_logger("OAuthService")

# Google OAuth scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file'
]


class OAuthService:
    """
    Service for managing Google OAuth authentication.
    
    Handles OAuth flow, token storage, and credential management per user.
    """
    
    def __init__(self):
        """Initialize OAuth service."""
        self.logger = get_logger("OAuthService")
        self.settings = get_settings()
        self.tokens_dir = self.settings.data_dir / "tokens"
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        
        # Store active OAuth flows (state -> user_id mapping)
        self.active_flows: Dict[str, str] = {}
    
    def get_authorization_url(self, user_id: str) -> str:
        """
        Generate Google OAuth authorization URL.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            Authorization URL to redirect user to
        """
        settings = get_settings()
        
        # Determine redirect URI first
        if ENV_REDIRECT_URI:
            redirect_uri = ENV_REDIRECT_URI
        elif settings.oauth_redirect_uri:
            redirect_uri = settings.oauth_redirect_uri
        elif settings.server_url:
            redirect_uri = f"{settings.server_url}/oauth/callback"
        else:
            raise ValueError(
                "OAuth redirect URI not configured. Set one of: "
                "GOOGLE_REDIRECT_URI, MCP_OAUTH_REDIRECT_URI, or MCP_SERVER_URL environment variables"
            )
        
        # Load client configuration
        if ENV_CLIENT_ID and ENV_CLIENT_SECRET:
            client_config = {
                "web": {
                    "client_id": ENV_CLIENT_ID,
                    "client_secret": ENV_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            }

        else:
            # Fall back to credentials.json
            credentials_path = Path(settings.google_credentials_path)
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google credentials not found. Either set GOOGLE_CLIENT_ID and "
                    f"GOOGLE_CLIENT_SECRET environment variables, or place credentials.json "
                    f"at {credentials_path}"
                )
            with open(credentials_path, 'r') as f:
                client_config = json.load(f)
        
        # Create OAuth flow
        # Determine redirect URI - prioritize explicit setting, then environment variable, then construct from server_url
        if ENV_REDIRECT_URI:
            redirect_uri = ENV_REDIRECT_URI
        elif settings.oauth_redirect_uri:
            redirect_uri = settings.oauth_redirect_uri
        elif settings.server_url:
            redirect_uri = f"{settings.server_url}/oauth/callback"
        else:
            raise ValueError(
                "OAuth redirect URI not configured. Set one of: "
                "GOOGLE_REDIRECT_URI, MCP_OAUTH_REDIRECT_URI, or MCP_SERVER_URL environment variables"
            )
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        self.active_flows[state] = user_id
        
        # Get authorization URL
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'  # Force consent to get refresh token
        )
        
        return authorization_url
    
    def handle_callback(self, authorization_code: str, state: str) -> Optional[str]:
        """
        Handle OAuth callback and exchange code for tokens.
        
        Args:
            authorization_code: Authorization code from Google
            state: State parameter for CSRF protection
            
        Returns:
            User ID if successful, None otherwise
        """
        if state not in self.active_flows:
            self.logger.error(f"Invalid state parameter: {state}")
            return None
        
        user_id = self.active_flows.pop(state)
        
        settings = get_settings()
        
        # Determine redirect URI first
        if ENV_REDIRECT_URI:
            redirect_uri = ENV_REDIRECT_URI
        elif settings.oauth_redirect_uri:
            redirect_uri = settings.oauth_redirect_uri
        elif settings.server_url:
            redirect_uri = f"{settings.server_url}/oauth/callback"
        else:
            raise ValueError(
                "OAuth redirect URI not configured. Set one of: "
                "GOOGLE_REDIRECT_URI, MCP_OAUTH_REDIRECT_URI, or MCP_SERVER_URL environment variables"
            )
        
        # Load client configuration
        if ENV_CLIENT_ID and ENV_CLIENT_SECRET:
            client_config = {
                "web": {
                    "client_id": ENV_CLIENT_ID,
                    "client_secret": ENV_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            }

        else:
            credentials_path = Path(settings.google_credentials_path)
            with open(credentials_path, 'r') as f:
                client_config = json.load(f)
        
        # Create OAuth flow
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        # Exchange code for tokens
        try:
            flow.fetch_token(code=authorization_code)
            creds = flow.credentials
            
            # Save tokens for this user
            self.save_user_credentials(user_id, creds)
            
            return user_id
        except Exception as e:
            self.logger.error(f"Error exchanging authorization code: {e}")
            return None
    
    def get_user_credentials(self, user_id: str) -> Optional[Credentials]:
        """
        Get stored credentials for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Credentials object if found and valid, None otherwise
        """
        token_path = self.tokens_dir / f"{user_id}.json"
        
        if not token_path.exists():
            return None
        
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            
            # Refresh if expired
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.save_user_credentials(user_id, creds)
            
            return creds
        except Exception as e:
            self.logger.error(f"Error loading credentials for user {user_id}: {e}")
            return None
    
    def save_user_credentials(self, user_id: str, creds: Credentials):
        """
        Save credentials for a user.
        
        Args:
            user_id: User identifier
            creds: Credentials object
        """
        token_path = self.tokens_dir / f"{user_id}.json"
        
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    def is_user_authenticated(self, user_id: str) -> bool:
        """
        Check if a user is authenticated.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if user has valid credentials
        """
        creds = self.get_user_credentials(user_id)
        return creds is not None and creds.valid
    
    def revoke_user_credentials(self, user_id: str):
        """
        Revoke and delete credentials for a user.
        
        Args:
            user_id: User identifier
        """
        token_path = self.tokens_dir / f"{user_id}.json"
        
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
                if creds:
                    # Revoke the token
                    creds.revoke(Request())
            except Exception as e:
                self.logger.warning(f"Error revoking credentials: {e}")
            
            # Delete the token file
            token_path.unlink()

