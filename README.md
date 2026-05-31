# growth-pm-bot

## About

A Discord bot for managing tasks across the progsu Growth Team. Assign tasks, track deadlines, get automatic reminders, and run weekly progress reports — all from inside Discord. Supports multiple teams, VP roles, collaborative tasks, and interactive buttons. Built with Python, discord.py, Supabase, and hosted on Railway.

## Command Reference

### Task Management

| Command | Who | Description |
| --- | --- | --- |
| `/assign @member "task" due:YYYY-MM-DD collaborators:@a @b` | Admin / VP | Assign a task. Due date and collaborators are optional. VPs can only assign within their team. |
| `/mytasks` | Anyone | See your own tasks: Pending, Awaiting Review, Recently Completed (last 5), and tasks you're collaborating on. |
| `/teamtasks @member(opt) team:name(opt)` | Anyone | See pending tasks for the team or a specific member. Anyone can filter by team name. VPs default to their team. |
| `/inprogress task_id` | Assignee | Mark one of your tasks as in progress. |
| `/done task_id` | Assignee / Collaborator | Submit a task for review. On collaborative tasks, waits until all collaborators submit before moving to review. |
| `/settaskstatus task_id status` | Assignee / Admin | Set a task to todo, in_progress, review, or done. |
| `/edittask task_id` | Assignee / Admin | Edit a task's name and/or due date. Use `none` to clear the due date. |
| `/deletetask task_id` | Admin / VP | Permanently delete a task. VPs can only delete tasks in their team. |
| `/alltasks` | Admin / VP | List every task, grouped by member. VPs see their team only. |

### Review & Approval

| Command | Who | Description |
| --- | --- | --- |
| `/approve task_id` | Admin / VP | Approve a task in review and mark it complete. VPs can only approve tasks in their team. |
| `/reject task_id reason` | Admin / VP | Send a task back with feedback. VPs can only reject tasks in their team. |
| `/reviewqueue` | Admin / VP | See all tasks waiting for approval. VPs see their team only. |

### VP Management

| Command | Who | Description |
| --- | --- | --- |
| `/setvp @member team` | Admin | Set a member as VP of a team (growth, tech, or operations). |
| `/removevp @member` | Admin | Remove a member's VP role. |
| `/listvps` | Admin | List all current VPs by team. |

### Team Roster

| Command | Who | Description |
| --- | --- | --- |
| `/addmember @member team` | Admin / VP | Add someone to the team roster. VPs auto-assign to their team; admins specify the team. |
| `/removemember @member` | Admin / VP | Remove someone from the roster (does not delete their tasks). VPs can only remove from their team. |
| `/teammembers team(opt)` | Admin / VP | List team members with pending, completed, and overdue counts. VPs see their team; admins can filter. |

### Reminders & Notifications

| Command | Who | Description |
| --- | --- | --- |
| `/setchannel @member #channel` | Admin / VP | Set a personal reminder channel for a member. VPs can only configure their team. |
| `/setteamchannel #channel team` | Admin / VP | Set the default reminder channel for an entire team. VPs can only set their own team's channel. |
| `/remind @member` | Admin / VP | Post a member's pending tasks in their reminder channel (or ephemerally if none set). |
| `/dmtasks @member(opt)` | Admin / VP | DM a member their tasks, or DM all team roster members at once. |
| `/pingteam` | Admin / VP | Post all pending tasks publicly. VPs scope to their team. |

### Progress & Utilities

| Command | Who | Description |
| --- | --- | --- |
| `/progress timeframe team(opt)` | Admin / VP | Progress report with completion rate, overdue tasks, and upcoming deadlines. VPs auto-scope to their team. |
| `/ping` | Anyone | Check if the bot is online. |

---

## Permission Levels

| Level | Who | Access |
| --- | --- | --- |
| **Admin** | Members with Manage Server | Full access to all commands and all teams |
| **VP** | Members set via `/setvp` | Admin-level access scoped to their assigned team only |
| **Member** | Everyone else | `/mytasks`, `/teamtasks`, `/done`, `/inprogress`, `/settaskstatus` (own tasks), `/edittask` (own tasks), `/ping` |

---

## Task Statuses

| Status | Meaning |
| --- | --- |
| 🔵 To Do | Task assigned, not started |
| 🟡 In Progress | Assignee is actively working on it |
| ⏳ In Review | Submitted by assignee, awaiting admin/VP approval |
| ✅ Done | Approved by admin or VP |

If a task is sent back via `/reject`, the feedback reason is shown under the task in all task lists.

---

## How Task Completion Works

### Single Assignee
1. Assignee uses `/inprogress task_id` when they start working
2. Assignee uses `/done task_id` when finished — task moves to **In Review**
3. Admin/VP receives a DM with Approve and Reject buttons
4. Admin/VP approves or rejects — assignee is DM'd the result

### Collaborative Tasks
1. Admin/VP assigns with `/assign @member "task" collaborators:@a @b`
2. Each collaborator uses `/done task_id` when their part is complete
3. The task moves to **In Review** only when **all** collaborators have submitted
4. Each `/done` call shows who is still pending until the last person submits
5. Admin/VP approves or rejects the whole task — all collaborators are notified

---

## Interactive Buttons

Task messages include Discord buttons so members and admins don't need to remember slash commands:

- **Assign message** → `🟡 Mark In Progress` and `⏳ Submit for Review` buttons for the assignee
- **Admin review DM** → `✅ Approve` and `↩️ Reject` buttons; Reject opens a modal to enter feedback

---

## Reminder Channel Priority

When the bot needs to notify a member, it checks in this order:
1. **Personal channel** — set via `/setchannel @member #channel`
2. **Team default channel** — set via `/setteamchannel #channel team`
3. **DM** — fallback if no channel is configured

---

## Automatic Reminders

The bot checks for upcoming deadlines every hour:
- **2 days before** the due date
- **Day of** the due date

Reminders go to the member's configured channel (personal or team default), or DM if none is set. Tasks in review are excluded.

---

## Dashboard Integration (Internal)

The bot exposes a `POST /notify` HTTP endpoint on port 8080 so the webapp can trigger task assignment notifications when tasks are created from the dashboard.

**Request:**
```
POST /notify
Authorization: Bearer <BOT_NOTIFY_SECRET>
Content-Type: application/json

{
  "guild_id": "...",
  "task_id": 123,
  "task_name": "Design sprint plan",
  "assignee_id": "...",
  "due_date": "2026-06-01",
  "team": "growth",
  "collaborator_ids": ["...", "..."]
}
```

**Response:**
```json
{ "notified": true, "method": "personal" }
```

`method` is `"personal"`, `"team"`, or `"dm"`. On failure: `{ "notified": false, "warning": "no_channel_and_dm_failed" }`.

---

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `DATABASE_URL` | Yes | Supabase PostgreSQL connection string |
| `BOT_NOTIFY_SECRET` | Yes | Bearer token for the `/notify` endpoint |
| `NOTIFY_PORT` | No | HTTP server port (default: 8080) |
