"""
Task Scheduler MCP Server

MCP server that provides data access tools for task scheduling.
Exposes 8 tools for calendar events, document operations, and task memory management.
Also provides document content as resources and workflow prompts.
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
    instructions="""You are the Task Scheduling Data Service.

Your role: Provide access to Google Calendar events, Google Doc content, and task memory storage.

You expose:
- Calendar event fetching
- Free time slot calculation  
- Document reading/writing
- Task memory management
- Document content as resources

You do NOT orchestrate workflows or make scheduling decisions - you only fetch and write data.""",
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
async def get_calendar_events(
    date: str,
    ctx: Context = None
) -> str:
    """
    Get calendar events for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format
    """
    from datetime import datetime
    service = ctx.request_context.lifespan_context.google_calendar_service
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    events = service.get_events_for_date(target_date)
    return f"Found {len(events)} events for {date}: {events}"

@mcp.tool()
async def get_free_time_slots(
    date: str,
    start_hour: int = 9,
    end_hour: int = 20,
    ctx: Context = None
) -> str:
    """
    Get free time slots for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format
        start_hour: Start of work day (24-hour format)
        end_hour: End of work day (24-hour format)
    """
    from datetime import datetime
    service = ctx.request_context.lifespan_context.google_calendar_service
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    slots = service.get_free_time_slots(target_date, start_hour, end_hour)
    return f"Free time slots for {date}: {slots}"

@mcp.tool()
async def read_doc_content(
    doc_id: str,
    ctx: Context = None
) -> str:
    """
    Read content from a Google Doc.
    
    Args:
        doc_id: Google Doc ID
    """
    service = ctx.request_context.lifespan_context.google_docs_service
    content = service.read_document(doc_id)
    return content

@mcp.tool()
async def write_schedule_to_doc(
    doc_id: str,
    content: str,
    ctx: Context = None
) -> str:
    """
    Write content to a Google Doc.
    
    Args:
        doc_id: Google Doc ID
        content: Content to write to document
    """
    service = ctx.request_context.lifespan_context.google_docs_service
    service.write_to_doc(doc_id, content)
    return f"Successfully wrote content to document {doc_id}"

@mcp.tool()
async def get_tasks_from_memory(
    ctx: Context = None
) -> str:
    """
    Get all tasks currently in memory.
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    tasks = service.get_tasks_from_memory()
    return f"Tasks in memory: {tasks}"

@mcp.tool()
async def clear_tasks_memory(
    ctx: Context = None
) -> str:
    """
    Clear all tasks from memory.
    """
    service = ctx.request_context.lifespan_context.task_scheduler_service
    return service.clear_tasks_memory()

# === RESOURCES ===

@mcp.resource(uri="docs://{doc_id}")
async def get_doc_resource(doc_id: str, ctx: Context) -> str:
    """Expose Google Doc content as a resource."""
    service = ctx.request_context.lifespan_context.google_docs_service
    return service.read_document(doc_id)

# === PROMPTS ===

@mcp.prompt()
async def generate_tomorrow_schedule(
    work_start_hour: int = 8,
    work_end_hour: int = 20
) -> str:
    """DETAILED step-by-step workflow for generating tomorrow's schedule.
    
    CRITICAL: You MUST follow ALL these steps in order. Do NOT skip any steps.
    
    This is the most comprehensive, reusable workflow template for creating daily schedules.
    
    DETAILED WORKFLOW:
    
    1. CHECK SETUP
    - Call check_setup_status()
    - If no default doc ID, guide user to provide it

    2. READ DOCUMENT CONTENT
    - Call read_doc_content(doc_id)
    - Parse today's date section (format: MM/DD/YY - Day)
    - Extract incomplete tasks (lines starting with "-" but NO ✓ or ✔)
    - Extract "Still on list" section tasks (also NO ✓ or ✔)
    - CRITICAL: Include ALL incomplete tasks from today with EXACT names

    3. ASK USER FOR NEW TASKS
    - Ask: "What new tasks would you like to add for tomorrow?"
    - Call add_task() for each new task
    - Call get_tasks_from_memory() to retrieve them
    - CRITICAL: Do NOT create generic tasks like "Morning Work Session"

    4. GET CALENDAR DATA
    - Calculate tomorrow's date (today + 1 day)
    - Call get_calendar_events(tomorrow_date)
    - Call get_free_time_slots(tomorrow_date, 8, 20)
    - CRITICAL: Only include main calendar events (visible in Google Calendar UI)

    5. COMBINE ALL TASKS
    - Merge: incomplete from doc + new from memory + still on list from doc
    - Deduplicate by task name
    - Keep all unique tasks

    6. PRIORITIZE TASKS
    - Calculate priority scores:
        * Urgency: critical=10, high=7, medium=4, low=1
        * Due date: overdue/today=+5, tomorrow=+3, this_week=+1, later=0
        * Carryover boost: +3 for tasks from document
    - Sort by priority (highest first)

    7. SCHEDULE INTO TIME BLOCKS
    - CRITICAL: 6-8h is a GUIDELINE, NOT a limit! Use ALL available free time if there are tasks left
    - Process EVERY free time slot and fill it if tasks remain:
        * Morning slots (8am-12pm)
        * Afternoon slots (12pm-4pm)
        * Evening slots (6pm-8pm after dinner)
    - CRITICAL: DO NOT STOP at 7h or 8h if there are MORE free slots and unscheduled tasks
    - CRITICAL: If a task doesn't fit completely, schedule partial time and track remainder
    - Example: If you've scheduled 7h and there's a 6:20pm-8pm slot with 0.5h task remaining → SCHEDULE IT!
    - CRITICAL: After scheduling, if a task has 0h remaining, it's COMPLETE - do NOT add to "Still on list"
    - CRITICAL: Check for time overlaps - no overlapping tasks/meetings
    - Meetings don't count toward work hours
    - Only stop scheduling when: (a) NO more free time OR (b) NO more tasks to schedule

    8. CALCULATE REMAINING TIME FOR EACH TASK
    - For EACH task in your list, calculate:
        * Total time originally allocated (e.g., 4h)
        * Time scheduled in today's plan (sum all occurrences, e.g., 2h + 1.17h = 3.17h)
        * Remaining time = Total - Scheduled (e.g., 4h - 3.17h = 0.83h)
    - If Remaining time = 0h → Task is COMPLETE, exclude from "Still on list"
    - If Remaining time > 0h → Include in "Still on list" with correct remaining time

    9. FORMAT SCHEDULE (EXACT FORMAT)
    - Header: MM/DD/YY - Day
    - CRITICAL: List ALL events chronologically - BOTH tasks AND meetings mixed by time
    - Task format: HH:MM - HH:MM: Task name (Xh, urgency - due date)
    - Meeting format: [Meeting: HH:MM - HH:MM: Meeting name]
    - CRITICAL: Include EVERY calendar event as [Meeting: ...] in chronological order
    - Blank line before "Still on list" section
    - Catch-all: "Still on list (not scheduled today):"
        * Use the remaining time calculations from step 8
        * ONLY include tasks where remaining_time > 0
        * Format: "- Task name (Xh remaining, urgency - due date)"
        * If NO tasks have remaining_time > 0, write: "- None (all tasks complete!)"
    - Footer: "---"
    - CRITICAL: NO "NOTES" sections, NO custom formatting

    10. WRITE AND CLEANUP
    - Call write_schedule_to_doc(doc_id, formatted_schedule)
    - Call clear_tasks_memory()

    **EXAMPLE OUTPUT FORMAT:**
    10/23/25 - Thursday

    08:00 - 08:30: [Meeting: Journal / PT Rehab]
    09:00 - 10:30: Gym (1.5h, critical - due 2025-10-23)
    10:30 - 12:30: Boltz project (2h, medium urgency - due 2025-10-24)
    12:30 - 13:30: 1 Leetcode (1h, medium urgency - due 2025-10-24)
    13:30 - 16:00: Update dad documentation (2.5h, medium urgency - due 2025-10-26)
    [Meeting: 16:00 - 17:30: Walk Yul]
    [Meeting: 17:30 - 18:20: Cook Dinner]
    18:20 - 18:50: Update dad documentation (0.5h remaining, medium urgency - due 2025-10-26)
    18:50 - 20:00: Boltz project (1.17h, medium urgency - due 2025-10-24)

    Still on list (not scheduled today):
    - Boltz project (0.83h remaining, medium urgency - due 2025-10-24)

    ---

    **IMPORTANT MATH CHECK:**
    - If Boltz = 4h total, scheduled 2h + 1.17h = 3.17h → remaining = 0.83h ✓ (include in "Still on list")
    - If Boltz = 3.17h total, scheduled 2h + 1.17h = 3.17h → remaining = 0h ✗ (DO NOT include, task complete!)
    - If Gym = 1.5h total, scheduled 1.5h → remaining = 0h ✗ (DO NOT include)
    - If ALL tasks have 0h remaining → "Still on list" shows: "- None (all tasks complete!)"

    **NOTE:** ALL meetings shown in [Meeting: ...] format. ALL free time used (8am-8pm minus meetings).

    **CRITICAL RULES:**
    - Do NOT skip step 2 (reading doc)
    - Do NOT skip step 5 (combining all tasks)  
    - Do NOT skip step 7 (scheduling ALL available free time)
    - Do NOT leave gaps in the schedule if there are tasks left to schedule
    - Do NOT stop scheduling at 1pm if free time continues until 4pm or 8pm
    - ALWAYS use partial scheduling if a task doesn't fit completely
    - NEVER include tasks with 0h remaining in "Still on list" - they are COMPLETE!
    """

# === SERVER ENTRY POINT ===

if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8084)
