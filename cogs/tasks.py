import traceback
from datetime import datetime, date, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    CLEAR,
    insert_task,
    get_tasks_by_user,
    get_all_tasks,
    get_task_by_id,
    update_task,
    update_task_status,
    delete_task,
    get_tasks_for_progress,
    set_reminder_channel,
    get_reminder_channel,
    get_tasks_in_review,
    approve_task,
    reject_task,
    add_team_member,
    remove_team_member,
    get_team_members,
    is_team_member,
)

STATUS_EMOJI = {"todo": "🔵", "in_progress": "🟡", "review": "⏳", "done": "✅"}
STATUS_ORDER = {"todo": 0, "in_progress": 1, "review": 2, "done": 3}

STATUS_CHOICES = [
    app_commands.Choice(name="To Do", value="todo"),
    app_commands.Choice(name="In Progress", value="in_progress"),
    app_commands.Choice(name="In Review", value="review"),
    app_commands.Choice(name="Done", value="done"),
]

TIMEFRAME_CHOICES = [
    app_commands.Choice(name="This Week", value="this_week"),
    app_commands.Choice(name="All Time", value="all_time"),
]

GENERIC_ERROR = (
    "⚠️ Something went wrong. Please try again or contact your server admin."
)


def _format_due(due: Optional[date]) -> str:
    return due.isoformat() if due else "No due date"


def _sort_pending(tasks: list[dict]) -> list[dict]:
    return sorted(
        (t for t in tasks if t["status"] != "done"),
        key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
    )


def _task_line(t: dict) -> str:
    emoji = STATUS_EMOJI.get(t["status"], "🔵")
    label = " (In Review)" if t["status"] == "review" else ""
    line = f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}{label}"
    if t.get("rejection_reason"):
        line += f"\n   ↩️ Sent back: {t['rejection_reason']}"
    return line


def _build_dm_lines(tasks: list[dict]) -> list[str]:
    sorted_items = sorted(
        tasks,
        key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
    )
    lines = ["📋 growth-pm-bot — Your current tasks:", ""]
    for t in sorted_items:
        lines.append(_task_line(t))
    lines.append("")
    lines.append("Use /done [id] to submit a task for review.")
    return lines


async def _send_generic_error(interaction: discord.Interaction) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(GENERIC_ERROR, ephemeral=True)
        else:
            await interaction.response.send_message(GENERIC_ERROR, ephemeral=True)
    except discord.HTTPException:
        traceback.print_exc()


class Tasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def notify_admin(
        self,
        interaction: discord.Interaction,
        command_name: str,
        details: str,
    ) -> None:
        if interaction.guild is None:
            return
        try:
            owner = await self.bot.fetch_user(interaction.guild.owner_id)
            await owner.send(
                f"📋 Command used — growth-pm-bot\n"
                f"Command: /{command_name}\n"
                f"Used by: {interaction.user.mention} ({interaction.user.name})\n"
                f"Server: {interaction.guild.name}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"Details: {details}"
            )
        except Exception:
            pass

    @app_commands.command(name="assign", description="Assign a task to a member.")
    @app_commands.describe(
        member="Member to assign the task to",
        task="Task description",
        due="Optional due date (YYYY-MM-DD)",
    )
    async def assign(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        task: str,
        due: Optional[str] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ Only admins can assign tasks.", ephemeral=True
                )
                return

            due_date: Optional[date] = None
            if due is not None and due.strip() != "":
                try:
                    due_date = datetime.strptime(due.strip(), "%Y-%m-%d").date()
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Invalid date format. Please use YYYY-MM-DD (e.g. 2026-05-20)",
                        ephemeral=True,
                    )
                    return

            task_id = insert_task(
                guild_id=interaction.guild.id,
                assignee_id=member.id,
                assigner_id=interaction.user.id,
                task_name=task,
                due_date=due_date,
            )

            due_str = _format_due(due_date)
            await interaction.response.send_message(
                f"✅ Task #{task_id} assigned to {member.mention}\n"
                f"📋 {task}\n"
                f"📅 Due: {due_str}"
            )

            try:
                await member.send(
                    f"📋 New task assigned by {interaction.user.display_name}\n"
                    f"Task #{task_id}: {task}\n"
                    f"Due: {due_str}\n"
                    f"Use /done {task_id} to submit for review when complete."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "assign",
                f"Assigned task #{task_id} '{task}' to {member.mention}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="mytasks", description="List your tasks.")
    async def mytasks(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_tasks_by_user(interaction.guild.id, interaction.user.id)
            if not tasks:
                await interaction.response.send_message(
                    "🎉 You have no tasks!", ephemeral=True
                )
                return

            pending = sorted(
                [t for t in tasks if t["status"] in ("todo", "in_progress")],
                key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
            )
            in_review = [t for t in tasks if t["status"] == "review"]
            done_tasks = sorted(
                [t for t in tasks if t["status"] == "done"],
                key=lambda t: t["id"],
                reverse=True,
            )[:5]

            lines: list[str] = []

            if pending:
                lines.append("📋 Your Pending Tasks:")
                for t in pending:
                    lines.append(_task_line(t))
                lines.append("")

            if in_review:
                lines.append("⏳ Awaiting Review:")
                for t in in_review:
                    lines.append(_task_line(t))
                lines.append("")

            if done_tasks:
                lines.append("✅ Recently Completed:")
                for t in done_tasks:
                    lines.append(_task_line(t))
                lines.append("")

            if not lines:
                await interaction.response.send_message(
                    "🎉 You have no tasks!", ephemeral=True
                )
                return

            await interaction.response.send_message(
                "\n".join(lines).strip(), ephemeral=True
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="teamtasks", description="List pending tasks for the team or a member.")
    @app_commands.describe(member="Optional: a specific member to filter by")
    async def teamtasks(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if member is not None:
                tasks = get_tasks_by_user(interaction.guild.id, member.id)
                pending = _sort_pending(tasks)

                if not pending:
                    await interaction.response.send_message(
                        "No pending tasks found.", ephemeral=True
                    )
                    return

                lines = [f"📋 Pending tasks for {member.mention}:"]
                for t in pending:
                    lines.append(_task_line(t))

                await interaction.response.send_message(
                    "\n".join(lines),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            all_tasks = get_all_tasks(interaction.guild.id)
            pending = _sort_pending(all_tasks)

            if not pending:
                await interaction.response.send_message(
                    "No pending tasks found.", ephemeral=True
                )
                return

            grouped: dict[str, list[dict]] = {}
            for t in pending:
                grouped.setdefault(t["assignee_id"], []).append(t)

            sections: list[str] = []
            for assignee_id, items in grouped.items():
                section = [f"**<@{assignee_id}>**"]
                for t in items:
                    section.append(_task_line(t))
                sections.append("\n".join(section))

            await interaction.response.send_message(
                "\n\n".join(sections),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="done", description="Submit a task for admin review.")
    @app_commands.describe(task_id="The task ID")
    async def done(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            if task["status"] == "review":
                await interaction.response.send_message(
                    f"⏳ Task #{task_id} is already submitted for review.", ephemeral=True
                )
                return

            if task["status"] == "done":
                await interaction.response.send_message(
                    f"✅ Task #{task_id} is already complete.", ephemeral=True
                )
                return

            if str(interaction.user.id) != task["assignee_id"]:
                await interaction.response.send_message(
                    "❌ You can only submit your own tasks.", ephemeral=True
                )
                return

            update_task_status(task_id, "review")
            await interaction.response.send_message(
                f"⏳ {interaction.user.mention} submitted task #{task_id} for review:\n"
                f"📋 {task['task_name']}\n"
                f"Waiting for admin approval."
            )

            try:
                owner = await self.bot.fetch_user(interaction.guild.owner_id)
                await owner.send(
                    f"📋 Task submitted for review — growth-pm-bot\n"
                    f"{interaction.user.mention} completed their task and submitted it for review:\n"
                    f"Task #{task_id}: {task['task_name']}\n"
                    f"Use /approve {task_id} to mark it done or "
                    f"/reject {task_id} [reason] to send it back."
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "done",
                f"{interaction.user.mention} submitted task #{task_id} for review: {task['task_name']}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="approve", description="Approve a reviewed task and mark it complete.")
    @app_commands.describe(task_id="The task ID")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def approve(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            if task["status"] != "review":
                await interaction.response.send_message(
                    f"⚠️ Task #{task_id} is not in review. Current status: {task['status']}",
                    ephemeral=True,
                )
                return

            approve_task(task_id)
            await interaction.response.send_message(
                f"✅ Task #{task_id} approved and marked complete:\n"
                f"📋 {task['task_name']}\n"
                f"Great work <@{task['assignee_id']}>!"
            )

            try:
                assignee = await self.bot.fetch_user(int(task["assignee_id"]))
                await assignee.send(
                    f"✅ Task approved — growth-pm-bot\n"
                    f"Your task has been reviewed and approved!\n"
                    f"Task #{task_id}: {task['task_name']}\n"
                    f"Great work!"
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "approve",
                f"Approved task #{task_id}: {task['task_name']} "
                f"(assigned to <@{task['assignee_id']}>)",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="reject", description="Send a task back to the assignee with feedback.")
    @app_commands.describe(task_id="The task ID", reason="Feedback for the member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reject(
        self,
        interaction: discord.Interaction,
        task_id: int,
        reason: str,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            if task["status"] != "review":
                await interaction.response.send_message(
                    f"⚠️ Task #{task_id} is not in review. Current status: {task['status']}",
                    ephemeral=True,
                )
                return

            reject_task(task_id, reason)
            await interaction.response.send_message(
                f"↩️ Task #{task_id} sent back to <@{task['assignee_id']}>:\n"
                f"📋 {task['task_name']}\n"
                f"Reason: {reason}"
            )

            try:
                assignee = await self.bot.fetch_user(int(task["assignee_id"]))
                await assignee.send(
                    f"↩️ Task sent back — growth-pm-bot\n"
                    f"Your task has been reviewed and needs more work:\n"
                    f"Task #{task_id}: {task['task_name']}\n"
                    f"Feedback: {reason}\n"
                    f"Update your work and resubmit with /done {task_id} when ready."
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "reject",
                f"Rejected task #{task_id}: {task['task_name']} — Reason: {reason}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="reviewqueue", description="See all tasks waiting for admin review.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reviewqueue(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_tasks_in_review(interaction.guild.id)
            if not tasks:
                await interaction.response.send_message(
                    "✅ No tasks waiting for review.", ephemeral=True
                )
                return

            lines = ["⏳ Tasks Awaiting Review:", ""]
            for t in tasks:
                lines.append(f"**#{t['id']} — {t['task_name']}**")
                lines.append(f"👤 Submitted by: <@{t['assignee_id']}>")
                lines.append(f"📅 Due: {_format_due(t['due_date'])}")
                lines.append(f"Use /approve {t['id']} or /reject {t['id']} [reason]")
                lines.append("")

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="settaskstatus", description="Set the status of a task.")
    @app_commands.describe(task_id="The task ID", status="New status")
    @app_commands.choices(status=STATUS_CHOICES)
    async def settaskstatus(
        self,
        interaction: discord.Interaction,
        task_id: int,
        status: app_commands.Choice[str],
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            is_assignee = str(interaction.user.id) == task["assignee_id"]
            can_manage = interaction.user.guild_permissions.manage_guild
            if not (is_assignee or can_manage):
                await interaction.response.send_message(
                    "❌ You can only update your own tasks.", ephemeral=True
                )
                return

            update_task_status(task_id, status.value)
            emoji = STATUS_EMOJI.get(status.value, "")
            await interaction.response.send_message(
                f"Updated task #{task_id} to {emoji} {status.value}", ephemeral=True
            )

            await self.notify_admin(
                interaction, "settaskstatus",
                f"Updated task #{task_id} status to {status.value}: {task['task_name']}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="edittask", description="Edit the name or due date of a task.")
    @app_commands.describe(
        task_id="The task ID",
        task_name="New task name (optional)",
        due="New due date YYYY-MM-DD, or 'none' to remove it (optional)",
    )
    async def edittask(
        self,
        interaction: discord.Interaction,
        task_id: int,
        task_name: Optional[str] = None,
        due: Optional[str] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if task_name is None and due is None:
                await interaction.response.send_message(
                    "❌ Please provide at least one field to update (task name or due date).",
                    ephemeral=True,
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            is_assignee = str(interaction.user.id) == task["assignee_id"]
            can_manage = interaction.user.guild_permissions.manage_guild
            if not (is_assignee or can_manage):
                await interaction.response.send_message(
                    "❌ You can only edit your own tasks.", ephemeral=True
                )
                return

            db_due = None
            changes: list[str] = []
            if due is not None:
                if due.strip().lower() == "none":
                    db_due = CLEAR
                    changes.append("due date cleared")
                else:
                    try:
                        db_due = datetime.strptime(due.strip(), "%Y-%m-%d").date()
                        changes.append(f"due → {db_due.isoformat()}")
                    except ValueError:
                        await interaction.response.send_message(
                            "❌ Invalid date format. Please use YYYY-MM-DD (e.g. 2026-05-20)",
                            ephemeral=True,
                        )
                        return

            if task_name is not None:
                changes.append(f"name → '{task_name}'")

            update_task(task_id, task_name=task_name, due_date=db_due)
            updated = get_task_by_id(task_id, interaction.guild.id)

            await interaction.response.send_message(
                f"✅ Task #{task_id} updated:\n"
                f"📋 Name: {updated['task_name']}\n"
                f"📅 Due: {_format_due(updated['due_date'])}",
                ephemeral=True,
            )

            await self.notify_admin(
                interaction, "edittask",
                f"Edited task #{task_id}: {', '.join(changes)}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="deletetask", description="Delete a task (Manage Server only).")
    @app_commands.describe(task_id="The task ID")
    async def deletetask(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You don't have permission to delete tasks.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            delete_task(task_id)
            await interaction.response.send_message(
                f"🗑️ Task #{task_id} deleted.", ephemeral=True
            )

            await self.notify_admin(
                interaction, "deletetask",
                f"Deleted task #{task_id}: {task['task_name']}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="alltasks", description="List every task in the server, grouped by member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alltasks(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_all_tasks(interaction.guild.id)
            if not tasks:
                await interaction.response.send_message(
                    "No tasks found.", ephemeral=True
                )
                return

            grouped: dict[str, list[dict]] = {}
            for t in tasks:
                grouped.setdefault(t["assignee_id"], []).append(t)

            lines: list[str] = []
            for assignee_id, items in grouped.items():
                sorted_items = sorted(
                    items,
                    key=lambda t: (
                        STATUS_ORDER.get(t["status"], 99),
                        t["due_date"] is None,
                        t["due_date"] or date.max,
                    ),
                )

                lines.append(f"**<@{assignee_id}>**")
                for t in sorted_items:
                    lines.append(_task_line(t))
                lines.append("")

            chunks: list[str] = []
            current = ""
            for line in lines:
                candidate = current + "\n" + line if current else line
                if len(candidate) > 1900:
                    chunks.append(current)
                    current = line
                else:
                    current = candidate
            if current:
                chunks.append(current)

            await interaction.response.send_message(
                chunks[0],
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            for chunk in chunks[1:]:
                await interaction.followup.send(
                    chunk,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="progress", description="Team progress snapshot for the weekly meeting.")
    @app_commands.describe(timeframe="Reporting window (defaults to This Week)")
    @app_commands.choices(timeframe=TIMEFRAME_CHOICES)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def progress(
        self,
        interaction: discord.Interaction,
        timeframe: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            window = timeframe.value if timeframe is not None else "this_week"
            if window == "this_week":
                since_date = date.today() - timedelta(days=7)
                tasks = get_tasks_for_progress(interaction.guild.id, since_date=since_date)
                window_label = "This Week"
            else:
                tasks = get_tasks_for_progress(interaction.guild.id)
                window_label = "All Time"

            today = date.today()

            total = len(tasks)
            completed = sum(1 for t in tasks if t["status"] == "done")
            in_review = sum(1 for t in tasks if t["status"] == "review")
            pending = sum(1 for t in tasks if t["status"] in ("todo", "in_progress"))
            overdue_tasks = [
                t for t in tasks
                if t["due_date"] is not None
                and t["due_date"] < today
                and t["status"] not in ("done", "review")
            ]
            overdue = len(overdue_tasks)
            completion_rate = round((completed / total * 100), 1) if total else 0.0

            overview = (
                f"**Window:** {window_label}\n"
                f"Total tasks: **{total}**\n"
                f"✅ Completed: **{completed}**\n"
                f"⏳ In Review: **{in_review}**\n"
                f"🔵 Pending: **{pending}**\n"
                f"⚠️ Overdue: **{overdue}**\n"
                f"📈 Completion rate: **{completion_rate}%**"
            )

            per_person: dict[str, dict] = {}
            for t in tasks:
                entry = per_person.setdefault(
                    t["assignee_id"],
                    {"completed": 0, "in_review": 0, "pending": 0, "overdue": []},
                )
                if t["status"] == "done":
                    entry["completed"] += 1
                elif t["status"] == "review":
                    entry["in_review"] += 1
                else:
                    entry["pending"] += 1
                    if t["due_date"] is not None and t["due_date"] < today:
                        entry["overdue"].append(t)

            person_lines: list[str] = []
            for assignee_id, entry in per_person.items():
                line = (
                    f"**<@{assignee_id}>** — "
                    f"✅ {entry['completed']} · "
                    f"⏳ {entry['in_review']} · "
                    f"🔵 {entry['pending']}"
                )
                if entry["overdue"]:
                    oldest = min(entry["overdue"], key=lambda t: t["due_date"])
                    line += (
                        f"\n   ⚠️ Oldest overdue: {oldest['task_name']} "
                        f"(due {oldest['due_date'].isoformat()})"
                    )
                person_lines.append(line)

            per_person_text = "\n".join(person_lines) if person_lines else "No tasks in this window."
            if len(per_person_text) > 1024:
                per_person_text = per_person_text[:1000].rsplit("\n", 1)[0] + "\n…(truncated)"

            upcoming = sorted(
                (
                    t for t in tasks
                    if t["status"] not in ("done", "review") and t["due_date"] is not None
                ),
                key=lambda t: t["due_date"],
            )[:5]

            if upcoming:
                upcoming_lines = []
                for t in upcoming:
                    upcoming_lines.append(
                        f"📅 {t['due_date'].isoformat()} — {t['task_name']} (<@{t['assignee_id']}>)"
                    )
                upcoming_text = "\n".join(upcoming_lines)
            else:
                upcoming_text = "No upcoming deadlines."

            embed = discord.Embed(
                title="📊 Growth Team Progress Report",
                color=0x5865F2,
            )
            embed.add_field(name="Team Overview", value=overview, inline=False)
            embed.add_field(name="Per Person", value=per_person_text, inline=False)
            embed.add_field(name="Coming Up", value=upcoming_text, inline=False)
            embed.set_footer(
                text=f"growth-pm-bot · Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="pingteam", description="Ping @Growth with all current pending tasks.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pingteam(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            all_tasks = get_all_tasks(interaction.guild.id)
            pending = _sort_pending(all_tasks)

            if not pending:
                await interaction.response.send_message(
                    "✅ No pending tasks right now!"
                )
                return

            team_rows = get_team_members(interaction.guild.id)
            team_ids = {row["user_id"] for row in team_rows}

            team_tasks: dict[str, list[dict]] = {}
            other_tasks: dict[str, list[dict]] = {}
            for t in pending:
                if t["assignee_id"] in team_ids:
                    team_tasks.setdefault(t["assignee_id"], []).append(t)
                else:
                    other_tasks.setdefault(t["assignee_id"], []).append(t)

            role = discord.utils.get(interaction.guild.roles, name="Growth")
            ping_prefix = f"{role.mention} — " if role else ""

            sections: list[str] = []
            for assignee_id, items in team_tasks.items():
                section = [f"<@{assignee_id}>"]
                for t in items:
                    section.append(_task_line(t))
                sections.append("\n".join(section))

            body = "\n\n".join(sections) if sections else "No pending tasks for team members."
            message = f"{ping_prefix}here are all current pending tasks:\n\n{body}"

            if other_tasks:
                other_sections: list[str] = []
                for assignee_id, items in other_tasks.items():
                    section = [f"<@{assignee_id}>"]
                    for t in items:
                        section.append(_task_line(t))
                    other_sections.append("\n".join(section))
                message += (
                    "\n\n📋 Other assigned tasks (not on official team roster):\n"
                    + "\n\n".join(other_sections)
                )

            if len(message) > 1900:
                message = message[:1900] + "\n…(truncated)"

            allowed = discord.AllowedMentions(roles=[role] if role else [], users=False)
            await interaction.response.send_message(message, allowed_mentions=allowed)

            await self.notify_admin(
                interaction, "pingteam",
                f"Pinged team with {len(pending)} pending task(s)",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="dmtasks", description="DM team member(s) their pending tasks.")
    @app_commands.describe(member="Optional: DM only this member")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def dmtasks(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if member is not None:
                tasks = get_tasks_by_user(interaction.guild.id, member.id)
                pending = [t for t in tasks if t["status"] not in ("done",)]

                if not pending:
                    await interaction.response.send_message(
                        f"⚠️ {member.mention} has no pending tasks.",
                        ephemeral=True,
                    )
                    return

                lines = _build_dm_lines(pending)
                try:
                    user = await self.bot.fetch_user(member.id)
                    await user.send("\n".join(lines))
                    await interaction.response.send_message(
                        f"✅ DMed {member.mention} their pending tasks.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
                    )
                    await self.notify_admin(
                        interaction, "dmtasks",
                        f"DMed {member.mention} their pending tasks ({len(pending)} tasks)",
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        f"❌ Could not DM {member.mention} — they may have "
                        f"DMs disabled or have blocked the bot.",
                        ephemeral=True,
                    )
                return

            # No-member mode: only DM registered team members
            team_rows = get_team_members(interaction.guild.id)
            if not team_rows:
                await interaction.response.send_message(
                    "⚠️ No team members found. Use /addmember to add members first.",
                    ephemeral=True,
                )
                return

            successfully_dmed: list[str] = []
            failed_to_dm: list[str] = []

            for row in team_rows:
                assignee_id = row["user_id"]
                tasks = get_tasks_by_user(interaction.guild.id, assignee_id)
                pending = [t for t in tasks if t["status"] not in ("done",)]

                if not pending:
                    continue

                try:
                    user = await self.bot.fetch_user(int(assignee_id))
                except (discord.NotFound, discord.HTTPException):
                    failed_to_dm.append(f"<@{assignee_id}>")
                    continue

                lines = _build_dm_lines(pending)
                try:
                    await user.send("\n".join(lines))
                    successfully_dmed.append(f"<@{assignee_id}>")
                except Exception:
                    failed_to_dm.append(f"<@{assignee_id}>")

            if not successfully_dmed and failed_to_dm:
                reply = "❌ Could not reach any members. They may have DMs disabled."
            elif not successfully_dmed:
                reply = "✅ No team members have pending tasks."
            else:
                n = len(successfully_dmed)
                reply = f"✅ DMed {n} team member(s) their pending tasks."
                reply += f"\n\n📨 Delivered: {', '.join(successfully_dmed)}"
                if failed_to_dm:
                    reply += (
                        f"\n\n❌ Could not reach ({len(failed_to_dm)}): "
                        f"{', '.join(failed_to_dm)}\n"
                        f"(These members may have DMs disabled or have blocked the bot.)"
                    )

            await interaction.response.send_message(
                reply,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )

            await self.notify_admin(
                interaction, "dmtasks",
                f"DMed {len(successfully_dmed)} team member(s) their tasks "
                f"({len(failed_to_dm)} failed)",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="addmember", description="Add a member to the Growth team.")
    @app_commands.describe(member="Member to add to the Growth team")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addmember(self, interaction: discord.Interaction, member: discord.Member):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if is_team_member(interaction.guild.id, member.id):
                await interaction.response.send_message(
                    f"⚠️ {member.mention} is already on the team.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            add_team_member(interaction.guild.id, member.id, member.display_name)
            await interaction.response.send_message(
                f"✅ {member.mention} has been added to the growth team!"
            )

            try:
                await member.send(
                    f"👋 You've been added to the growth-pm-bot task system by "
                    f"{interaction.user.display_name}. You'll receive task assignments "
                    f"and deadline reminders here. Use /mytasks anytime to see your tasks."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "addmember",
                f"Added {member.mention} to the Growth team",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="removemember", description="Remove a member from the Growth team.")
    @app_commands.describe(member="Member to remove from the Growth team")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removemember(self, interaction: discord.Interaction, member: discord.Member):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not is_team_member(interaction.guild.id, member.id):
                await interaction.response.send_message(
                    f"⚠️ {member.mention} is not on the team.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            remove_team_member(interaction.guild.id, member.id)
            await interaction.response.send_message(
                f"✅ {member.mention} has been removed from the growth team."
            )

            await self.notify_admin(
                interaction, "removemember",
                f"Removed {member.mention} from the Growth team",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="setchannel", description="Set the reminder channel for a member.")
    @app_commands.describe(
        member="Member to configure reminders for",
        channel="Channel to post reminders in",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setchannel(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        channel: discord.TextChannel,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            set_reminder_channel(interaction.guild.id, member.id, channel.id)
            await interaction.response.send_message(
                f"✅ Reminders for {member.mention} will be sent to {channel.mention}.",
                ephemeral=True,
            )

            await self.notify_admin(
                interaction, "setchannel",
                f"Set {member.mention}'s reminders to {channel.mention}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="remind", description="Remind a member of their pending tasks.")
    @app_commands.describe(member="Member to remind")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remind(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_tasks_by_user(interaction.guild.id, member.id)
            active_tasks = sorted(
                [t for t in tasks if t["status"] != "done"],
                key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
            )

            if not active_tasks:
                await interaction.response.send_message(
                    f"⚠️ {member.mention} has no pending tasks.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            lines = [f"📋 {member.mention} — here are your current pending tasks:", ""]
            for t in active_tasks:
                lines.append(_task_line(t))
            lines.append("")
            lines.append("Use /done [id] to submit a task for review.")

            channel_id, _ = get_reminder_channel(interaction.guild.id, str(member.id))
            if channel_id is not None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                    await channel.send(
                        "\n".join(lines),
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    await interaction.response.send_message(
                        f"✅ Posted reminder for {member.mention} in {channel.mention}.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
                    )
                except Exception:
                    await interaction.response.send_message(
                        "❌ Could not post in the configured reminder channel.",
                        ephemeral=True,
                    )
                    return
            else:
                lines.append(
                    "\n*(No reminder channel set — use /setchannel to assign one)*"
                )
                await interaction.response.send_message(
                    "\n".join(lines),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )

            await self.notify_admin(
                interaction, "remind",
                f"Sent task reminder to {member.mention} ({len(active_tasks)} active task(s))",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="teammembers", description="List all Growth team members and their task counts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def teammembers(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            team_rows = get_team_members(interaction.guild.id)
            if not team_rows:
                await interaction.response.send_message(
                    "No team members found. Use /addmember to add members.", ephemeral=True
                )
                return

            all_tasks = get_all_tasks(interaction.guild.id)
            today = date.today()

            counts: dict[str, dict] = {}
            for t in all_tasks:
                entry = counts.setdefault(
                    t["assignee_id"],
                    {"pending": 0, "completed": 0, "overdue": 0},
                )
                if t["status"] == "done":
                    entry["completed"] += 1
                else:
                    entry["pending"] += 1
                    if (
                        t["due_date"] is not None
                        and t["due_date"] < today
                        and t["status"] not in ("done", "review")
                    ):
                        entry["overdue"] += 1

            lines = [f"👥 Growth Team Members ({len(team_rows)} total):", ""]
            for row in team_rows:
                uid = row["user_id"]
                try:
                    user = await self.bot.fetch_user(int(uid))
                    display = user.display_name
                except Exception:
                    display = row.get("display_name") or f"<@{uid}>"

                entry = counts.get(uid, {"pending": 0, "completed": 0, "overdue": 0})
                line = (
                    f"• <@{uid}> ({display}) — "
                    f"{entry['pending']} pending, "
                    f"{entry['completed']} completed"
                )
                if entry["overdue"]:
                    line += f", ⚠️ {entry['overdue']} overdue"
                lines.append(line)

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="inprogress", description="Mark a task as in progress.")
    @app_commands.describe(task_id="The task ID")
    async def inprogress(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            if str(interaction.user.id) != task["assignee_id"]:
                await interaction.response.send_message(
                    "❌ You can only update your own tasks.", ephemeral=True
                )
                return

            if task["status"] == "in_progress":
                await interaction.response.send_message(
                    f"⚠️ Task #{task_id} is already in progress.", ephemeral=True
                )
                return

            update_task_status(task_id, "in_progress")
            await interaction.response.send_message(
                f"🟡 {interaction.user.mention} is now working on task #{task_id}: {task['task_name']}"
            )

            await self.notify_admin(
                interaction, "inprogress",
                f"{interaction.user.mention} started working on task #{task_id}: {task['task_name']}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="ping", description="Check if the bot is online.")
    async def ping(self, interaction: discord.Interaction):
        try:
            latency_ms = round(self.bot.latency * 1000)
            await interaction.response.send_message(
                f"🟢 growth-pm-bot is online! Latency: {latency_ms}ms",
                ephemeral=True,
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tasks(bot))
