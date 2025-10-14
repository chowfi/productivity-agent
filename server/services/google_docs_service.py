"""
Google Docs Service

Handles Google Docs API integration for reading, parsing, and updating documents.
"""

import os
import re
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
    
    def parse_tasks_from_doc(self, doc_id: str) -> List[Dict]:
        """
        Parse tasks from document format.
        
        Looks for today's date section and extracts incomplete tasks.
        Format: "- Task (2h, urgent - due date)"
        
        Args:
            doc_id: Google Doc ID
            
        Returns:
            List of task dictionaries
        """
        try:
            content = self.read_document(doc_id)
            if not content:
                return []
            
            lines = content.split('\n')
            tasks = []
            current_date = None
            today = datetime.now().date()
            
            # Look for today's date section
            today_pattern = today.strftime('%m/%d/%y')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Check if this is a date header
                if re.match(r'\d{1,2}/\d{1,2}/\d{2,4}\s*-\s*\w+', line):
                    current_date = line
                    continue
                
                # Check if this is today's section
                if today_pattern in line:
                    current_date = line
                    continue
                
                # Parse task lines (only from today's section)
                if current_date and today_pattern in current_date and line.startswith('-'):
                    task_text = line[1:].strip()
                    
                    # Skip completed tasks (with checkmarks)
                    if '✔' in task_text or '✓' in task_text:
                        continue
                    
                    # Parse task details
                    task_info = self._parse_task_details(task_text)
                    if task_info:
                        task_info['source'] = 'carryover'
                        tasks.append(task_info)
            
            self.logger.info(f"Parsed {len(tasks)} incomplete tasks from today's section")
            return tasks
            
        except Exception as e:
            self.logger.error(f"Error parsing tasks from doc: {e}")
            return []
    
    def parse_still_on_list(self, doc_id: str) -> List[Dict]:
        """
        Parse 'Still on list' section from previous days.
        
        Args:
            doc_id: Google Doc ID
            
        Returns:
            List of tasks from "still on list" sections
        """
        try:
            content = self.read_document(doc_id)
            if not content:
                return []
            
            lines = content.split('\n')
            tasks = []
            in_still_on_list = False
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Check if we're in a "Still on list" section
                if 'Still on list' in line or 'still on list' in line:
                    in_still_on_list = True
                    continue
                
                # Check if we've moved to a new date section
                if re.match(r'\d{1,2}/\d{1,2}/\d{2,4}\s*-\s*\w+', line):
                    in_still_on_list = False
                    continue
                
                # Parse tasks from "still on list" section
                if in_still_on_list and line.startswith('-'):
                    task_text = line[1:].strip()
                    
                    # Skip completed tasks
                    if '✔' in task_text or '✓' in task_text:
                        continue
                    
                    # Parse task details
                    task_info = self._parse_task_details(task_text)
                    if task_info:
                        task_info['source'] = 'still_on_list'
                        tasks.append(task_info)
            
            self.logger.info(f"Parsed {len(tasks)} tasks from 'still on list' sections")
            return tasks
            
        except Exception as e:
            self.logger.error(f"Error parsing still on list: {e}")
            return []
    
    def _parse_task_details(self, task_text: str) -> Optional[Dict]:
        """
        Parse task details from text.
        
        Format: "Task name (2h, urgent - due date)"
        
        Args:
            task_text: Raw task text
            
        Returns:
            Task dictionary or None if parsing fails
        """
        try:
            # Extract details from parentheses
            details_match = re.search(r'\(([^)]+)\)', task_text)
            if not details_match:
                return None
            
            details = details_match.group(1)
            
            # Extract duration
            duration_match = re.search(r'(\d+(?:\.\d+)?)h', details)
            hours = float(duration_match.group(1)) if duration_match else 1.0
            
            # Extract urgency
            urgency = 'medium'  # default
            if 'urgent' in details.lower():
                urgency = 'urgent'
            elif 'high' in details.lower():
                urgency = 'high'
            elif 'critical' in details.lower():
                urgency = 'critical'
            elif 'low' in details.lower():
                urgency = 'low'
            
            # Extract due date
            due_date = None
            due_match = re.search(r'due\s+(\d{4}-\d{2}-\d{2})', details)
            if due_match:
                due_date = due_match.group(1)
            
            # Extract task name (everything before parentheses)
            task_name = task_text.split('(')[0].strip()
            
            return {
                'name': task_name,
                'hours': hours,
                'urgency': urgency,
                'due_date': due_date
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing task details: {e}")
            return None
    
    def append_schedule(self, doc_id: str, schedule_text: str):
        """
        Append schedule to document.
        
        Args:
            doc_id: Google Doc ID
            schedule_text: Formatted schedule text to append
        """
        if not self.service:
            raise RuntimeError("Service not initialized. Call initialize() first.")
        
        try:
            self.logger.info(f"Appending schedule to document: {doc_id}")
            
            # Get current document to find end position
            document = self.service.documents().get(documentId=doc_id).execute()
            end_index = document.get('body', {}).get('content', [])[-1].get('endIndex', 1) - 1
            
            # Prepare the text to insert
            requests = [
                {
                    'insertText': {
                        'location': {
                            'index': end_index,
                        },
                        'text': '\n\n' + schedule_text + '\n'
                    }
                }
            ]
            
            # Execute the request
            result = self.service.documents().batchUpdate(
                documentId=doc_id, body={'requests': requests}
            ).execute()
            
            self.logger.info("Successfully appended schedule to document")
            return result
            
        except HttpError as error:
            self.logger.error(f"Docs API error: {error}")
            raise
        except Exception as e:
            self.logger.error(f"Error appending schedule: {e}")
            raise
