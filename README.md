# growth-pm-bot

## About

A Discord bot for managing tasks across the progsu Growth Team. Assign tasks, track deadlines, get automatic reminders, and run weekly progress reports — all from inside Discord. Built with Python, discord.py, Supabase, and hosted on Railway.

## Command Reference

| Command | Description |
| --- | --- |
| `/assign @member "task" due:YYYY-MM-DD` | Assign a task to a team member. Due date optional. |
| `/mytasks` | See your own pending tasks (only visible to you). |
| `/teamtasks @member (optional)` | See all team tasks or filter by member. |
| `/done task_id` | Mark your task as complete. Notifies the assigner. |
| `/settaskstatus task_id status` | Update a task to todo, in_progress, or done. |
| `/edittask task_id` | Edit a task's name and/or due date. Use "none" to clear the due date. |
| `/deletetask task_id` | Permanently delete a task. Admin only. |
| `/alltasks` | List every task across all statuses, sorted by status then due date. Admin only. |
| `/pingteam` | Ping @Growth with all current pending tasks. Admin only. |
| `/dmtasks @member (optional)` | DM a member (or all members) their individual pending tasks. Admin only. |
| `/addmember @member` | Add someone to the Growth team. Admin only. |
| `/progress timeframe` | Weekly progress report. Admin only. |
| `/ping` | Check if the bot is online. |
