"""
Google Calendar Service

Handles Google Calendar API integration for fetching events and managing calendar data.
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


class GoogleCalendarService:
    """
    Service for Google Calendar API integration.
    
    Handles authentication and fetching calendar events.
    Supports per-user authentication.
    """
    
    def __init__(self, oauth_service: Optional[OAuthService] = None):
        """
        Initialize Google Calendar service.
        
        Args:
            oauth_service: OAuth service instance for user authentication
        """
        self.logger = get_logger("GoogleCalendarService")
        self.oauth_service = oauth_service or OAuthService()
    
    def get_service_for_user(self, user_id: str):
        """
        Get Google Calendar service for a specific user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Google Calendar API service instance
            
        Raises:
            RuntimeError: If user is not authenticated
        """
        creds = self.oauth_service.get_user_credentials(user_id)
        if not creds or not creds.valid:
            raise RuntimeError(
                f"User {user_id} is not authenticated. Please complete OAuth flow first."
            )
        
        return build('calendar', 'v3', credentials=creds)
    
    def get_events_for_date(self, target_date: date, user_id: str) -> List[Dict]:
        """
        Get all events for a specific date.
        
        Args:
            target_date: Date to fetch events for
            user_id: User identifier for authentication
            
        Returns:
            List of events with start/end times and details
        """
        service = self.get_service_for_user(user_id)
        
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
            
            # Call the Calendar API
            events_result = service.events().list(
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
            
            return formatted_events
            
        except HttpError as error:
            self.logger.error(f"Calendar API error: {error}")
            return []
        except Exception as e:
            self.logger.error(f"Error fetching events: {e}")
            return []
    
    def get_free_time_slots(self, target_date: date, user_id: str, work_start_hour: int = 8, work_end_hour: int = 20) -> List[Dict]:
        """
        Get free time slots for a specific date.
        
        Args:
            target_date: Date to analyze
            user_id: User identifier for authentication
            work_start_hour: Start of work day (24-hour format)
            work_end_hour: End of work day (24-hour format)
            
        Returns:
            List of free time slots
        """
        events = self.get_events_for_date(target_date, user_id)
        
        # Convert events to time blocks
        event_blocks = []
        for event in events:
            start_time = datetime.fromisoformat(event['start'].replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(event['end'].replace('Z', '+00:00'))
            
            # Convert to local time and handle minutes properly
            start_hour = start_time.hour + start_time.minute / 60.0
            end_hour = end_time.hour + end_time.minute / 60.0
            
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
        
        return free_slots
