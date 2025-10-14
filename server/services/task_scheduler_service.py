"""
Task Scheduler Service

Main service for task scheduling logic.
Handles the complete lifecycle of daily task planning from collecting tasks 
through scheduling to document updates.
"""

from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from fastmcp.utilities.logging import get_logger

from services.google_calendar_service import GoogleCalendarService
from services.google_docs_service import GoogleDocsService


class TaskSchedulerService:
    """
    Service for managing task scheduling.
    
    Handles the complete lifecycle of daily task planning from
    collecting tasks through scheduling to document updates.
    """
    
    def __init__(
        self, 
        data_dir: Path,
        google_docs_service: GoogleDocsService,
        google_calendar_service: GoogleCalendarService
    ):
        """
        Initialize Task Scheduler Service.
        
        Args:
            data_dir: Directory for storing data
            google_docs_service: Google Docs service instance
            google_calendar_service: Google Calendar service instance
        """
        self.logger = get_logger("TaskSchedulerService")
        self.data_dir = Path(data_dir)
        self.google_docs_service = google_docs_service
        self.google_calendar_service = google_calendar_service
        
        # In-memory storage for add_task() calls
        self.tasks_memory = []
        
        # Store default Google Doc ID
        self.default_doc_id = None
        self.config_file = data_dir / "task_scheduler_config.json"
        self._load_config()
    
    # === TASK MANAGEMENT ===
    
    def add_task(
        self, 
        task_name: str, 
        hours: float, 
        urgency: str, 
        due_date: str = None
    ) -> str:
        """
        Add task to temporary memory for tomorrow's schedule.
        
        Args:
            task_name: Name of the task
            hours: Estimated duration in hours
            urgency: One of: critical, high, medium, low
            due_date: Optional due date (YYYY-MM-DD)
        
        Returns:
            Confirmation message
        """
        task = {
            "name": task_name,
            "hours": hours,
            "urgency": urgency,
            "due_date": due_date,
            "source": "add_task"
        }
        self.tasks_memory.append(task)
        self.logger.info(f"Added task: {task_name}")
        return f"Added: {task_name} ({hours}h, {urgency})"
    
    def _load_config(self):
        """Load configuration from file."""
        try:
            if self.config_file.exists():
                import json
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.default_doc_id = config.get('default_doc_id')
                    self.logger.info(f"Loaded config: default_doc_id = {self.default_doc_id}")
            else:
                self.logger.info("No config file found, starting with no default doc ID")
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            self.default_doc_id = None
    
    def _save_config(self):
        """Save configuration to file."""
        try:
            import json
            config = {
                'default_doc_id': self.default_doc_id,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            self.logger.info(f"Saved config: default_doc_id = {self.default_doc_id}")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
    
    def set_default_doc_id(self, doc_id: str) -> str:
        """
        Set the default Google Doc ID for schedule generation.
        
        Args:
            doc_id: Google Doc ID to use as default
        
        Returns:
            Confirmation message
        """
        self.default_doc_id = doc_id
        self._save_config()
        self.logger.info(f"Set default doc ID: {doc_id}")
        return f"Default Google Doc ID set to: {doc_id}"
    
    def get_default_doc_id(self) -> Optional[str]:
        """
        Get the current default Google Doc ID.
        
        Returns:
            Current default doc ID or None if not set
        """
        return self.default_doc_id
    
    def check_setup_status(self) -> str:
        """
        Check if the system is properly set up for task scheduling.
        
        Returns:
            Status message about setup
        """
        if self.default_doc_id is None:
            return """🔧 **Setup Required**

No Google Doc ID is configured yet. You need to set up your Google Doc before I can help you with task scheduling.

**To get started:**
1. Open your Google Doc (or create a new one)
2. Copy the ID from the URL: `https://docs.google.com/document/d/YOUR_DOC_ID_HERE/edit`
3. Tell me your Google Doc ID or URL

**Example:**
- "My doc ID is 1ABC123XYZ789"
- "Here's my doc: https://docs.google.com/document/d/1ABC123XYZ789/edit"

Once set up, I can help you add tasks and generate daily schedules!"""
        else:
            return f"""✅ **System Ready**

Your Google Doc is configured: `{self.default_doc_id}`

You can now:
- Add tasks with `add_task()`
- Generate daily schedules with `generate_and_create_tomorrow_schedule()`

Ready to help you manage your daily tasks!"""
    
    # === SCHEDULE GENERATION ===
    
    def generate_complete_schedule(
        self,
        doc_id: str = None,
        work_start_hour: int = 9,
        work_end_hour: int = 15
    ) -> str:
        """
        Generate complete schedule and append to Google Doc.
        
        This does ALL the work:
        1. Get dates
        2. Parse doc for incomplete tasks
        3. Get calendar events
        4. Combine all tasks (carryover + new + still-on-list)
        5. Prioritize with boost for persistent tasks
        6. Schedule around meetings
        7. Append to doc
        8. Cleanup
        
        Args:
            doc_id: Google Doc ID (optional, uses default if not provided)
            work_start_hour: Start of work day (default 9am)
            work_end_hour: End of work day (default 3pm)
        
        Returns:
            Summary message
        """
        try:
            # Use default doc_id if none provided
            if doc_id is None:
                if self.default_doc_id is None:
                    return """🔧 **First Time Setup Required**

No Google Doc ID is set yet. Please provide your Google Doc ID to get started.

**How to get your Google Doc ID:**
1. Open your Google Doc
2. Copy the ID from the URL: `https://docs.google.com/document/d/YOUR_DOC_ID_HERE/edit`
3. Use: `set_default_doc_id("YOUR_DOC_ID_HERE")`

**Example:**
```
set_default_doc_id("1ABC123XYZ789")
```

After setting your doc ID once, you can use `generate_and_create_tomorrow_schedule()` without providing the ID every time!"""
                doc_id = self.default_doc_id
                self.logger.info(f"Using default doc ID: {doc_id}")
            # A. Get dates
            today, tomorrow = self._get_dates()
            
            # B. Parse Google Doc
            doc_tasks = self.google_docs_service.parse_tasks_from_doc(doc_id)
            still_on_list_tasks = self.google_docs_service.parse_still_on_list(doc_id)
            
            # C. Get calendar events
            calendar_events = self.google_calendar_service.get_events_for_date(tomorrow)
            
            # D. Combine ALL tasks (KEY: 3 sources)
            all_tasks = self._combine_all_tasks(
                carryover=doc_tasks,
                new_tasks=self.tasks_memory,
                still_on_list=still_on_list_tasks
            )
            
            # E. Prioritize with boost
            prioritized_tasks = self._prioritize_tasks(all_tasks)
            
            # F. Schedule into time slots
            schedule = self._schedule_tasks(
                prioritized_tasks,
                calendar_events,
                work_start_hour,
                work_end_hour
            )
            
            # G. Format and append to doc
            schedule_text = self._format_schedule(tomorrow, schedule)
            self.google_docs_service.append_schedule(doc_id, schedule_text)
            
            # H. Cleanup
            self.tasks_memory = []
            
            return self._create_summary(schedule)
            
        except Exception as e:
            self.logger.error(f"Failed to generate schedule: {e}")
            return f"Error: {str(e)}"
    
    # === INTERNAL METHODS ===
    
    def _get_dates(self):
        """Get today and tomorrow dates."""
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        return today, tomorrow
    
    def _combine_all_tasks(self, carryover, new_tasks, still_on_list):
        """
        Combine tasks from 3 sources and deduplicate.
        
        Args:
            carryover: Incomplete urgent tasks from today
            new_tasks: Tasks from add_task() calls
            still_on_list: Tasks from previous "still on list"
        
        Returns:
            List of unique tasks
        """
        # Combine all
        all_tasks = carryover + new_tasks + still_on_list
        
        # Deduplicate by task name
        unique_tasks = []
        seen_names = set()
        
        for task in all_tasks:
            if task["name"] not in seen_names:
                unique_tasks.append(task)
                seen_names.add(task["name"])
        
        self.logger.info(f"Combined {len(all_tasks)} tasks into {len(unique_tasks)} unique tasks")
        return unique_tasks
    
    def _prioritize_tasks(self, tasks):
        """
        Calculate priority scores for all tasks.
        
        Priority = urgency_weight + due_date_weight + carryover_boost
        
        Weights:
        - Urgency: critical=10, high=7, medium=4, low=1
        - Due date: today=5, tomorrow=3, within_week=1, later=0
        - Carryover boost: +3 for persistent tasks
        """
        urgency_weights = {
            "critical": 10,
            "high": 7,
            "medium": 4,
            "low": 1
        }
        
        for task in tasks:
            # Base urgency score
            score = urgency_weights.get(task.get("urgency", "medium"), 4)
            
            # Due date score
            if task.get("due_date"):
                due_date = datetime.strptime(task["due_date"], "%Y-%m-%d").date()
                today = datetime.now().date()
                days_until_due = (due_date - today).days
                
                if days_until_due <= 0:
                    score += 5  # Due today or overdue
                elif days_until_due == 1:
                    score += 3  # Due tomorrow
                elif days_until_due <= 7:
                    score += 1  # Due within week
            
            # Carryover boost for persistent tasks
            if task.get("source") in ["carryover", "still_on_list"]:
                score += 3
            
            task["priority_score"] = score
        
        # Sort by priority (highest first)
        sorted_tasks = sorted(tasks, key=lambda t: t["priority_score"], reverse=True)
        self.logger.info(f"Prioritized {len(sorted_tasks)} tasks")
        return sorted_tasks
    
    def _schedule_tasks(self, tasks, calendar_events, start_hour, end_hour):
        """
        Fit tasks into time slots around meetings.
        
        Args:
            tasks: List of prioritized tasks
            calendar_events: List of calendar events
            start_hour: Start of work day
            end_hour: End of work day
        
        Returns:
            Dict with 'scheduled' and 'unscheduled' lists
        """
        # Get free time slots
        free_slots = self.google_calendar_service.get_free_time_slots(
            datetime.now().date() + timedelta(days=1),
            start_hour,
            end_hour
        )
        
        scheduled = []
        unscheduled = []
        
        # Convert free slots to minutes for easier calculation
        available_minutes = []
        for slot in free_slots:
            start_minutes = slot['start'] * 60
            end_minutes = slot['end'] * 60
            available_minutes.append({
                'start': start_minutes,
                'end': end_minutes,
                'duration': slot['duration'] * 60
            })
        
        # Try to fit tasks into available slots
        for task in tasks:
            task_minutes = int(task['hours'] * 60)
            fitted = False
            
            for slot in available_minutes:
                if slot['duration'] >= task_minutes:
                    # Fit the task
                    scheduled.append({
                        **task,
                        'start_time': slot['start'] // 60,
                        'end_time': (slot['start'] + task_minutes) // 60,
                        'slot_duration': slot['duration'] // 60
                    })
                    
                    # Update slot
                    slot['start'] += task_minutes
                    slot['duration'] -= task_minutes
                    fitted = True
                    break
            
            if not fitted:
                unscheduled.append(task)
        
        self.logger.info(f"Scheduled {len(scheduled)} tasks, {len(unscheduled)} unscheduled")
        return {
            "scheduled": scheduled,
            "unscheduled": unscheduled,
            "meetings": calendar_events
        }
    
    def _format_schedule(self, date, schedule):
        """
        Format schedule for Google Doc.
        
        Format:
        10/14/25 - Mon
        
        09:00 - 11:00: Review reports (2h, high urgency - due today)
        [Meeting: 11:00 - 12:00: Team standup]
        12:00 - 13:00: Walk dog (1h, medium urgency)
        
        Still on list (not scheduled today):
        - Update docs (2h, medium urgency - due 10/20/25)
        
        ---
        """
        # Format date header
        date_str = date.strftime('%m/%d/%y - %a')
        formatted_text = f"{date_str}\n\n"
        
        # Format scheduled tasks with times
        for task in schedule["scheduled"]:
            start_time = f"{task['start_time']:02d}:00"
            end_time = f"{task['end_time']:02d}:00"
            urgency_text = f"{task['urgency']} urgency"
            due_text = f" - due {task['due_date']}" if task.get('due_date') else ""
            
            formatted_text += f"{start_time} - {end_time}: {task['name']} ({task['hours']}h, {urgency_text}{due_text})\n"
        
        # Format meetings
        for meeting in schedule["meetings"]:
            # Extract time from meeting
            start_time = meeting.get('start', '')
            end_time = meeting.get('end', '')
            if start_time and end_time:
                # Convert to readable format
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    start_str = start_dt.strftime('%H:%M')
                    end_str = end_dt.strftime('%H:%M')
                    formatted_text += f"[Meeting: {start_str} - {end_str}: {meeting.get('summary', 'No Title')}]\n"
                except:
                    formatted_text += f"[Meeting: {meeting.get('summary', 'No Title')}]\n"
        
        # Format "still on list"
        if schedule["unscheduled"]:
            formatted_text += "\nStill on list (not scheduled today):\n"
            for task in schedule["unscheduled"]:
                urgency_text = f"{task['urgency']} urgency"
                due_text = f" - due {task['due_date']}" if task.get('due_date') else ""
                formatted_text += f"- {task['name']} ({task['hours']}h, {urgency_text}{due_text})\n"
        
        # Add separator
        formatted_text += "\n---\n"
        
        return formatted_text
    
    def _create_summary(self, schedule):
        """Create human-readable summary."""
        scheduled_count = len(schedule["scheduled"])
        unscheduled_count = len(schedule["unscheduled"])
        
        return f"Schedule created! {scheduled_count} tasks scheduled, {unscheduled_count} on waitlist."
