"""
Google Docs Service

Handles Google Docs API integration for reading and writing documents.
Provides simple fetch/write operations for document content.
"""

import os
from datetime import datetime, date
from typing import List, Dict, Optional
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from fastmcp.utilities.logging import get_logger

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']


class GoogleDocsService:
    """
    Service for Google Docs API integration.
    
    Handles reading, parsing, and updating Google Documents.
    """
    
    def __init__(self, credentials_path: str = None):
        """
        Initialize Google Docs service.
        
        Args:
            credentials_path: Path to credentials file (optional)
        """
        self.logger = get_logger("GoogleDocsService")
        self.credentials_path = credentials_path or "credentials.json"
        self.service = None
        self.creds = None
    
    def initialize(self):
        """Initialize Google Docs API service."""
        # The file token.json stores the user's access and refresh tokens.
        token_path = Path("token.json")
        
        if token_path.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(self.creds.to_json())
        
        self.service = build('docs', 'v1', credentials=self.creds)
        self.logger.info("Google Docs service initialized successfully")
    
    def read_document(self, doc_id: str) -> str:
        """
        Read full document content.
        
        Args:
            doc_id: Google Doc ID
            
        Returns:
            Document text content
        """
        if not self.service:
            raise RuntimeError("Service not initialized. Call initialize() first.")
        
        try:
            self.logger.info(f"Reading document: {doc_id}")
            
            # Retrieve the documents contents from the Docs service.
            document = self.service.documents().get(documentId=doc_id).execute()
            
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
            self.logger.info(f"Successfully read document ({len(full_text)} characters)")
            return full_text
            
        except HttpError as error:
            self.logger.error(f"Docs API error: {error}")
            return ""
        except Exception as e:
            self.logger.error(f"Error reading document: {e}")
            return ""
    
    
    
    
    def write_to_doc(self, doc_id: str, content: str):
        """
        Write content to the top of the document.
        
        Args:
            doc_id: Google Doc ID
            content: Content to write to document
        """
        if not self.service:
            raise RuntimeError("Service not initialized. Call initialize() first.")
        
        try:
            self.logger.info(f"Writing content to document: {doc_id}")
            
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
            result = self.service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
            
            self.logger.info("Successfully wrote content to document")
            return result
            
        except HttpError as error:
            self.logger.error(f"Docs API error: {error}")
            raise
        except Exception as e:
            self.logger.error(f"Error writing to document: {e}")
            raise
