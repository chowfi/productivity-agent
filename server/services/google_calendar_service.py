"""
Google Calendar Service

Handles Google Calendar API integration for fetching events and managing calendar data.
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
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class GoogleCalendarService:
    """
    Service for Google Calendar API integration.
    
    Handles authentication and fetching calendar events.
    """
    
    def __init__(self, credentials_path: str = None):
        """
        Initialize Google Calendar service.
        
        Args:
            credentials_path: Path to credentials file (optional)
        """
        self.logger = get_logger("GoogleCalendarService")
        self.credentials_path = credentials_path or "credentials.json"
        self.service = None
        self.creds = None
    
    def initialize(self):
        """Initialize Google Calendar API service."""
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
        
        self.service = build('calendar', 'v3', credentials=self.creds)
        self.logger.info("Google Calendar service initialized successfully")
    
    def get_events_for_date(self, target_date: date) -> List[Dict]:
        """
        Get all events for a specific date.
        
        Args:
            target_date: Date to fetch events for
            
        Returns:
            List of events with start/end times and details
        """
        if not self.service:
            raise RuntimeError("Service not initialized. Call initialize() first.")
        
        try:
            # Convert date to datetime range in local timezone
            # Use timezone-aware datetimes to avoid UTC conversion issues
            from datetime import timezone
            import pytz
            
            # Get local timezone (Eastern Time)
            local_tz = pytz.timezone('America/New_York')
            
            start_datetime = local_tz.localize(datetime.combine(target_date, datetime.min.time()))
            end_datetime = local_tz.localize(datetime.combine(target_date, datetime.max.time()))
            
            # Format for API (will include timezone offset)
            start_time = start_datetime.isoformat()
            end_time = end_datetime.isoformat()
            
            self.logger.info(f"Fetching events for {target_date}")
            
            # Call the Calendar API
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Format events for our use
            formatted_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                formatted_events.append({
                    'summary': event.get('summary', 'No Title'),
                    'start': start,
                    'end': end,
                    'description': event.get('description', ''),
                    'location': event.get('location', ''),
                    'attendees': event.get('attendees', [])
                })
            
            self.logger.info(f"Found {len(formatted_events)} events for {target_date}")
            return formatted_events
            
        except HttpError as error:
            self.logger.error(f"Calendar API error: {error}")
            return []
        except Exception as e:
            self.logger.error(f"Error fetching events: {e}")
            return []
    
    def get_free_time_slots(self, target_date: date, work_start_hour: int = 8, work_end_hour: int = 20) -> List[Dict]:
        """
        Get free time slots for a specific date.
        
        Args:
            target_date: Date to analyze
            work_start_hour: Start of work day (24-hour format)
            work_end_hour: End of work day (24-hour format)
            
        Returns:
            List of free time slots
        """
        events = self.get_events_for_date(target_date)
        self.logger.info(f"Processing {len(events)} events for free time calculation")
        self.logger.info(f"Work hours: {work_start_hour}:00 to {work_end_hour}:00")
        
        # Convert events to time blocks
        event_blocks = []
        for event in events:
            start_time = datetime.fromisoformat(event['start'].replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(event['end'].replace('Z', '+00:00'))
            
            # Convert to local time and handle minutes properly
            start_hour = start_time.hour + start_time.minute / 60.0
            end_hour = end_time.hour + end_time.minute / 60.0
            
            self.logger.info(f"Event: {event['summary']} from {start_hour:.2f} to {end_hour:.2f}")
            
            event_blocks.append({
                'start': start_hour,
                'end': end_hour,
                'summary': event['summary']
            })
        
        # Sort by start time
        event_blocks.sort(key=lambda x: x['start'])
        
        # Find free slots
        free_slots = []
        current_time = float(work_start_hour)
        
        for event in event_blocks:
            if current_time < event['start']:
                # Free slot before this event (but don't go past work_end_hour)
                slot_end = min(event['start'], work_end_hour)
                if current_time < slot_end:
                    free_slots.append({
                        'start': current_time,
                        'end': slot_end,
                        'duration': slot_end - current_time
                    })
            current_time = max(current_time, event['end'])
        
        # Check for free time after last event
        if current_time < work_end_hour:
            free_slots.append({
                'start': current_time,
                'end': work_end_hour,
                'duration': work_end_hour - current_time
            })
        
        self.logger.info(f"Calculated free slots: {free_slots}")
        return free_slots
