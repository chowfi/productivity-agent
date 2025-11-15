"""
Google Docs Service

Handles Google Docs API integration for reading and writing documents.
Provides simple fetch/write operations for document content.
Supports per-user authentication via OAuth service.
"""

import os
from datetime import datetime, date
from typing import List, Dict, Optional
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from fastmcp.utilities.logging import get_logger
from services.oauth_service import OAuthService


class GoogleDocsService:
    """
    Service for Google Docs API integration.
    
    Handles reading, parsing, and updating Google Documents.
    Supports per-user authentication.
    """
    
    def __init__(self, oauth_service: Optional[OAuthService] = None):
        """
        Initialize Google Docs service.
        
        Args:
            oauth_service: OAuth service instance for user authentication
        """
        self.logger = get_logger("GoogleDocsService")
        self.oauth_service = oauth_service or OAuthService()
    
    def get_service_for_user(self, user_id: str):
        """
        Get Google Docs service for a specific user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Google Docs API service instance
            
        Raises:
            RuntimeError: If user is not authenticated
        """
        creds = self.oauth_service.get_user_credentials(user_id)
        if not creds or not creds.valid:
            raise RuntimeError(
                f"User {user_id} is not authenticated. Please complete OAuth flow first."
            )
        
        return build('docs', 'v1', credentials=creds)
    
    def read_document(self, doc_id: str, user_id: str) -> str:
        """
        Read full document content.
        
        Args:
            doc_id: Google Doc ID
            user_id: User identifier for authentication
            
        Returns:
            Document text content
        """
        service = self.get_service_for_user(user_id)
        
        try:
            # Retrieve the documents contents from the Docs service.
            document = service.documents().get(documentId=doc_id).execute()
            
            # Extract text content
            content = document.get('body', {}).get('content', [])
            text_content = []
            
            for element in content:
                if 'paragraph' in element:
                    paragraph = element['paragraph']
                    for text_run in paragraph.get('elements', []):
                        if 'textRun' in text_run:
                            text_content.append(text_run['textRun']['content'])
            
            full_text = ''.join(text_content)
            return full_text
            
        except HttpError as error:
            self.logger.error(f"Docs API error: {error}")
            return ""
        except Exception as e:
            self.logger.error(f"Error reading document: {e}")
            return ""
    
    
    
    
    def write_to_doc(self, doc_id: str, content: str, user_id: str):
        """
        Write content to the top of the document.
        
        Args:
            doc_id: Google Doc ID
            content: Content to write to document
            user_id: User identifier for authentication
        """
        service = self.get_service_for_user(user_id)
        
        try:
            # Insert at the beginning of the document
            requests = [
                {
                    'insertText': {
                        'location': {
                            'index': 1,  # Insert at the beginning
                        },
                        'text': content + '\n\n'
                    }
                }
            ]
            
            # Execute the request
            result = service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
            
            return result
            
        except HttpError as error:
            self.logger.error(f"Docs API error: {error}")
            raise
        except Exception as e:
            self.logger.error(f"Error writing to document: {e}")
            raise
