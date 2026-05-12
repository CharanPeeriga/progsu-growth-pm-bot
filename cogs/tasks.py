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
)

STATUS_EMOJI = {"todo": "🔵", "in_progress": "🟡", "done": "✅"}
STATUS_ORDER = {"todo": 0, "in_progress": 1, "done": 2}

STATUS_CHOICES = [
    app_commands.Choice(name="To Do", value="todo"),
    app_commands.Choice(name="In Progress", value="in_progress"),
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


def _build_dm_lines(tasks: list[dict]) -> list[str]:
    sorted_items = sorted(
        tasks,
        key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
    )
    lines = ["📋 growth-pm-bot — Your current tasks:", ""]
    for t in sorted_items:
        emoji = STATUS_EMOJI.get(t["status"], "🔵")
        lines.append(
            f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}"
        )
    lines.append("")
    lines.append("Use /done [id] to mark a task complete.")
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
                    f"Use /done {task_id} when complete."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="mytasks", description="List your pending tasks.")
    async def mytasks(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_tasks_by_user(interaction.guild.id, interaction.user.id)
            pending = _sort_pending(tasks)

            if not pending:
                await interaction.response.send_message(
                    "🎉 You have no pending tasks!", ephemeral=True
                )
                return

            lines = ["📋 Your Pending Tasks:"]
            for t in pending:
                emoji = STATUS_EMOJI.get(t["status"], "🔵")
                lines.append(
                    f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}"
                )

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
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

                lines = [f"📋 Pending tasks for **{member.display_name}**:"]
                for t in pending:
                    emoji = STATUS_EMOJI.get(t["status"], "🔵")
                    lines.append(
                        f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}"
                    )

                await interaction.response.send_message("\n".join(lines), ephemeral=True)
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
                guild_member = interaction.guild.get_member(int(assignee_id))
                if guild_member is not None:
                    display = guild_member.display_name
                else:
                    display = f"User {assignee_id}"

                section = [f"**{display}**"]
                for t in items:
                    emoji = STATUS_EMOJI.get(t["status"], "🔵")
                    section.append(
                        f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}"
                    )
                sections.append("\n".join(section))

            await interaction.response.send_message(
                "\n\n".join(sections), ephemeral=True
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="done", description="Mark a task as complete.")
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

            is_assignee = str(interaction.user.id) == task["assignee_id"]
            can_manage = interaction.user.guild_permissions.manage_guild
            if not (is_assignee or can_manage):
                await interaction.response.send_message(
                    "❌ You can only mark your own tasks as complete.", ephemeral=True
                )
                return

            update_task_status(task_id, "done")
            await interaction.response.send_message(
                f"✅ {interaction.user.mention} completed task #{task_id}: ~~{task['task_name']}~~"
            )

            assigner_id_int = int(task["assigner_id"])
            if assigner_id_int != interaction.user.id:
                try:
                    assigner = await self.bot.fetch_user(assigner_id_int)
                    await assigner.send(
                        "✅ Task completed — growth-pm-bot\n"
                        f"{interaction.user.display_name} completed their task:\n"
                        f"#{task_id}: {task['task_name']}\n"
                        f"Completed: {date.today().isoformat()}"
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
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
            if due is not None:
                if due.strip().lower() == "none":
                    db_due = CLEAR
                else:
                    try:
                        db_due = datetime.strptime(due.strip(), "%Y-%m-%d").date()
                    except ValueError:
                        await interaction.response.send_message(
                            "❌ Invalid date format. Please use YYYY-MM-DD (e.g. 2026-05-20)",
                            ephemeral=True,
                        )
                        return

            update_task(task_id, task_name=task_name, due_date=db_due)
            updated = get_task_by_id(task_id, interaction.guild.id)

            await interaction.response.send_message(
                f"✅ Task #{task_id} updated:\n"
                f"📋 Name: {updated['task_name']}\n"
                f"📅 Due: {_format_due(updated['due_date'])}",
                ephemeral=True,
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
                guild_member = interaction.guild.get_member(int(assignee_id))
                display = guild_member.display_name if guild_member else f"User {assignee_id}"

                sorted_items = sorted(
                    items,
                    key=lambda t: (
                        STATUS_ORDER.get(t["status"], 99),
                        t["due_date"] is None,
                        t["due_date"] or date.max,
                    ),
                )

                lines.append(f"**{display}**")
                for t in sorted_items:
                    emoji = STATUS_EMOJI.get(t["status"], "🔵")
                    lines.append(
                        f"{emoji} #{t['id']} — {t['task_name']} · "
                        f"Assigned to: {display} · Due: {_format_due(t['due_date'])}"
                    )
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

            await interaction.response.send_message(chunks[0], ephemeral=True)
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
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
            pending = sum(1 for t in tasks if t["status"] in ("todo", "in_progress"))
            overdue_tasks = [
                t for t in tasks
                if t["due_date"] is not None and t["due_date"] < today and t["status"] != "done"
            ]
            overdue = len(overdue_tasks)
            completion_rate = round((completed / total * 100), 1) if total else 0.0

            overview = (
                f"**Window:** {window_label}\n"
                f"Total tasks: **{total}**\n"
                f"✅ Completed: **{completed}**\n"
                f"🔵 Pending: **{pending}**\n"
                f"⚠️ Overdue: **{overdue}**\n"
                f"📈 Completion rate: **{completion_rate}%**"
            )

            per_person: dict[str, dict] = {}
            for t in tasks:
                entry = per_person.setdefault(
                    t["assignee_id"],
                    {"completed": 0, "pending": 0, "overdue": []},
                )
                if t["status"] == "done":
                    entry["completed"] += 1
                else:
                    entry["pending"] += 1
                    if t["due_date"] is not None and t["due_date"] < today:
                        entry["overdue"].append(t)

            person_lines: list[str] = []
            for assignee_id, entry in per_person.items():
                guild_member = interaction.guild.get_member(int(assignee_id))
                display = guild_member.display_name if guild_member else f"User {assignee_id}"

                line = (
                    f"**{display}** — ✅ {entry['completed']} · 🔵 {entry['pending']}"
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
                (t for t in tasks if t["status"] != "done" and t["due_date"] is not None),
                key=lambda t: t["due_date"],
            )[:5]

            if upcoming:
                upcoming_lines = []
                for t in upcoming:
                    guild_member = interaction.guild.get_member(int(t["assignee_id"]))
                    display = guild_member.display_name if guild_member else f"User {t['assignee_id']}"
                    upcoming_lines.append(
                        f"📅 {t['due_date'].isoformat()} — {t['task_name']} ({display})"
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

            await interaction.response.send_message(embed=embed, ephemeral=True)
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

            role = discord.utils.get(interaction.guild.roles, name="Growth")
            if role is None:
                await interaction.response.send_message(
                    "❌ No role named 'Growth' found in this server.", ephemeral=True
                )
                return

            all_tasks = get_all_tasks(interaction.guild.id)
            pending = _sort_pending(all_tasks)

            if not pending:
                await interaction.response.send_message(
                    "✅ No pending tasks right now!"
                )
                return

            grouped: dict[str, list[dict]] = {}
            for t in pending:
                grouped.setdefault(t["assignee_id"], []).append(t)

            sections: list[str] = []
            for assignee_id, items in grouped.items():
                guild_member = interaction.guild.get_member(int(assignee_id))
                display = guild_member.display_name if guild_member else f"User {assignee_id}"

                section = [display]
                for t in items:
                    emoji = STATUS_EMOJI.get(t["status"], "🔵")
                    section.append(
                        f"{emoji} #{t['id']} — {t['task_name']} · Due: {_format_due(t['due_date'])}"
                    )
                sections.append("\n".join(section))

            body = "\n\n".join(sections)
            message = f"{role.mention} — here are all current pending tasks:\n\n{body}"
            if len(message) > 1900:
                message = message[:1900] + "\n…(truncated)"

            await interaction.response.send_message(
                message,
                allowed_mentions=discord.AllowedMentions(roles=[role]),
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
                pending = [t for t in tasks if t["status"] != "done"]

                if not pending:
                    await interaction.response.send_message(
                        f"⚠️ {member.display_name} has no pending tasks.",
                        ephemeral=True,
                    )
                    return

                lines = _build_dm_lines(pending)
                try:
                    user = await self.bot.fetch_user(member.id)
                    await user.send("\n".join(lines))
                    await interaction.response.send_message(
                        f"✅ DMed {member.display_name} their pending tasks.",
                        ephemeral=True,
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        f"❌ Could not DM {member.display_name} — they may have "
                        f"DMs disabled or have blocked the bot.",
                        ephemeral=True,
                    )
                return

            all_tasks = get_all_tasks(interaction.guild.id)
            pending = [t for t in all_tasks if t["status"] != "done"]

            grouped: dict[str, list[dict]] = {}
            for t in pending:
                grouped.setdefault(t["assignee_id"], []).append(t)

            if not grouped:
                await interaction.response.send_message(
                    "✅ No pending tasks to deliver.", ephemeral=True
                )
                return

            successfully_dmed: list[str] = []
            failed_to_dm: list[str] = []

            for assignee_id, items in grouped.items():
                guild_member = interaction.guild.get_member(int(assignee_id))
                try:
                    user = await self.bot.fetch_user(int(assignee_id))
                    display = guild_member.display_name if guild_member else user.display_name
                except (discord.NotFound, discord.HTTPException):
                    display = guild_member.display_name if guild_member else f"User {assignee_id}"
                    failed_to_dm.append(display)
                    continue

                lines = _build_dm_lines(items)
                try:
                    await user.send("\n".join(lines))
                    successfully_dmed.append(display)
                except Exception:
                    failed_to_dm.append(display)

            if not successfully_dmed and failed_to_dm:
                reply = "❌ Could not reach any members. They may have DMs disabled."
            else:
                n = len(successfully_dmed)
                reply = f"✅ DMed {n} member(s) their pending tasks."
                if successfully_dmed:
                    reply += f"\n\n📨 Delivered: {', '.join(successfully_dmed)}"
                if failed_to_dm:
                    reply += (
                        f"\n\n❌ Could not reach ({len(failed_to_dm)}): "
                        f"{', '.join(failed_to_dm)}\n"
                        f"(These members may have DMs disabled or have blocked the bot.)"
                    )

            await interaction.response.send_message(reply, ephemeral=True)
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

            role = discord.utils.get(interaction.guild.roles, name="Growth")
            if role is None:
                role = await interaction.guild.create_role(
                    name="Growth",
                    mentionable=True,
                    reason="growth-pm-bot: creating Growth role",
                )

            if role in member.roles:
                await interaction.response.send_message(
                    f"⚠️ {member.display_name} is already a member of the Growth team.",
                    ephemeral=True,
                )
                return

            await member.add_roles(role, reason="growth-pm-bot: /addmember")

            await interaction.response.send_message(
                f"✅ {member.mention} has been added to the Growth team!"
            )

            try:
                await member.send(
                    f"👋 You've been added to the growth-pm-bot task system by "
                    f"{interaction.user.display_name}. You'll receive task assignments "
                    f"and deadline reminders here. Use /mytasks anytime to see your tasks."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
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
