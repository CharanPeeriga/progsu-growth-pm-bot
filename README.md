# growth-pm-bot

## About

A Discord bot for managing tasks across the progsu Growth Team. Assign tasks, track deadlines, get automatic reminders, and run weekly progress reports — all from inside Discord. Built with Python, discord.py, Supabase, and hosted on Railway.

## Command Reference

### Task Management

| Command | Who | Description |
| --- | --- | --- |
| `/assign @member "task" due:YYYY-MM-DD` | Admin | Assign a task to a member. Due date is optional. |
| `/mytasks` | Anyone | See your own tasks split into: Pending, Awaiting Review, and Recently Completed (last 5). |
| `/teamtasks @member (optional)` | Anyone | See all pending team tasks, or filter by a specific member. |
| `/inprogress task_id` | Assignee | Mark one of your tasks as in progress. |
| `/done task_id` | Assignee | Submit a completed task for admin review. |
| `/settaskstatus task_id status` | Assignee / Admin | Set a task to todo, in_progress, review, or done. |
| `/edittask task_id` | Assignee / Admin | Edit a task's name and/or due date. Use `none` to clear the due date. |
| `/deletetask task_id` | Admin | Permanently delete a task. |
| `/alltasks` | Admin | List every task across all statuses, grouped by member. |

### Review & Approval

| Command | Who | Description |
| --- | --- | --- |
| `/approve task_id` | Admin | Approve a task in review and mark it complete. |
| `/reject task_id reason` | Admin | Send a task back to in_progress with feedback. |
| `/reviewqueue` | Admin | See all tasks currently waiting for approval. |

### Team Roster

| Command | Who | Description |
| --- | --- | --- |
| `/addmember @member` | Admin | Add someone to the Growth team roster. |
| `/removemember @member` | Admin | Remove someone from the Growth team roster (does not delete their tasks). |
| `/teammembers` | Admin | List all team members with pending, completed, and overdue task counts. |

### Reminders & Notifications

| Command | Who | Description |
| --- | --- | --- |
| `/setchannel @member #channel` | Admin | Set a channel where reminders and `/remind` output are posted for a member. |
| `/remind @member` | Admin | Post a member's pending tasks publicly in their reminder channel, or ephemerally if no channel is set. |
| `/dmtasks @member (optional)` | Admin | DM a specific member their tasks, or DM all team roster members at once. |
| `/pingteam` | Admin | Post all pending tasks publicly, grouped by team member. Non-roster assignees appear in a separate section. |

### Progress & Utilities

| Command | Who | Description |
| --- | --- | --- |
| `/progress timeframe` | Admin | Weekly or all-time progress report with completion rate, overdue tasks, and upcoming deadlines. |
| `/ping` | Anyone | Check if the bot is online. |

## Task Statuses

| Status | Meaning |
| --- | --- |
| 🔵 To Do | Task assigned, not started |
| 🟡 In Progress | Assignee is actively working on it |
| ⏳ In Review | Submitted by assignee, awaiting admin approval |
| ✅ Done | Approved by admin |

If a task is sent back via `/reject`, the feedback reason is shown under the task in all task lists.

## How Task Completion Works

1. Assignee uses `/inprogress task_id` when they start working
2. Assignee uses `/done task_id` when finished — task moves to **In Review**
3. Admin receives a DM with approve/reject instructions
4. Admin uses `/approve task_id` to mark it done, or `/reject task_id reason` to send it back
5. Assignee is DM'd the result either way

## Automatic Reminders

The bot checks for upcoming deadlines every hour and sends reminders:
- **2 days before** the due date
- **Day of** the due date

Reminders go to the member's configured reminder channel (set via `/setchannel`), or as a DM if no channel is set. Tasks in review are excluded from deadline reminders.
