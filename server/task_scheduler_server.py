"""
Task Scheduler MCP Server

MCP server that uses service-based architecture.
Provides 5 simple tools: add_task(), set_default_doc_id(), get_default_doc_id(), check_setup_status(), and generate_and_create_tomorrow_schedule().
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

from fastmcp import FastMCP, Context
from fastmcp.utilities.logging import get_logger

# Add the server directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from services.task_scheduler_service import TaskSchedulerService
from services.google_calendar_service import GoogleCalendarService
from services.google_docs_service import GoogleDocsService
from config.settings import get_settings

logger = get_logger(__name__)

# === APPLICATION CONTEXT ===

@dataclass
class AppContext:
    """Application context with all services."""
    task_scheduler_service: TaskSchedulerService
    google_calendar_service: GoogleCalendarService
    google_docs_service: GoogleDocsService
    settings: object

@asynccontextmanager
async def app_lifespan(mcp: FastMCP):
    """Initialize all services for the task scheduler."""
    logger.info("Starting Task Scheduler MCP Server")
    
    # Get settings
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize Google services (fail fast for OAuth)
    google_calendar_service = GoogleCalendarService()
    google_calendar_service.initialize()
    logger.info("Google Calendar service initialized successfully")
    
    google_docs_service = GoogleDocsService()
    google_docs_service.initialize()
    logger.info("Google Docs service initialized successfully")
    
    # Initialize main service
    task_scheduler_service = TaskSchedulerService(
        data_dir=settings.data_dir,
        google_docs_service=google_docs_service,
        google_calendar_service=google_calendar_service
    )
    
    logger.info("All services initialized!")
    logger.info(f"Data directory: {settings.data_dir}")
    
    try:
        yield AppContext(
            task_scheduler_service=task_scheduler_service,
            google_calendar_service=google_calendar_service,
            google_docs_service=google_docs_service,
            settings=settings
        )
    finally:
        logger.info("Shutting down Task Scheduler MCP Server")

# === MCP SERVER ===

mcp = FastMCP(
    name="task-scheduler-server",
    instructions=f"""You are a task scheduling assistant.

Current date: {datetime.now().strftime('%A, %B %d, %Y')}

You have these tools:
1. add_task() - Add tasks to temporary memory
2. set_default_doc_id() - Set default Google Doc ID (do this once)
3. get_default_doc_id() - Check current default Google Doc ID
4. check_setup_status() - Check if system is ready for task scheduling
5. generate_and_create_tomorrow_schedule() - Generate complete schedule

**CRITICAL: Always check for default doc ID first!**

**When user wants to add tasks or generate schedules:**
1. FIRST call check_setup_status() to see if system is ready
2. If setup is required, guide them through it BEFORE proceeding
3. If system is ready, proceed with their request

**Setup Process for New Users:**
- Ask for their Google Doc URL or ID
- Help them extract the ID from the URL if needed
- Use set_default_doc_id() with their doc ID
- THEN they can add tasks and generate schedules

**Natural Language Examples:**
- User: "I want to set up my Google Doc: https://docs.google.com/document/d/1ABC123XYZ789/edit"
- You: Call set_default_doc_id("https://docs.google.com/document/d/1ABC123XYZ789/edit")
- User: "My doc ID is 1ABC123XYZ789"  
- You: Call set_default_doc_id("1ABC123XYZ789")

**User Experience Flow:**
1. User says "I want to add a task" or "generate schedule"
2. You call check_setup_status() first
3. If setup required: Show the setup message and guide them through it
4. If system ready: Proceed with their request

**Be proactive about setup - never assume they have a default doc ID!**
""",
    lifespan=app_lifespan
)

# === TOOLS ===

@mcp.tool()
async def add_task(
    task_name: str,
    hours: float,
    urgency: str,
    due_date: str = None,
    ctx: Context = None
) -> str:
    """
    Add task to temporary list for tomorrow's schedule.
    
    Args:
        task_name: Name of the task
        hours: Estimated duration in hours
        urgency: One of: critical, high, medium, low
        due_date: Optional due date (YYYY-MM-DD)
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    return service.add_task(task_name, hours, urgency, due_date)

@mcp.tool()
async def set_default_doc_id(
    doc_id: str,
    ctx: Context = None
) -> str:
    """
    Set the default Google Doc ID for schedule generation.
    
    This allows you to set a Google Doc ID once and use it for all
    future schedule generations without having to provide it each time.
    
    You can provide the doc ID in any of these formats:
    - Full URL: "https://docs.google.com/document/d/1ABC123XYZ789/edit"
    - Just the ID: "1ABC123XYZ789"
    - URL with other params: "https://docs.google.com/document/d/1ABC123XYZ789/edit?usp=sharing"
    
    Args:
        doc_id: Google Doc ID or full URL to use as default
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    
    # Extract doc ID from URL if full URL provided
    if "docs.google.com/document/d/" in doc_id:
        # Extract ID from URL like: https://docs.google.com/document/d/1ABC123XYZ789/edit
        import re
        match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', doc_id)
        if match:
            doc_id = match.group(1)
        else:
            return "Error: Could not extract Google Doc ID from URL. Please provide just the ID."
    
    return service.set_default_doc_id(doc_id)

@mcp.tool()
async def get_default_doc_id(
    ctx: Context = None
) -> str:
    """
    Get the current default Google Doc ID.
    
    Returns:
        Current default doc ID or message if none set
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    doc_id = service.get_default_doc_id()
    if doc_id:
        return f"Current default Google Doc ID: {doc_id}"
    else:
        return "No default Google Doc ID set. Use set_default_doc_id() to set one."

@mcp.tool()
async def check_setup_status(
    ctx: Context = None
) -> str:
    """
    Check if the system is properly set up for task scheduling.
    
    Returns:
        Status message about setup and next steps
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    return service.check_setup_status()

@mcp.tool()
async def generate_and_create_tomorrow_schedule(
    doc_id: str = None,
    work_start_hour: int = 9,
    work_end_hour: int = 15,
    ctx: Context = None
) -> str:
    """
    Generate complete schedule and append to Google Doc.
    
    This does everything in one call:
    - Parse incomplete tasks from doc
    - Get calendar events
    - Combine all tasks (carryover + new + still-on-list)
    - Prioritize and schedule
    - Append to doc
    
    Args:
        doc_id: Google Doc ID (optional, uses default if not provided)
        work_start_hour: Start of work day (default 9am)
        work_end_hour: End of work day (default 3pm)
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    return service.generate_complete_schedule(doc_id, work_start_hour, work_end_hour)

# === SERVER ENTRY POINT ===

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8084)
