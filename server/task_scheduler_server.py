"""
Task Scheduler MCP Server

MCP server that provides data access tools for task scheduling.
Exposes tools for calendar events, document operations, and task memory management.
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
from services.oauth_service import OAuthService
from services.user_config_service import UserConfigService
from services.security_service import SecurityService
from config.settings import get_settings

logger = get_logger(__name__)

# === SECURITY HELPERS ===

import re
from pathlib import Path

def sanitize_user_id(user_id: str) -> str:
    """
    Sanitize user ID to prevent path traversal and injection attacks.
    
    Args:
        user_id: Raw user ID from request
        
    Returns:
        Sanitized user ID safe for use in file paths
        
    Raises:
        ValueError: If user_id contains dangerous characters
    """
    if not user_id:
        raise ValueError("User ID cannot be empty")
    
    # Remove any path traversal attempts
    user_id = user_id.replace('..', '').replace('/', '').replace('\\', '')
    
    # Only allow alphanumeric, hyphens, underscores, and dots
    if not re.match(r'^[a-zA-Z0-9._-]+$', user_id):
        raise ValueError(f"Invalid user ID format: {user_id}")
    
    # Limit length to prevent abuse
    if len(user_id) > 100:
        raise ValueError("User ID too long")
    
    return user_id

def validate_doc_id(doc_id: str) -> str:
    """
    Validate Google Doc ID format.
    
    Args:
        doc_id: Google Doc ID
        
    Returns:
        Validated doc_id
        
    Raises:
        ValueError: If doc_id is invalid
    """
    if not doc_id:
        raise ValueError("Document ID cannot be empty")
    
    # Google Doc IDs are typically 44 characters, alphanumeric with hyphens/underscores
    if len(doc_id) > 100:
        raise ValueError("Document ID too long")
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', doc_id):
        raise ValueError("Invalid document ID format")
    
    return doc_id

def require_authentication(ctx: Context, oauth_service: OAuthService) -> str:
    """
    Require user authentication before allowing operations.
    
    Args:
        ctx: Request context
        oauth_service: OAuth service instance
        
    Returns:
        Sanitized user_id
        
    Raises:
        RuntimeError: If user is not authenticated
        ValueError: If user_id is invalid
    """
    user_id = get_user_id(ctx)
    user_id = sanitize_user_id(user_id)
    
    if not oauth_service.is_user_authenticated(user_id):
        raise RuntimeError(
            f"User {user_id} is not authenticated. Please complete OAuth flow first."
        )
    
    return user_id

# Helper function to extract user_id from context
def get_user_id(ctx: Context) -> str:
    """
    Extract user ID from request context.
    
    For ChatGPT integration, user_id should be passed in headers or metadata.
    Falls back to 'default' for backward compatibility.
    
    Note: This function does NOT sanitize or validate. Use require_authentication()
    for security-critical operations.
    """
    try:
        if ctx and hasattr(ctx, 'request_context') and ctx.request_context:
            # Try to get from headers (when called via HTTP)
            headers = getattr(ctx.request_context, 'headers', {})
            if headers:
                user_id = headers.get('x-user-id') or headers.get('user-id') or headers.get('X-User-ID')
                if user_id:
                    logger.debug(f"Extracted user_id from headers: {user_id}")
                    return user_id
            
            # Try to get from metadata
            metadata = getattr(ctx.request_context, 'metadata', {})
            if metadata and 'user_id' in metadata:
                user_id = metadata['user_id']
                logger.debug(f"Extracted user_id from metadata: {user_id}")
                return user_id
    except Exception as e:
        logger.warning(f"Error extracting user_id from context: {e}")
    
    # Default fallback (for backward compatibility or local testing)
    logger.debug("Using default user_id")
    return 'default'

# === APPLICATION CONTEXT ===

@dataclass
class AppContext:
    """Application context with all services."""
    task_scheduler_service: TaskSchedulerService
    google_calendar_service: GoogleCalendarService
    google_docs_service: GoogleDocsService
    oauth_service: OAuthService
    user_config_service: UserConfigService
    security_service: SecurityService
    settings: object

@asynccontextmanager
async def app_lifespan(mcp: FastMCP):
    """Initialize all services for the task scheduler."""
    try:
        logger.info("Initializing Task Scheduler MCP Server...")
        # Get settings
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize services
        logger.info("Initializing services...")
        oauth_service = OAuthService()
        user_config_service = UserConfigService()
        security_service = SecurityService(data_dir=settings.data_dir)
        google_calendar_service = GoogleCalendarService(oauth_service=oauth_service)
        google_docs_service = GoogleDocsService(oauth_service=oauth_service)
        
        task_scheduler_service = TaskSchedulerService(
            data_dir=settings.data_dir,
            google_docs_service=google_docs_service,
            google_calendar_service=google_calendar_service
        )
        
        app_context = AppContext(
            task_scheduler_service=task_scheduler_service,
            google_calendar_service=google_calendar_service,
            google_docs_service=google_docs_service,
            oauth_service=oauth_service,
            user_config_service=user_config_service,
            security_service=security_service,
            settings=settings
        )
        
        # Store app_context globally for OAuth routes
        set_global_app_context(app_context)
        logger.info("Task Scheduler MCP Server initialized successfully")
        
        yield app_context
    except Exception as e:
        logger.error(f"Error during app lifespan: {e}", exc_info=True)
        raise
    finally:
        logger.info("Shutting down Task Scheduler MCP Server")

# === MCP SERVER ===

# Get current date for instructions
current_date_str = datetime.now().strftime('%A, %B %d, %Y')

mcp = FastMCP(
    name="task-scheduler-server",
    instructions=f"""You are a Task Scheduling Assistant and editor-in-chief of the user's daily schedule.

Current date: {current_date_str}

Your mission: Help users plan their day by intelligently combining tasks from multiple sources, prioritizing work, and time-blocking around meetings.

**CRITICAL: AVAILABLE TOOLS - USE ONLY THESE TOOLS:**
- get_workflow_instructions() - **MUST CALL THIS FIRST when user asks for a schedule**
- check_setup_status() - Check if system is configured
- set_default_doc_id(doc_id) - Set the default Google Doc ID
- get_default_doc_id() - Get the current default Doc ID
- read_doc_content(doc_id) - Read content from a Google Doc
- write_schedule_to_doc(doc_id, content) - Write schedule to a Google Doc
- get_calendar_events(date) - Get calendar events for a date (YYYY-MM-DD)
- get_free_time_slots(date, start_hour, end_hour) - Get free time slots
- add_task(task_name, hours, urgency, due_date) - Add a task to memory
- get_tasks_from_memory() - Get all tasks in memory
- clear_tasks_memory() - Clear all tasks from memory

**DO NOT INVENT OR HALLUCINATE TOOL NAMES. ONLY USE THE TOOLS LISTED ABOVE.**

**WORKFLOW FOR "GENERATE SCHEDULE" REQUESTS:**
1. **FIRST**: Call get_workflow_instructions() - This returns the complete workflow
2. **THEN**: Follow the workflow steps exactly as returned
3. **NEVER**: Invent tool names like "generate_next_day_plan_v2" or "generate_tasks_and_timings"
4. **ALWAYS**: Use only the tools listed above

**If user says "generate schedule", "tomorrow's schedule", "create schedule", etc.:**
- Step 1: Call get_workflow_instructions()
- Step 2: Follow the returned workflow exactly
- Step 3: Use only the tools from the list above""",
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
    logger.info(f"➕ TOOL CALLED: add_task(task_name={task_name}, hours={hours}, urgency={urgency}, due_date={due_date})")
    
    # Security: Validate inputs
    if not task_name or len(task_name.strip()) == 0:
        return "Error: Task name cannot be empty."
    if len(task_name) > 500:
        return "Error: Task name too long (max 500 characters)."
    
    if not isinstance(hours, (int, float)) or hours <= 0 or hours > 24:
        return "Error: Hours must be a positive number between 0 and 24."
    
    valid_urgency = ['critical', 'high', 'medium', 'low']
    if urgency not in valid_urgency:
        return f"Error: Urgency must be one of: {', '.join(valid_urgency)}"
    
    if due_date:
        try:
            from datetime import datetime
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            return "Error: Due date must be in YYYY-MM-DD format."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    service = ctx.request_context.lifespan_context.task_scheduler_service
    result = service.add_task(task_name, hours, urgency, due_date)
    logger.info(f"➕ add_task result: {result}")
    return result

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
    # Security: Validate doc_id
    # Extract doc ID from URL if full URL provided
    if "docs.google.com/document/d/" in doc_id:
        # Extract ID from URL like: https://docs.google.com/document/d/1ABC123XYZ789/edit
        import re
        match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', doc_id)
        if match:
            doc_id = match.group(1)
        else:
            return "Error: Could not extract Google Doc ID from URL. Please provide just the ID."
    
    try:
        doc_id = validate_doc_id(doc_id)
    except ValueError as e:
        logger.error(f"Invalid doc_id: {e}")
        return f"Error: Invalid document ID format."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    service = ctx.request_context.lifespan_context.task_scheduler_service
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
async def get_workflow_instructions(
    ctx: Context = None
) -> str:
    """
    Get the complete workflow instructions for generating schedules.
    
    **CRITICAL: THIS IS THE FIRST TOOL YOU MUST CALL when user asks for a schedule.**
    
    **WHEN TO USE THIS TOOL:**
    WHEN USER SAYS ANYTHING LIKE "generate schedule", "tomorrow's schedule", "create schedule", "plan tomorrow", etc., YOU MUST:
    1. CALL THIS TOOL FIRST (get_workflow_instructions)
    2. THEN follow the returned workflow exactly
    3. DO NOT invent tool names - only use tools that exist
    4. DO NOT skip steps
    
    **DO NOT INVENT TOOLS LIKE:**
    - generate_next_day_plan_v2 (DOES NOT EXIST)
    - generate_tasks_and_timings (DOES NOT EXIST)
    - create_schedule (DOES NOT EXIST)
    
    **ONLY USE THESE REAL TOOLS:**
    - get_workflow_instructions (this tool)
    - check_setup_status
    - read_doc_content
    - get_calendar_events
    - get_free_time_slots
    - add_task
    - get_tasks_from_memory
    - write_schedule_to_doc
    - clear_tasks_memory
    
    This returns the complete step-by-step process you MUST follow when generating schedules.
    
    Returns:
        Complete workflow instructions with all 10 steps
    """
    return """COMPLETE WORKFLOW FOR GENERATING TOMORROW'S SCHEDULE:

**IMPORTANT: Follow ALL steps in order. DO NOT skip steps. DO NOT make up your own workflow.**

1. CHECK SETUP - **YOU MUST DO THIS FIRST**
   - **CALL check_setup_status() tool immediately**
   - If no default doc ID, guide user to provide it using set_default_doc_id()
   - **DO NOT proceed without a doc ID**

2. READ DOCUMENT CONTENT - **YOU MUST DO THIS BEFORE CREATING SCHEDULE - DO NOT SKIP**
   - **CALL read_doc_content(doc_id) tool to get the document** (use doc_id from step 1)
   - Parse today's date section (format: MM/DD/YY - Day)
   - Extract incomplete tasks (lines starting with "-" but NO ✓ or ✔)
   - Extract "Still on list" section tasks (also NO ✓ or ✔)
   - **CRITICAL: Include ALL incomplete tasks from today with EXACT names**
   - **DO NOT create a schedule without reading the document first**

3. ASK USER FOR NEW TASKS - **YOU MUST ASK THE USER - THIS IS NOT OPTIONAL**
   - **YOU MUST ASK: "What new tasks would you like to add for tomorrow?"**
   - **WAIT for user response** (this is a conversation turn - user will respond in the next message)
   - **After user responds:**
     * If user says "none" or "no new tasks" → that's fine, proceed to step 4 with only carryover tasks
     * If user provides specific tasks → CALL add_task() for each task they mention
   - **CALL get_tasks_from_memory() tool to retrieve all tasks** (call this after user responds)
   - **CRITICAL CLARIFICATION: "Do NOT create generic tasks" means:**
     * DO ask the user for new tasks (this step is required)
     * DO NOT invent placeholder tasks like "Morning Work Session" or "Deep work block"
     * ONLY use: (1) carryover tasks from document, (2) tasks user explicitly provides, (3) "Still on list" tasks

4. GET CALENDAR DATA - **YOU MUST DO THIS - DO NOT SKIP THIS STEP**
   - Calculate tomorrow's date (today + 1 day, format: YYYY-MM-DD)
   - **CALL get_calendar_events(tomorrow_date) tool FIRST** (e.g., "2025-11-15")
   - **THEN CALL get_free_time_slots(tomorrow_date, 8, 20) tool**
   - **CRITICAL: You MUST call get_calendar_events() BEFORE get_free_time_slots()**
   - **CRITICAL: Only include main calendar events (visible in Google Calendar UI)**
   - **CRITICAL: Include ALL calendar events in the schedule as [Meeting: ...] entries**

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
   - For EACH task, calculate: Total - Scheduled = Remaining
   - If Remaining = 0h → Task is COMPLETE, exclude from "Still on list"
   - If Remaining > 0h → Include in "Still on list" with correct remaining time

9. SORT ALL EVENTS CHRONOLOGICALLY - **DO THIS BEFORE FORMATTING**
   - Collect ALL scheduled items: tasks AND meetings
   - Sort by START TIME (HH:MM) - earliest to latest
   - Create a single ordered list mixing tasks and meetings by time
   - This sorted list is what you will format in step 10

10. FORMAT SCHEDULE (EXACT FORMAT)
   - Header: MM/DD/YY - Day
   - **CRITICAL: CHRONOLOGICAL ORDERING - THIS IS MANDATORY**
     * Sort ALL events (both tasks AND meetings) by START TIME (HH:MM)
     * Earliest event first, latest event last
     * DO NOT group meetings together or tasks together - mix them by time
     * Example correct order:
       - [Meeting: 07:45 - 09:15: Walk Yul] ← earliest (7:45)
       - [Meeting: 08:00 - 08:30: Journal] ← next (8:00)
       - 09:15 - 09:45: Task name ← next (9:15)
       - [Meeting: 12:00 - 13:00: Lunch] ← next (12:00)
     * Example WRONG order (DO NOT DO THIS):
       - 09:15 - 09:45: Task name ← WRONG! This is after 7:45
       - [Meeting: 07:45 - 09:15: Walk Yul] ← Should be first!
   - Task format: HH:MM - HH:MM: Task name (Xh, urgency - due date)
   - Meeting format: [Meeting: HH:MM - HH:MM: Meeting name]
   - CRITICAL: Include EVERY calendar event as [Meeting: ...] in chronological order
   - Blank line before "Still on list" section
   - Catch-all: "Still on list (not scheduled today):"
     * ONLY include tasks where remaining_time > 0
     * Format: "- Task name (Xh remaining, urgency - due date)"
   - Footer: "---"
   - CRITICAL: NO "NOTES" sections, NO custom formatting

11. WRITE AND CLEANUP - **YOU MUST DO THIS**
   - **CALL write_schedule_to_doc(doc_id, formatted_schedule) tool to save the schedule**
   - **CALL clear_tasks_memory() tool to clean up**
   - **DO NOT skip writing to the document - the schedule must be saved**

**EXAMPLE OUTPUT FORMAT (NOTE: All events in chronological order by start time):**
10/23/25 - Thursday

[Meeting: 07:45 - 08:00: Morning Routine]
[Meeting: 08:00 - 08:30: Journal / PT Rehab]
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
- Do NOT skip step 3 (asking for new tasks)
- Do NOT skip step 4 (getting calendar data)
- Do NOT skip step 9 (sorting chronologically)
- Do NOT skip step 11 (writing to document)
- ALWAYS follow ALL steps in order"""

@mcp.tool()
async def check_setup_status(
    ctx: Context = None
) -> str:
    """
    Check if the system is properly set up for task scheduling.
    
    Use this when: Starting to generate a schedule. ALWAYS call this first before generating any schedule.
    This checks if a default Google Doc ID is configured. If not, you must ask the user to provide one using set_default_doc_id().
    
    Returns:
        Status message about setup and next steps
    """
    logger.info("🔧 TOOL CALLED: check_setup_status")
    service = ctx.request_context.lifespan_context.task_scheduler_service
    result = service.check_setup_status()
    logger.info(f"🔧 check_setup_status result: {result[:100]}...")
    return result

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
    logger.info(f"📅 TOOL CALLED: get_calendar_events(date={date})")
    
    # Security: Validate date format
    try:
        from datetime import datetime
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        # Prevent querying dates too far in past/future
        from datetime import date as date_class
        today = date_class.today()
        days_diff = abs((target_date - today).days)
        if days_diff > 365:
            raise ValueError(f"Date must be within 1 year: {date}")
    except ValueError as e:
        logger.error(f"Invalid date format: {date} - {e}")
        return f"Error: Invalid date format. Use YYYY-MM-DD format and date must be within 1 year."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    security_service = ctx.request_context.lifespan_context.security_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    # Security: Rate limiting
    is_allowed, rate_limit_error = security_service.check_rate_limit(user_id, 'read')
    if not is_allowed:
        security_service.log_audit_event('rate_limit_exceeded', user_id, {'operation': 'get_calendar_events', 'date': date}, 'warning')
        return f"Error: {rate_limit_error}"
    
    service = ctx.request_context.lifespan_context.google_calendar_service
    events = service.get_events_for_date(target_date, user_id)
    
    # Security: Check calendar event titles/descriptions for prompt injection
    for event in events:
        event_text = f"{event.get('summary', '')} {event.get('description', '')}"
        is_injection, patterns = security_service.detect_prompt_injection(event_text)
        if is_injection:
            security_service.log_audit_event(
                'prompt_injection_detected',
                user_id,
                {
                    'operation': 'get_calendar_events',
                    'date': date,
                    'event_id': event.get('id'),
                    'patterns': patterns
                },
                'warning'
            )
    
    # Log successful read
    security_service.log_audit_event('read_operation', user_id, {
        'operation': 'get_calendar_events',
        'date': date,
        'event_count': len(events)
    }, 'info')
    
    result = f"Found {len(events)} events for {date}: {events}"
    logger.info(f"📅 get_calendar_events result: {result[:200]}...")
    return result

@mcp.tool()
async def get_free_time_slots(
    date: str,
    start_hour: int = 8,
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
    logger.info(f"⏰ TOOL CALLED: get_free_time_slots(date={date}, start_hour={start_hour}, end_hour={end_hour})")
    
    # Security: Validate date format
    try:
        from datetime import datetime
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        from datetime import date as date_class
        today = date_class.today()
        days_diff = abs((target_date - today).days)
        if days_diff > 365:
            raise ValueError(f"Date must be within 1 year: {date}")
    except ValueError as e:
        logger.error(f"Invalid date format: {date} - {e}")
        return f"Error: Invalid date format. Use YYYY-MM-DD format and date must be within 1 year."
    
    # Security: Validate hour ranges
    if not (0 <= start_hour <= 23) or not (0 <= end_hour <= 23):
        logger.error(f"Invalid hour range: {start_hour}-{end_hour}")
        return "Error: Hours must be between 0 and 23."
    if start_hour >= end_hour:
        logger.error(f"Invalid hour range: start_hour ({start_hour}) must be less than end_hour ({end_hour})")
        return "Error: Start hour must be less than end hour."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    security_service = ctx.request_context.lifespan_context.security_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    # Security: Rate limiting
    is_allowed, rate_limit_error = security_service.check_rate_limit(user_id, 'read')
    if not is_allowed:
        security_service.log_audit_event('rate_limit_exceeded', user_id, {'operation': 'get_free_time_slots', 'date': date}, 'warning')
        return f"Error: {rate_limit_error}"
    
    service = ctx.request_context.lifespan_context.google_calendar_service
    slots = service.get_free_time_slots(target_date, user_id, start_hour, end_hour)
    
    # Log successful read
    security_service.log_audit_event('read_operation', user_id, {
        'operation': 'get_free_time_slots',
        'date': date,
        'slot_count': len(slots)
    }, 'info')
    
    result = f"Free time slots for {date}: {slots}"
    logger.info(f"⏰ get_free_time_slots result: {result[:200]}...")
    return result

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
    logger.info(f"📄 TOOL CALLED: read_doc_content(doc_id={doc_id})")
    
    # Security: Validate doc_id
    try:
        doc_id = validate_doc_id(doc_id)
    except ValueError as e:
        logger.error(f"Invalid doc_id: {e}")
        return f"Error: Invalid document ID format."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    security_service = ctx.request_context.lifespan_context.security_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    # Security: Rate limiting
    is_allowed, rate_limit_error = security_service.check_rate_limit(user_id, 'read')
    if not is_allowed:
        security_service.log_audit_event('rate_limit_exceeded', user_id, {'operation': 'read_doc_content', 'doc_id': doc_id}, 'warning')
        return f"Error: {rate_limit_error}"
    
    service = ctx.request_context.lifespan_context.google_docs_service
    try:
        content = service.read_document(doc_id, user_id)
        
        # Security: Limit response size to prevent DoS
        max_content_length = 100000  # 100KB
        if len(content) > max_content_length:
            logger.warning(f"Document content too large: {len(content)} chars, truncating")
            content = content[:max_content_length] + "\n\n[Content truncated - document too large]"
        
        # Security: Check for prompt injection in content
        is_injection, patterns = security_service.detect_prompt_injection(content)
        if is_injection:
            security_service.log_audit_event(
                'prompt_injection_detected',
                user_id,
                {
                    'operation': 'read_doc_content',
                    'doc_id': doc_id,
                    'patterns': patterns,
                    'content_preview': security_service.sanitize_content_for_logging(content, 200)
                },
                'warning'
            )
            # Return content with warning (don't block, but log it)
            warning = security_service.get_security_warning_for_content(content)
            if warning:
                content = f"{warning}\n\n{content}"
        
        # Log successful read
        security_service.log_audit_event('read_operation', user_id, {
            'operation': 'read_doc_content',
            'doc_id': doc_id,
            'content_length': len(content)
        }, 'info')
        
        logger.info(f"📄 read_doc_content result length: {len(content)} chars")
        return content
    except Exception as e:
        logger.error(f"Error reading document: {e}")
        security_service.log_audit_event('read_error', user_id, {
            'operation': 'read_doc_content',
            'doc_id': doc_id,
            'error': str(e)
        }, 'error')
        return f"Error: Failed to read document. {str(e)}"

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
    logger.info(f"✍️ TOOL CALLED: write_schedule_to_doc(doc_id={doc_id}, content_length={len(content)})")
    
    # Security: Validate doc_id
    try:
        doc_id = validate_doc_id(doc_id)
    except ValueError as e:
        logger.error(f"Invalid doc_id: {e}")
        return f"Error: Invalid document ID format."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    security_service = ctx.request_context.lifespan_context.security_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    # Security: Rate limiting
    is_allowed, rate_limit_error = security_service.check_rate_limit(user_id, 'write')
    if not is_allowed:
        security_service.log_audit_event('rate_limit_exceeded', user_id, {
            'operation': 'write_schedule_to_doc',
            'doc_id': doc_id
        }, 'warning')
        return f"Error: {rate_limit_error}"
    
    # Security: Limit content size to prevent DoS
    max_content_length = 50000  # 50KB for writes
    if len(content) > max_content_length:
        logger.error(f"Content too large: {len(content)} chars, max is {max_content_length}")
        security_service.log_audit_event('write_validation_failed', user_id, {
            'operation': 'write_schedule_to_doc',
            'doc_id': doc_id,
            'reason': 'content_too_large',
            'size': len(content)
        }, 'warning')
        return f"Error: Content too large ({len(content)} chars). Maximum is {max_content_length} characters."
    
    # Security: Validate write content for suspicious patterns
    is_valid, validation_error = security_service.validate_write_content(content, doc_id, user_id)
    if not is_valid:
        return f"Error: {validation_error}"
    
    service = ctx.request_context.lifespan_context.google_docs_service
    try:
        service.write_to_doc(doc_id, content, user_id)
        
        # Log successful write
        security_service.log_audit_event('write_operation', user_id, {
            'operation': 'write_schedule_to_doc',
            'doc_id': doc_id,
            'content_length': len(content),
            'content_preview': security_service.sanitize_content_for_logging(content, 100)
        }, 'info')
        
        result = f"Successfully wrote content to document {doc_id}"
        logger.info(f"✍️ write_schedule_to_doc completed")
        return result
    except Exception as e:
        logger.error(f"Error writing to document: {e}")
        security_service.log_audit_event('write_error', user_id, {
            'operation': 'write_schedule_to_doc',
            'doc_id': doc_id,
            'error': str(e)
        }, 'error')
        return f"Error: Failed to write to document. {str(e)}"

@mcp.tool()
async def get_tasks_from_memory(
    ctx: Context = None
) -> str:
    """
    Get all tasks currently in memory.
    """
    logger.info("📋 TOOL CALLED: get_tasks_from_memory")
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    service = ctx.request_context.lifespan_context.task_scheduler_service
    tasks = service.get_tasks_from_memory()
    result = f"Tasks in memory: {tasks}"
    logger.info(f"📋 get_tasks_from_memory result: {result[:200]}...")
    return result

@mcp.tool()
async def clear_tasks_memory(
    ctx: Context = None
) -> str:
    """
    Clear all tasks from memory.
    """
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    service = ctx.request_context.lifespan_context.task_scheduler_service
    return service.clear_tasks_memory()

# === RESOURCES ===

@mcp.resource(uri="docs://{doc_id}")
async def get_doc_resource(doc_id: str, ctx: Context) -> str:
    """Expose Google Doc content as a resource."""
    # Security: Validate doc_id
    try:
        doc_id = validate_doc_id(doc_id)
    except ValueError as e:
        logger.error(f"Invalid doc_id in resource: {e}")
        return f"Error: Invalid document ID format."
    
    # Security: Require authentication
    oauth_service = ctx.request_context.lifespan_context.oauth_service
    security_service = ctx.request_context.lifespan_context.security_service
    try:
        user_id = require_authentication(ctx, oauth_service)
    except (RuntimeError, ValueError) as e:
        logger.error(f"Authentication failed: {e}")
        return f"Error: {str(e)}"
    
    # Security: Rate limiting
    is_allowed, rate_limit_error = security_service.check_rate_limit(user_id, 'read')
    if not is_allowed:
        security_service.log_audit_event('rate_limit_exceeded', user_id, {'operation': 'get_doc_resource', 'doc_id': doc_id}, 'warning')
        return f"Error: {rate_limit_error}"
    
    service = ctx.request_context.lifespan_context.google_docs_service
    try:
        content = service.read_document(doc_id, user_id)
        # Security: Limit response size
        max_content_length = 100000  # 100KB
        if len(content) > max_content_length:
            content = content[:max_content_length] + "\n\n[Content truncated - document too large]"
        
        # Security: Check for prompt injection
        is_injection, patterns = security_service.detect_prompt_injection(content)
        if is_injection:
            security_service.log_audit_event(
                'prompt_injection_detected',
                user_id,
                {
                    'operation': 'get_doc_resource',
                    'doc_id': doc_id,
                    'patterns': patterns
                },
                'warning'
            )
        
        # Log resource access
        security_service.log_audit_event('read_operation', user_id, {
            'operation': 'get_doc_resource',
            'doc_id': doc_id,
            'content_length': len(content)
        }, 'info')
        
        return content
    except Exception as e:
        logger.error(f"Error reading document resource: {e}")
        security_service.log_audit_event('read_error', user_id, {
            'operation': 'get_doc_resource',
            'doc_id': doc_id,
            'error': str(e)
        }, 'error')
        return f"Error: Failed to read document. {str(e)}"

# === PROMPTS ===
# Note: Prompts removed - all workflow instructions are now in get_workflow_instructions() tool

# === OAUTH ENDPOINTS ===
# Use FastMCP's official @mcp.custom_route decorator to add OAuth routes
# This is the official way to add custom HTTP routes to FastMCP

from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse, Response
from fastapi import HTTPException

# Store app_context globally for OAuth routes
_global_app_context = None

def set_global_app_context(app_context):
    """Set the global app context for OAuth routes."""
    global _global_app_context
    _global_app_context = app_context

def get_oauth_service():
    """Get OAuth service from app context."""
    global _global_app_context
    if _global_app_context is None or not hasattr(_global_app_context, 'oauth_service'):
        raise HTTPException(status_code=500, detail="OAuth service not initialized")
    return _global_app_context.oauth_service

def get_user_config_service():
    """Get user config service from app context."""
    global _global_app_context
    if _global_app_context is None or not hasattr(_global_app_context, 'user_config_service'):
        raise HTTPException(status_code=500, detail="User config service not initialized")
    return _global_app_context.user_config_service

# Register OAuth routes using FastMCP's custom_route decorator
@mcp.custom_route("/oauth/authorize", methods=["GET"])
async def oauth_authorize(request: Request):
    """Initiate OAuth flow."""
    user_id = request.query_params.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id parameter is required")
    
    try:
        oauth_service = get_oauth_service()
        auth_url = oauth_service.get_authorization_url(user_id)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Error generating authorization URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@mcp.custom_route("/oauth/callback", methods=["GET"])
async def oauth_callback(request: Request):
    """Handle OAuth callback."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")
    
    try:
        oauth_service = get_oauth_service()
        user_id = oauth_service.handle_callback(code, state)
        
        if user_id:
            return JSONResponse({
                "status": "success",
                "message": f"Successfully authenticated user {user_id}",
                "user_id": user_id
            })
        else:
            raise HTTPException(status_code=400, detail="Failed to authenticate")
    except Exception as e:
        logger.error(f"Error handling OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@mcp.custom_route("/oauth/status", methods=["GET"])
async def oauth_status(request: Request):
    """Check OAuth status for a user."""
    user_id = request.query_params.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id parameter is required")
    
    # Security: Sanitize user_id
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError as e:
        logger.error(f"Invalid user_id in OAuth status: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid user_id: {str(e)}")
    
    try:
        oauth_service = get_oauth_service()
        is_authenticated = oauth_service.is_user_authenticated(user_id)
        
        return JSONResponse({
            "user_id": user_id,
            "authenticated": is_authenticated
        })
    except Exception as e:
        logger.error(f"Error checking OAuth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@mcp.custom_route("/oauth/config/openrouter", methods=["POST"])
async def set_openrouter_key(request: Request):
    """Store OpenRouter API key for a user."""
    try:
        body = await request.json()
        user_id = body.get("user_id")
        api_key = body.get("api_key")
        
        if not user_id or not api_key:
            raise HTTPException(status_code=400, detail="user_id and api_key are required")
        
        # Security: Sanitize user_id
        try:
            user_id = sanitize_user_id(user_id)
        except ValueError as e:
            logger.error(f"Invalid user_id in OpenRouter config: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid user_id: {str(e)}")
        
        # Security: Validate API key format (basic check)
        if not isinstance(api_key, str) or len(api_key) < 10 or len(api_key) > 500:
            raise HTTPException(status_code=400, detail="Invalid API key format")
        
        # Security: Require authentication before storing API key
        oauth_service = get_oauth_service()
        if not oauth_service.is_user_authenticated(user_id):
            raise HTTPException(status_code=401, detail="User must be authenticated to store API key")
        
        user_config_service = get_user_config_service()
        success = user_config_service.set_openrouter_api_key(user_id, api_key)
        
        if success:
            return JSONResponse({
                "status": "success",
                "message": f"OpenRouter API key stored for user {user_id}"
            })
        else:
            raise HTTPException(status_code=500, detail="Failed to store API key")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error storing OpenRouter API key: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request):
    """
    Health check endpoint for monitoring and connection validation.
    Helps prevent ChatGPT from caching bad connection states.
    """
    try:
        # Check if services are initialized
        oauth_service = get_oauth_service()
        
        return JSONResponse({
            "status": "healthy",
            "service": "task-scheduler-mcp-server",
            "version": "1.0.0",
            "mcp_endpoint": "/mcp",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            },
            status_code=503
        )

@mcp.custom_route("/tools", methods=["GET"])
async def list_tools(request: Request):
    """
    List available MCP tools.
    Helps diagnose connector issues by showing what tools are actually available.
    """
    try:
        # Get list of tools from the MCP server
        # FastMCP exposes tools, but we need to get them from the mcp instance
        # For now, return a static list based on what we know exists
        available_tools = [
            "add_task",
            "set_default_doc_id",
            "get_default_doc_id",
            "get_workflow_instructions",
            "check_setup_status",
            "get_calendar_events",
            "get_free_time_slots",
            "read_doc_content",
            "write_schedule_to_doc",
            "get_tasks_from_memory",
            "clear_tasks_memory"
        ]
        
        # Common hallucinated tool names that don't exist
        non_existent_tools = [
            "generate_next_day_plan_v2",
            "generate_tasks_and_timings",
            "create_schedule",
            "generate_schedule",
            "plan_next_day"
        ]
        
        return JSONResponse({
            "tools": available_tools,
            "count": len(available_tools),
            "non_existent_tools": non_existent_tools,
            "note": "Tools are accessed via MCP protocol at /mcp, not as REST endpoints",
            "mcp_endpoint": "/mcp",
            "connector_diagnosis": {
                "if_you_see_resource_not_found": "ChatGPT connector is in bad state - delete and recreate it",
                "if_tools_not_appearing": "Check that connector URL ends with /mcp",
                "if_hallucinated_tools": "ChatGPT is inventing tool names - recreate connector"
            },
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return JSONResponse(
            {
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            },
            status_code=500
        )

@mcp.custom_route("/privacy", methods=["GET"])
async def privacy_policy(request: Request):
    """Privacy Policy page."""
    privacy_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - Productivity Agent</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }
        h1 {
            color: #1a73e8;
            border-bottom: 2px solid #1a73e8;
            padding-bottom: 10px;
        }
        h2 {
            color: #5f6368;
            margin-top: 30px;
        }
        .last-updated {
            color: #666;
            font-style: italic;
            margin-bottom: 30px;
        }
        a {
            color: #1a73e8;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p class="last-updated">Last Updated: November 15, 2025</p>
    
    <h2>1. Introduction</h2>
    <p>Productivity Agent ("we", "our", or "us") is a task scheduling application that helps users manage their daily schedules by integrating with Google Calendar and Google Docs. This Privacy Policy explains how we collect, use, and protect your information when you use our service.</p>
    
    <h2>2. Information We Collect</h2>
    <h3>2.1 Google OAuth Data</h3>
    <p>To provide our service, we require access to your Google account through OAuth 2.0. We request the following permissions:</p>
    <ul>
        <li><strong>Google Calendar (Read-only)</strong>: To read your calendar events and free time slots</li>
        <li><strong>Google Docs</strong>: To read and write your schedule documents</li>
        <li><strong>Google Drive (Files)</strong>: To access and modify your schedule documents</li>
    </ul>
    <p>We do not collect or store your Google account password. All authentication is handled securely through Google's OAuth system.</p>
    
    <h3>2.2 OAuth Tokens</h3>
    <p>We store OAuth access and refresh tokens on our servers to maintain your authenticated session. These tokens are:</p>
    <ul>
        <li>Stored per-user in encrypted storage on Fly.io infrastructure</li>
        <li>Used only to access the Google services you've authorized</li>
        <li>Automatically refreshed when they expire</li>
        <li>Deleted if you revoke access through your Google account settings</li>
    </ul>
    
    <h3>2.3 Optional: OpenRouter API Keys</h3>
    <p>If you use our local FastAgent client (not ChatGPT), you may optionally provide an OpenRouter API key. This key is:</p>
    <ul>
        <li>Stored securely on our servers</li>
        <li>Used only for your local client requests</li>
        <li>Not required for ChatGPT integration (ChatGPT uses its own LLM)</li>
        <li>Never shared with third parties</li>
    </ul>
    
    <h3>2.4 User Identification</h3>
    <p>We use a user ID (provided by your client application, such as ChatGPT) to associate your data with your account. We do not collect personally identifiable information such as your name or email address unless you explicitly provide it.</p>
    
    <h2>3. How We Use Your Information</h2>
    <p>We use the information we collect solely to:</p>
    <ul>
        <li>Access your Google Calendar to read events and calculate free time slots</li>
        <li>Read and write schedule documents in your Google Docs</li>
        <li>Generate personalized daily schedules based on your calendar and tasks</li>
        <li>Maintain your authenticated session with Google services</li>
    </ul>
    <p>We do not:</p>
    <ul>
        <li>Share your data with third parties</li>
        <li>Use your data for advertising or marketing</li>
        <li>Analyze your personal information for purposes other than providing our service</li>
        <li>Sell your data to anyone</li>
    </ul>
    
    <h2>4. Data Storage and Security</h2>
    <h3>4.1 Storage Location</h3>
    <p>Your OAuth tokens and configuration data are stored on Fly.io infrastructure in encrypted volumes. Data is stored in the United States (US-East region) unless otherwise specified.</p>
    
    <h3>4.2 Security Measures</h3>
    <p>We implement the following security measures:</p>
    <ul>
        <li>OAuth tokens stored in encrypted Fly.io volumes</li>
        <li>HTTPS encryption for all data transmission</li>
        <li>Per-user data isolation (each user's tokens are stored separately)</li>
        <li>No storage of passwords or sensitive credentials</li>
    </ul>
    
    <h2>5. Data Retention</h2>
    <p>We retain your OAuth tokens and configuration data for as long as you use our service. You can revoke access at any time through your Google account settings, which will immediately invalidate your tokens. We will delete your stored data if you revoke access or if you request deletion.</p>
    
    <h2>6. Your Rights and Choices</h2>
    <h3>6.1 Access and Control</h3>
    <p>You have the right to:</p>
    <ul>
        <li>Revoke Google OAuth access at any time through <a href="https://myaccount.google.com/permissions" target="_blank">Google Account Settings</a></li>
        <li>Request deletion of your stored data</li>
        <li>Stop using the service at any time</li>
    </ul>
    
    <h3>6.2 Data Deletion</h3>
    <p>To request deletion of your data, revoke access through your Google account settings. This will immediately invalidate your tokens and prevent further access to your Google services.</p>
    
    <h2>7. Third-Party Services</h2>
    <h3>7.1 Google Services</h3>
    <p>Our service integrates with Google Calendar, Google Docs, and Google Drive. Your use of these services is subject to <a href="https://policies.google.com/privacy" target="_blank">Google's Privacy Policy</a>.</p>
    
    <h3>7.2 OpenRouter (Optional)</h3>
    <p>If you use our local FastAgent client and provide an OpenRouter API key, your requests may be processed through OpenRouter. This is optional and not required for ChatGPT integration. OpenRouter's privacy practices are governed by their own privacy policy.</p>
    
    <h2>8. Children's Privacy</h2>
    <p>Our service is not intended for children under 13 years of age. We do not knowingly collect personal information from children under 13.</p>
    
    <h2>9. Changes to This Privacy Policy</h2>
    <p>We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new Privacy Policy on this page and updating the "Last Updated" date. You are advised to review this Privacy Policy periodically for any changes.</p>
    
    <hr>
    <p style="color: #666; font-size: 0.9em;">
        <a href="/">← Back to Home</a>
    </p>
</body>
</html>"""
    return Response(content=privacy_html, media_type="text/html")

# OAuth routes are registered using @mcp.custom_route decorators above
# No need for manual registration - FastMCP handles it automatically!

# === SERVER ENTRY POINT ===

if __name__ == "__main__":
    # Run FastMCP - OAuth routes will be registered automatically
    # FastMCP handles MCP protocol automatically at /mcp endpoint
    logger.info("=" * 60)
    logger.info("Starting Task Scheduler MCP Server")
    logger.info("=" * 60)
    logger.info("MCP endpoint available at: http://0.0.0.0:8084/mcp")
    logger.info("Health check: GET /health")
    logger.info("Tools list: GET /tools")
    logger.info("OAuth endpoints:")
    logger.info("  - GET /oauth/authorize?user_id={id}")
    logger.info("  - GET /oauth/callback")
    logger.info("  - GET /oauth/status?user_id={id}")
    logger.info("=" * 60)
    
    try:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8084)
    except Exception as e:
        logger.error(f"Fatal error starting MCP server: {e}", exc_info=True)
        raise
