"""
Task Scheduler Service

Service for task memory management and configuration.
Handles task storage, retrieval, and system setup for the task scheduler.
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
    
    
    # === TASK MEMORY MANAGEMENT ===
    
    def get_tasks_from_memory(self) -> List[Dict]:
        """
        Get all tasks currently in memory.
        
        Returns:
            List of tasks added via add_task()
        """
        return self.tasks_memory.copy()
    
    def clear_tasks_memory(self) -> str:
        """
        Clear all tasks from memory.
        
        Returns:
            Confirmation message
        """
        count = len(self.tasks_memory)
        self.tasks_memory = []
        self.logger.info(f"Cleared {count} tasks from memory")
        return f"Cleared {count} tasks from memory"
