"""
Task Scheduler Client

Client for the task scheduler agent using FastAgent
Provides simple interface for task management and schedule generation.
"""

import asyncio
from datetime import datetime
from fast_agent import FastAgent, RequestParams

# Create the application
fast = FastAgent("Task Scheduler", config_path="client/task-scheduler.config.yaml")

# Define the agent with task scheduling capabilities
@fast.agent(
    instruction=f"""You are a task scheduling assistant.
    
Current date: {datetime.now().strftime('%A, %B %d, %Y')}

You have two simple tools:
1. add_task(task_name, hours, urgency, due_date) - Add tasks to temporary memory
2. generate_and_create_tomorrow_schedule(doc_id, work_start, work_end) - Generate complete schedule

The schedule tool automatically:
- Reads Google Doc for incomplete tasks
- Checks Google Calendar for meetings  
- Combines with new tasks
- Prioritizes all tasks (including "still on list")
- Schedules around meetings
- Appends to same doc

Help users manage their daily tasks efficiently. Always be helpful and clear about what each tool does.
""",
    name="Task Scheduler Agent",
    servers=["task_scheduler_server"],
    request_params=RequestParams(
        max_iterations=9999,
    ),
)
async def main():
    async with fast.run() as agent:
        await agent.interactive()

if __name__ == "__main__":
    asyncio.run(main())
