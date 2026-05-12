from datetime import date, datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database

VALID_STATUSES = ("todo", "in_progress", "done")

STATUS_CHOICES = [
    app_commands.Choice(name="To Do", value="todo"),
    app_commands.Choice(name="In Progress", value="in_progress"),
    app_commands.Choice(name="Done", value="done"),
]


def _parse_due_date(value: Optional[str]) -> Optional[date]:
    if value is None or value.strip() == "":
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _format_task_line(task: dict) -> str:
    due = task["due_date"].isoformat() if task.get("due_date") else "no due date"
    return (
        f"`#{task['id']}` **{task['task_name']}** — "
        f"<@{task['assignee_id']}> • {task['status']} • {due}"
    )


class Tasks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="addtask", description="Assign a task to a member.")
    @app_commands.describe(
        assignee="Member to assign the task to",
        task_name="Short description of the task",
        due_date="Due date in YYYY-MM-DD format (optional)",
    )
    async def addtask(
        self,
        interaction: discord.Interaction,
        assignee: discord.Member,
        task_name: str,
        due_date: Optional[str] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        try:
            parsed_due = _parse_due_date(due_date)
        except ValueError:
            await interaction.response.send_message(
                "Invalid due_date. Use YYYY-MM-DD.", ephemeral=True
            )
            return

        task_id = database.insert_task(
            guild_id=interaction.guild.id,
            assignee_id=assignee.id,
            assigner_id=interaction.user.id,
            task_name=task_name,
            due_date=parsed_due,
        )

        due_str = parsed_due.isoformat() if parsed_due else "no due date"
        await interaction.response.send_message(
            f"✅ Created task `#{task_id}` for {assignee.mention}: "
            f"**{task_name}** (due: {due_str})"
        )

    @app_commands.command(name="mytasks", description="List your tasks in this server.")
    async def mytasks(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        tasks = database.get_tasks_by_user(interaction.guild.id, interaction.user.id)
        if not tasks:
            await interaction.response.send_message(
                "You have no tasks. 🎉", ephemeral=True
            )
            return

        lines = [_format_task_line(t) for t in tasks]
        await interaction.response.send_message(
            "**Your tasks:**\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="alltasks", description="List every task in this server.")
    async def alltasks(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        tasks = database.get_all_tasks(interaction.guild.id)
        if not tasks:
            await interaction.response.send_message("No tasks in this server yet.")
            return

        lines = [_format_task_line(t) for t in tasks]
        body = "\n".join(lines)
        if len(body) > 1900:
            body = body[:1900] + "\n…(truncated)"
        await interaction.response.send_message("**All tasks:**\n" + body)

    @app_commands.command(name="updatestatus", description="Update the status of a task.")
    @app_commands.describe(task_id="The task ID", status="New status")
    @app_commands.choices(status=STATUS_CHOICES)
    async def updatestatus(
        self,
        interaction: discord.Interaction,
        task_id: int,
        status: app_commands.Choice[str],
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        task = database.get_task_by_id(task_id, interaction.guild.id)
        if task is None:
            await interaction.response.send_message(
                f"Task `#{task_id}` not found in this server.", ephemeral=True
            )
            return

        database.update_task_status(task_id, status.value)
        await interaction.response.send_message(
            f"✅ Task `#{task_id}` set to **{status.value}**."
        )

    @app_commands.command(name="deletetask", description="Delete a task.")
    @app_commands.describe(task_id="The task ID")
    async def deletetask(self, interaction: discord.Interaction, task_id: int):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        task = database.get_task_by_id(task_id, interaction.guild.id)
        if task is None:
            await interaction.response.send_message(
                f"Task `#{task_id}` not found in this server.", ephemeral=True
            )
            return

        database.delete_task(task_id)
        await interaction.response.send_message(f"🗑️ Deleted task `#{task_id}`.")

    @app_commands.command(name="taskinfo", description="Show details for a single task.")
    @app_commands.describe(task_id="The task ID")
    async def taskinfo(self, interaction: discord.Interaction, task_id: int):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        task = database.get_task_by_id(task_id, interaction.guild.id)
        if task is None:
            await interaction.response.send_message(
                f"Task `#{task_id}` not found in this server.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Task #{task['id']}: {task['task_name']}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Assignee", value=f"<@{task['assignee_id']}>", inline=True)
        embed.add_field(name="Assigner", value=f"<@{task['assigner_id']}>", inline=True)
        embed.add_field(name="Status", value=task["status"], inline=True)
        embed.add_field(
            name="Due",
            value=task["due_date"].isoformat() if task["due_date"] else "—",
            inline=True,
        )
        embed.add_field(
            name="Created",
            value=task["created_at"].isoformat() if task["created_at"] else "—",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="progress", description="Summarize task progress for this server.")
    @app_commands.describe(days="Only count tasks created in the last N days (optional)")
    async def progress(
        self,
        interaction: discord.Interaction,
        days: Optional[int] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.", ephemeral=True
            )
            return

        since = None
        if days is not None:
            if days < 0:
                await interaction.response.send_message(
                    "`days` must be non-negative.", ephemeral=True
                )
                return
            since = datetime.utcnow() - timedelta(days=days)

        tasks = database.get_tasks_for_progress(interaction.guild.id, since_date=since)
        if not tasks:
            await interaction.response.send_message("No tasks in that window.")
            return

        totals = {"todo": 0, "in_progress": 0, "done": 0}
        for t in tasks:
            totals[t["status"]] = totals.get(t["status"], 0) + 1

        total = sum(totals.values())
        done_pct = (totals["done"] / total * 100) if total else 0.0
        window = f"last {days} days" if days is not None else "all time"

        embed = discord.Embed(
            title=f"Progress ({window})",
            color=discord.Color.green(),
        )
        embed.add_field(name="To Do", value=str(totals["todo"]), inline=True)
        embed.add_field(name="In Progress", value=str(totals["in_progress"]), inline=True)
        embed.add_field(name="Done", value=str(totals["done"]), inline=True)
        embed.add_field(name="Total", value=str(total), inline=True)
        embed.add_field(name="% Done", value=f"{done_pct:.1f}%", inline=True)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tasks(bot))
