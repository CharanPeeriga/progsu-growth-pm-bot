import re
import traceback
from datetime import datetime, date, timedelta
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands

from cogs.views import TaskActionView

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
    get_tasks_for_team,
    set_reminder_channel,
    get_reminder_channel,
    get_tasks_in_review,
    approve_task,
    reject_task,
    add_team_member,
    remove_team_member,
    get_team_members,
    is_team_member,
    set_vp,
    remove_vp,
    get_vp_roles,
    get_team_for_user,
    is_vp,
    get_all_vps,
    get_member_team,
    set_team_channel,
    get_team_channel,
    add_collaborator,
    get_collaborators,
    submit_collaborator,
    all_collaborators_submitted,
    get_pending_collaborators,
    get_tasks_as_collaborator,
    get_tasks_as_collaborator_for_user,
    get_all_task_collaborators,
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

TEAM_CHOICES = [
    app_commands.Choice(name="Growth", value="growth"),
    app_commands.Choice(name="Tech", value="tech"),
    app_commands.Choice(name="Operations", value="operations"),
    app_commands.Choice(name="Progirls", value="progirls"),
]

TEAMS = ("growth", "tech", "operations", "progirls")

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


def _task_block(t: dict, collabs: Optional[list[dict]] = None) -> str:
    """Task line plus optional collaborator status lines."""
    line = _task_line(t)
    if collabs:
        line += f"\n   👤 <@{t['assignee_id']}>"
        parts = []
        for c in collabs:
            status = "✅" if c["submitted"] else "⏳"
            parts.append(f"<@{c['user_id']}> {status}")
        line += f"\n   🤝 {' · '.join(parts)}"
    return line


def _build_dm_lines(tasks: list[dict]) -> list[str]:
    sorted_items = sorted(
        tasks,
        key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
    )
    lines = ["📋 progsu pm bot — Your current tasks:", ""]
    for t in sorted_items:
        lines.append(_task_line(t))
    lines.append("")
    lines.append("Use /done [id] to submit a task for review.")
    return lines


def _parse_user_ids(text: str) -> list[str]:
    """Extract user IDs from a string of Discord mentions like '<@123> <@!456>'."""
    return re.findall(r"<@!?(\d+)>", text)


# ---------------------------------------------------------------------------
# VP / team helper functions
# ---------------------------------------------------------------------------

def _get_team_ids_for_vp(guild_id, caller_team: list[str]) -> set[str]:
    """Returns the set of member user_ids across all of a VP's teams."""
    result: set[str] = set()
    for t in caller_team:
        result |= {r["user_id"] for r in get_team_members(guild_id, team=t)}
    return result


def _get_all_tasks_for_vp(guild_id, caller_team: list[str]) -> list[dict]:
    """Returns all tasks from all of a VP's teams, deduplicated and sorted."""
    if len(caller_team) == 1:
        return get_all_tasks(guild_id, team=caller_team[0])
    seen: dict[int, dict] = {}
    for t in caller_team:
        for task in get_all_tasks(guild_id, team=t):
            seen[task["id"]] = task
    return sorted(
        seen.values(),
        key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
    )


def _get_members_for_vp(guild_id, caller_team: list[str]) -> list[dict]:
    """Returns team_members rows across all of a VP's teams, deduplicated."""
    if len(caller_team) == 1:
        return get_team_members(guild_id, team=caller_team[0])
    seen: dict[str, dict] = {}
    for t in caller_team:
        for m in get_team_members(guild_id, team=t):
            seen[m["user_id"]] = m
    return list(seen.values())


async def _send_generic_error(interaction: discord.Interaction) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(GENERIC_ERROR, ephemeral=True)
        else:
            await interaction.response.send_message(GENERIC_ERROR, ephemeral=True)
    except discord.HTTPException:
        traceback.print_exc()


async def get_caller_team(
    interaction: discord.Interaction,
) -> Union[str, list[str]]:
    """
    Returns 'all' for admins, a list of team strings for VPs (may be multiple),
    or an empty list [] for regular members.
    """
    if interaction.guild is None:
        return []
    if interaction.user.guild_permissions.manage_guild:
        return "all"
    teams = get_team_for_user(str(interaction.guild.id), str(interaction.user.id))
    return teams  # list, empty if not a VP


async def require_admin_or_vp(interaction: discord.Interaction) -> bool:
    """Sends an error and returns False if the caller is not an admin or VP."""
    caller_team = await get_caller_team(interaction)
    if caller_team != "all" and not caller_team:
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True
        )
        return False
    return True


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
                f"📋 Command used — progsu pm bot\n"
                f"Command: /{command_name}\n"
                f"Used by: {interaction.user.mention} ({interaction.user.name})\n"
                f"Server: {interaction.guild.name}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"Details: {details}"
            )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # VP management
    # -----------------------------------------------------------------------

    @app_commands.command(name="setvp", description="Set a member as VP of a team.")
    @app_commands.describe(member="Member to make VP", team="Team they will VP")
    @app_commands.choices(team=TEAM_CHOICES)
    async def setvp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        team: app_commands.Choice[str],
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.", ephemeral=True
                )
                return

            set_vp(interaction.guild.id, member.id, team.value, interaction.user.id)
            await interaction.response.send_message(
                f"✅ {member.mention} is now VP of **{team.value}** team."
            )

            try:
                await member.send(
                    f"👑 You've been set as VP of the **{team.value}** team in "
                    f"{interaction.guild.name}.\n"
                    f"You now have admin-level access for your team's tasks and members."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "setvp",
                f"Set {member.mention} as VP of {team.value} team",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="removevp", description="Remove a member's VP role.")
    @app_commands.describe(
        member="Member to remove VP from",
        team="Specific team to remove (leave blank to remove all VP roles)",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def removevp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.", ephemeral=True
                )
                return

            roles = get_vp_roles(interaction.guild.id, member.id)
            if not roles:
                await interaction.response.send_message(
                    f"⚠️ {member.mention} is not a VP.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            if team is not None:
                # Remove from a specific team only
                matching = [r for r in roles if r["team"] == team.value]
                if not matching:
                    await interaction.response.send_message(
                        f"⚠️ {member.mention} is not VP of the **{team.value}** team.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
                    )
                    return
                from database import get_connection
                import psycopg2
                conn = get_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "DELETE FROM vp_roles WHERE guild_id = %s AND user_id = %s AND team = %s",
                            (str(interaction.guild.id), str(member.id), team.value),
                        )
                    conn.commit()
                finally:
                    conn.close()
                await interaction.response.send_message(
                    f"✅ {member.mention} has been removed as VP of **{team.value}**."
                )
            else:
                remove_vp(interaction.guild.id, member.id)
                await interaction.response.send_message(
                    f"✅ {member.mention} has been removed as VP."
                )

            await self.notify_admin(
                interaction, "removevp",
                f"Removed {member.mention} as VP"
                + (f" of {team.value}" if team else " (all teams)"),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="listvps", description="List all current VPs.")
    async def listvps(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.", ephemeral=True
                )
                return

            vps = get_all_vps(interaction.guild.id)

            by_team: dict[str, list[str]] = {}
            for row in vps:
                by_team.setdefault(row["team"], []).append(f"<@{row['user_id']}>")

            lines = ["👑 VPs:", ""]
            for team_value in ("growth", "tech", "operations", "progirls"):
                mentions = ", ".join(by_team.get(team_value, [])) or "*(none)*"
                lines.append(f"**{team_value.capitalize()}:** {mentions}")

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="setteamchannel", description="Set the default reminder channel for a team.")
    @app_commands.describe(
        channel="Channel to use as the default reminder channel",
        team="Team to set the channel for",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def setteamchannel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        team: app_commands.Choice[str],
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all" and team.value not in caller_team:
                await interaction.response.send_message(
                    "❌ You can only set channels for your own team.", ephemeral=True
                )
                return

            set_team_channel(interaction.guild.id, team.value, channel.id)
            await interaction.response.send_message(
                f"✅ Default reminder channel for **{team.value}** team set to {channel.mention}.\n"
                f"Members without a personal channel set will be notified here."
            )

            await self.notify_admin(
                interaction, "setteamchannel",
                f"Set {team.value} team reminder channel to {channel.mention}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    # -----------------------------------------------------------------------
    # Task assignment
    # -----------------------------------------------------------------------

    @app_commands.command(name="assign", description="Assign a task to a member.")
    @app_commands.describe(
        member="Member to assign the task to",
        task="Task description",
        due="Optional due date (YYYY-MM-DD)",
        collaborators="Optional: mention collaborators e.g. @user1 @user2",
        team="Team for the task (required if you are VP of multiple teams)",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def assign(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        task: str,
        due: Optional[str] = None,
        collaborators: Optional[str] = None,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team == "all":
                effective_team = team.value if team is not None else "growth"
            elif team is not None:
                if team.value not in caller_team:
                    await interaction.response.send_message(
                        "❌ You can only assign tasks within your own team.", ephemeral=True
                    )
                    return
                effective_team = team.value
            elif len(caller_team) > 1:
                await interaction.response.send_message(
                    "⚠️ You are VP of multiple teams. Please specify a team with the `team:` parameter.",
                    ephemeral=True,
                )
                return
            else:
                effective_team = caller_team[0]

            # BUG 3: when no explicit team: param, use the assignee's registered team
            assignee_team_warn = ""
            if team is None:
                assignee_db_team = get_member_team(
                    str(interaction.guild.id), str(member.id)
                )
                if assignee_db_team:
                    effective_team = assignee_db_team
                elif caller_team != "all":
                    assignee_team_warn = (
                        "\n*(Note: assignee not found in team roster — "
                        "task assigned to your team by default)*"
                    )

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
                team=effective_team,
            )

            collab_ids: list[str] = []
            if collaborators:
                collab_ids = _parse_user_ids(collaborators)
                for uid in collab_ids:
                    add_collaborator(task_id, uid)

            due_str = _format_due(due_date)
            member_view = TaskActionView(task_id, str(member.id), task, mode="member")

            if collab_ids:
                all_mentions = [member.mention] + [f"<@{uid}>" for uid in collab_ids]
                await interaction.response.send_message(
                    f"✅ Task #{task_id} assigned to {', '.join(all_mentions)}\n"
                    f"📋 {task}\n"
                    f"📅 Due: {due_str}"
                    + assignee_team_warn,
                    view=member_view,
                )
            else:
                await interaction.response.send_message(
                    f"✅ Task #{task_id} assigned to {member.mention}\n"
                    f"📋 {task}\n"
                    f"📅 Due: {due_str}"
                    + assignee_team_warn,
                    view=member_view,
                )

            if collab_ids:
                # Everyone (assignee + collaborators) gets the same DM format
                all_participant_ids = [str(member.id)] + collab_ids
                for uid in all_participant_ids:
                    other_ids = [u for u in all_participant_ids if u != uid]
                    other_mentions = ", ".join(f"<@{u}>" for u in other_ids)
                    dm_msg = (
                        f"📋 New task assigned by {interaction.user.display_name}\n"
                        f"Task #{task_id}: {task}\n"
                        f"Due: {due_str}\n"
                        f"Others working on this: {other_mentions}\n"
                        f"Use /done {task_id} when your part is complete."
                    )
                    try:
                        user = await self.bot.fetch_user(int(uid))
                        await user.send(dm_msg)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
            else:
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
                f"Assigned task #{task_id} '{task}' to {member.mention} [{effective_team} team]"
                + (f" with {len(collab_ids)} collaborator(s)" if collab_ids else ""),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    # -----------------------------------------------------------------------
    # Member-facing task commands
    # -----------------------------------------------------------------------

    @app_commands.command(name="mytasks", description="List your tasks.")
    async def mytasks(self, interaction: discord.Interaction):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            tasks = get_tasks_by_user(interaction.guild.id, interaction.user.id)
            collab_tasks = get_tasks_as_collaborator(
                interaction.guild.id, interaction.user.id
            )

            if not tasks and not collab_tasks:
                await interaction.response.send_message(
                    "🎉 You have no tasks!", ephemeral=True
                )
                return

            # Collab tasks not already appearing as assigned tasks
            assigned_ids = {t["id"] for t in tasks}
            collab_by_id = {
                ct["id"]: ct for ct in collab_tasks if ct["id"] not in assigned_ids
            }

            # Build merged sections
            all_pending = sorted(
                [t for t in tasks if t["status"] in ("todo", "in_progress")]
                + [ct for ct in collab_by_id.values() if ct["status"] in ("todo", "in_progress")],
                key=lambda t: (t["due_date"] is None, t["due_date"] or date.max),
            )
            all_review = (
                [t for t in tasks if t["status"] == "review"]
                + [ct for ct in collab_by_id.values() if ct["status"] == "review"]
            )
            all_done = sorted(
                [t for t in tasks if t["status"] == "done"]
                + [ct for ct in collab_by_id.values() if ct["status"] == "done"],
                key=lambda t: t["id"],
                reverse=True,
            )[:5]

            lines: list[str] = []

            if all_pending:
                lines.append("📋 Your Pending Tasks:")
                for t in all_pending:
                    if t["id"] in collab_by_id:
                        submitted = collab_by_id[t["id"]].get("submitted", False)
                        if submitted:
                            line = (
                                f"⏳ #{t['id']} — {t['task_name']} "
                                f"· Due: {_format_due(t['due_date'])} · 🤝 waiting on others"
                            )
                        else:
                            emoji = STATUS_EMOJI.get(t["status"], "🔵")
                            line = (
                                f"{emoji} #{t['id']} — {t['task_name']} "
                                f"· Due: {_format_due(t['due_date'])} · 🤝 team task"
                            )
                        if t.get("rejection_reason"):
                            line += f"\n   ↩️ Sent back: {t['rejection_reason']}"
                        lines.append(line)
                    else:
                        lines.append(_task_line(t))
                lines.append("")

            if all_review:
                lines.append("⏳ Awaiting Review:")
                for t in all_review:
                    lines.append(_task_line(t))
                lines.append("")

            if all_done:
                lines.append("✅ Recently Completed:")
                for t in all_done:
                    lines.append(_task_line(t))
                lines.append("")

            if not lines:
                await interaction.response.send_message(
                    "🎉 You have no tasks!", ephemeral=True
                )
                return

            await interaction.response.send_message(
                "\n".join(lines).strip(),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="teamtasks", description="List pending tasks for the team or a member.")
    @app_commands.describe(
        member="Optional: filter by specific member",
        team="Optional: filter by team (visible to all)",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def teamtasks(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            caller_team = await get_caller_team(interaction)
            collab_map = get_all_task_collaborators(interaction.guild.id)

            # Determine task source
            if team is not None:
                # Explicit team param wins for everyone
                effective_team: Optional[str] = team.value
                use_vp_multi = False
            elif caller_team == "all" or not caller_team:
                effective_team = None
                use_vp_multi = False
            elif len(caller_team) == 1:
                effective_team = caller_team[0]
                use_vp_multi = False
            else:
                # Multi-team VP, no explicit param — show all their teams
                effective_team = None
                use_vp_multi = True

            if member is not None:
                if use_vp_multi:
                    assigned_list: list[dict] = []
                    collab_list: list[dict] = []
                    for t in caller_team:
                        assigned_list.extend(
                            get_tasks_by_user(interaction.guild.id, member.id, team=t)
                        )
                        collab_list.extend(
                            get_tasks_as_collaborator_for_user(
                                interaction.guild.id, member.id, team=t
                            )
                        )
                else:
                    assigned_list = get_tasks_by_user(
                        interaction.guild.id, member.id, team=effective_team
                    )
                    collab_list = get_tasks_as_collaborator_for_user(
                        interaction.guild.id, member.id, team=effective_team
                    )

                seen_assigned: dict[int, dict] = {t["id"]: t for t in assigned_list}
                seen_collab: dict[int, dict] = {t["id"]: t for t in collab_list}
                collab_only_ids: set[int] = set(seen_collab) - set(seen_assigned)
                merged: dict[int, dict] = {**seen_collab, **seen_assigned}
                pending = _sort_pending(merged.values())

                if not pending:
                    await interaction.response.send_message(
                        "No pending tasks found.", ephemeral=True
                    )
                    return

                lines = [f"📋 Pending tasks for {member.mention}:"]
                for t in pending:
                    if t["id"] in collab_only_ids:
                        emoji = STATUS_EMOJI.get(t["status"], "🔵")
                        task_collabs = collab_map.get(t["id"], [])
                        n_others = len(task_collabs)
                        line = (
                            f"{emoji} #{t['id']} — {t['task_name']} "
                            f"· Due: {_format_due(t['due_date'])} "
                            f"· 🤝 <@{t['assignee_id']}>"
                            + (f" + {n_others} other(s)" if n_others > 0 else "")
                        )
                        if t.get("rejection_reason"):
                            line += f"\n   ↩️ Sent back: {t['rejection_reason']}"
                        lines.append(line)
                    else:
                        lines.append(_task_block(t, collab_map.get(t["id"])))

                await interaction.response.send_message(
                    "\n".join(lines),
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            if use_vp_multi:
                all_tasks = _get_all_tasks_for_vp(interaction.guild.id, caller_team)
            else:
                all_tasks = get_all_tasks(interaction.guild.id, team=effective_team)
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
                    section.append(_task_block(t, collab_map.get(t["id"])))
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

            collabs = get_collaborators(task_id)
            collab_ids = [c["user_id"] for c in collabs]
            is_collab = str(interaction.user.id) in collab_ids
            is_assignee = str(interaction.user.id) == task["assignee_id"]

            if not (is_assignee or is_collab):
                await interaction.response.send_message(
                    "❌ You are not assigned to this task.", ephemeral=True
                )
                return

            if collabs:
                if is_collab:
                    # Check if user already submitted their part
                    user_collab = next(
                        (c for c in collabs if c["user_id"] == str(interaction.user.id)),
                        None,
                    )
                    if user_collab and user_collab["submitted"]:
                        remaining = get_pending_collaborators(task_id)
                        await interaction.response.send_message(
                            f"⏳ You already submitted your part of task #{task_id}.\n"
                            f"Waiting on {len(remaining)} more person(s) before it goes to review.",
                            ephemeral=True,
                        )
                        return
                    submit_collaborator(task_id, interaction.user.id)

                if all_collaborators_submitted(task_id):
                    update_task_status(task_id, "review")
                    await interaction.response.send_message(
                        f"✅ Task #{task_id} submitted for review — all members complete.\n"
                        f"📋 {task['task_name']}\n"
                        f"Waiting for admin approval."
                    )
                    for c in collabs:
                        try:
                            cu = await self.bot.fetch_user(int(c["user_id"]))
                            await cu.send(
                                f"✅ All parts submitted for task #{task_id}: "
                                f"{task['task_name']}\n"
                                f"It is now in the admin review queue."
                            )
                        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                            pass
                    try:
                        owner = await self.bot.fetch_user(interaction.guild.owner_id)
                        await owner.send(
                            f"📋 Task submitted for review — progsu pm bot\n"
                            f"All collaborators completed task #{task_id}: "
                            f"{task['task_name']}\n"
                            f"Use the buttons below or /approve {task_id} / "
                            f"/reject {task_id} [reason].",
                            view=TaskActionView(
                                task_id, task["assignee_id"], task["task_name"], mode="review"
                            ),
                        )
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
                    await self.notify_admin(
                        interaction, "done",
                        f"All collaborators submitted task #{task_id}: {task['task_name']}",
                    )
                else:
                    remaining = get_pending_collaborators(task_id)
                    await interaction.response.send_message(
                        f"✅ Marked as done on your end.\n"
                        f"Task #{task_id} is waiting on {len(remaining)} more person(s) "
                        f"before going to review.",
                        ephemeral=True,
                    )
            else:
                update_task_status(task_id, "review")
                await interaction.response.send_message(
                    f"⏳ {interaction.user.mention} submitted task #{task_id} for review:\n"
                    f"📋 {task['task_name']}\n"
                    f"Waiting for admin approval."
                )
                try:
                    owner = await self.bot.fetch_user(interaction.guild.owner_id)
                    await owner.send(
                        f"📋 Task submitted for review — progsu pm bot\n"
                        f"{interaction.user.mention} completed their task and submitted it "
                        f"for review:\n"
                        f"Task #{task_id}: {task['task_name']}\n"
                        f"Use the buttons below or /approve {task_id} / "
                        f"/reject {task_id} [reason].",
                        view=TaskActionView(
                            task_id, task["assignee_id"], task["task_name"], mode="review"
                        ),
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                await self.notify_admin(
                    interaction, "done",
                    f"{interaction.user.mention} submitted task #{task_id} for review: "
                    f"{task['task_name']}",
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

            if task["status"] != "todo":
                await interaction.response.send_message(
                    f"⚠️ Task #{task_id} cannot be moved to in progress "
                    f"— current status: {task['status']}.",
                    ephemeral=True,
                )
                return

            update_task_status(task_id, "in_progress")
            await interaction.response.send_message(
                f"🟡 {interaction.user.mention} is now working on task "
                f"#{task_id}: {task['task_name']}"
            )

            await self.notify_admin(
                interaction, "inprogress",
                f"{interaction.user.mention} started working on task #{task_id}: "
                f"{task['task_name']}",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    # -----------------------------------------------------------------------
    # Review / approval
    # -----------------------------------------------------------------------

    @app_commands.command(name="approve", description="Approve a reviewed task and mark it complete.")
    @app_commands.describe(task_id="The task ID")
    async def approve(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if task["assignee_id"] not in team_ids:
                    await interaction.response.send_message(
                        f"❌ Task #{task_id} is not in your team.", ephemeral=True
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
                    f"✅ Task approved — progsu pm bot\n"
                    f"Your task has been reviewed and approved!\n"
                    f"Task #{task_id}: {task['task_name']}\n"
                    f"Great work!"
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            for c in get_collaborators(task_id):
                if c["user_id"] == task["assignee_id"]:
                    continue
                try:
                    cu = await self.bot.fetch_user(int(c["user_id"]))
                    await cu.send(
                        f"✅ Task approved — progsu pm bot\n"
                        f"Task #{task_id}: {task['task_name']} was approved.\n"
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

            if not await require_admin_or_vp(interaction):
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if task["assignee_id"] not in team_ids:
                    await interaction.response.send_message(
                        f"❌ Task #{task_id} is not in your team.", ephemeral=True
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
                    f"↩️ Task sent back — progsu pm bot\n"
                    f"Your task has been reviewed and needs more work:\n"
                    f"Task #{task_id}: {task['task_name']}\n"
                    f"Feedback: {reason}\n"
                    f"Please update your work and set a new due date if needed:\n"
                    f"→ Update due date: /edittask {task_id} due:YYYY-MM-DD\n"
                    f"→ Resubmit when ready: /done {task_id}"
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            for c in get_collaborators(task_id):
                if c["user_id"] == task["assignee_id"]:
                    continue
                try:
                    cu = await self.bot.fetch_user(int(c["user_id"]))
                    await cu.send(
                        f"↩️ Task sent back — progsu pm bot\n"
                        f"Task #{task_id}: {task['task_name']}\n"
                        f"Feedback: {reason}\n"
                        f"Please update your work and set a new due date if needed:\n"
                        f"→ Update due date: /edittask {task_id} due:YYYY-MM-DD\n"
                        f"→ Resubmit when ready: /done {task_id}"
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

    @app_commands.command(name="reviewqueue", description="See all tasks waiting for review.")
    @app_commands.describe(team="Optional: filter to a specific team")
    @app_commands.choices(team=TEAM_CHOICES)
    async def reviewqueue(
        self,
        interaction: discord.Interaction,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)

            # Fetch all review tasks within the caller's scope
            if caller_team != "all":
                scoped = _get_all_tasks_for_vp(interaction.guild.id, caller_team)
                all_tasks = [t for t in scoped if t["status"] == "review"]
                all_tasks.sort(key=lambda t: t["created_at"])
            else:
                all_tasks = get_tasks_in_review(interaction.guild.id)

            # Apply explicit team filter
            if team is not None:
                all_tasks = [t for t in all_tasks if t.get("team") == team.value]

            if not all_tasks:
                await interaction.response.send_message(
                    "✅ No tasks waiting for review.", ephemeral=True
                )
                return

            # Determine display order of teams
            if team is not None:
                teams_to_show = [team.value]
            elif caller_team == "all":
                teams_to_show = list(TEAMS)
            else:
                teams_to_show = list(caller_team)

            lines = ["⏳ Tasks Awaiting Review:", ""]
            for team_name in teams_to_show:
                bucket = [t for t in all_tasks if t.get("team") == team_name]
                if not bucket:
                    continue
                lines.append(f"**── {team_name.capitalize()} ──**")
                for t in bucket:
                    lines.append(f"**#{t['id']} — {t['task_name']}**")
                    lines.append(f"👤 Submitted by: <@{t['assignee_id']}>")
                    lines.append(f"📅 Due: {_format_due(t['due_date'])}")
                    lines.append(f"Use /approve {t['id']} or /reject {t['id']} [reason]")
                    lines.append("")
                lines.append("")

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    # -----------------------------------------------------------------------
    # Task editing
    # -----------------------------------------------------------------------

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

    @app_commands.command(name="deletetask", description="Delete a task.")
    @app_commands.describe(task_id="The task ID")
    async def deletetask(self, interaction: discord.Interaction, task_id: int):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            task = get_task_by_id(task_id, interaction.guild.id)
            if task is None:
                await interaction.response.send_message(
                    f"❌ Task #{task_id} not found.", ephemeral=True
                )
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if task["assignee_id"] not in team_ids:
                    await interaction.response.send_message(
                        f"❌ Task #{task_id} is not in your team.", ephemeral=True
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

    # -----------------------------------------------------------------------
    # Admin / VP task views
    # -----------------------------------------------------------------------

    @app_commands.command(name="alltasks", description="List every task, grouped by team and member.")
    @app_commands.describe(team="Optional: filter to a specific team")
    @app_commands.choices(team=TEAM_CHOICES)
    async def alltasks(
        self,
        interaction: discord.Interaction,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            collab_map = get_all_task_collaborators(interaction.guild.id)

            # Determine which teams to display
            if team is not None:
                teams_to_show = [team.value]
            elif caller_team == "all":
                teams_to_show = list(TEAMS)
            else:
                teams_to_show = list(caller_team)

            lines: list[str] = []
            for team_name in teams_to_show:
                team_tasks = get_all_tasks(interaction.guild.id, team=team_name)
                if not team_tasks:
                    continue
                lines.append(f"**── {team_name.capitalize()} ──**")
                grouped: dict[str, list[dict]] = {}
                for t in team_tasks:
                    grouped.setdefault(t["assignee_id"], []).append(t)
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
                        lines.append(_task_block(t, collab_map.get(t["id"])))
                    lines.append("")
                lines.append("")

            if not lines:
                await interaction.response.send_message(
                    "No tasks found.", ephemeral=True
                )
                return

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

    @app_commands.command(name="progress", description="Team progress snapshot.")
    @app_commands.describe(
        timeframe="Reporting window (defaults to This Week)",
        team="Filter by team (required if you are VP of multiple teams)",
    )
    @app_commands.choices(timeframe=TIMEFRAME_CHOICES, team=TEAM_CHOICES)
    async def progress(
        self,
        interaction: discord.Interaction,
        timeframe: Optional[app_commands.Choice[str]] = None,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            window = timeframe.value if timeframe is not None else "this_week"
            window_label = "This Week" if window == "this_week" else "All Time"
            since_date = date.today() - timedelta(days=7) if window == "this_week" else None

            # Resolve effective team
            if caller_team == "all":
                effective_team = team.value if team is not None else None
            elif team is not None:
                if team.value not in caller_team:
                    await interaction.response.send_message(
                        "❌ You can only view progress for your own team.", ephemeral=True
                    )
                    return
                effective_team = team.value
            elif len(caller_team) > 1:
                await interaction.response.send_message(
                    "⚠️ You are VP of multiple teams. Please specify a team with the `team:` parameter.",
                    ephemeral=True,
                )
                return
            else:
                effective_team = caller_team[0]

            if effective_team is not None:
                all_team_tasks = get_tasks_for_team(interaction.guild.id, effective_team)
                tasks = (
                    [t for t in all_team_tasks if t["created_at"].date() >= since_date]
                    if since_date else all_team_tasks
                )
            else:
                tasks = get_tasks_for_progress(
                    interaction.guild.id, since_date=since_date
                )

            team_label = f" — {effective_team.capitalize()} Team" if effective_team else ""
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
            completion_rate = round((completed / total * 100), 1) if total else 0.0

            overview = (
                f"**Window:** {window_label}\n"
                f"Total tasks: **{total}**\n"
                f"✅ Completed: **{completed}**\n"
                f"⏳ In Review: **{in_review}**\n"
                f"🔵 Pending: **{pending}**\n"
                f"⚠️ Overdue: **{len(overdue_tasks)}**\n"
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

            upcoming_text = (
                "\n".join(
                    f"📅 {t['due_date'].isoformat()} — {t['task_name']} (<@{t['assignee_id']}>)"
                    for t in upcoming
                )
                if upcoming else "No upcoming deadlines."
            )

            embed = discord.Embed(
                title=f"📊 Progress Report{team_label}",
                color=0x5865F2,
            )
            embed.add_field(name="Team Overview", value=overview, inline=False)
            embed.add_field(name="Per Person", value=per_person_text, inline=False)
            embed.add_field(name="Coming Up", value=upcoming_text, inline=False)
            embed.set_footer(
                text=f"progsu pm bot · Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="pingteam", description="Post all current pending tasks publicly.")
    @app_commands.describe(team="Optional: filter to a specific team")
    @app_commands.choices(team=TEAM_CHOICES)
    async def pingteam(
        self,
        interaction: discord.Interaction,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)

            if team is not None:
                all_tasks = get_all_tasks(interaction.guild.id, team=team.value)
                roster = get_team_members(interaction.guild.id, team=team.value)
            elif caller_team == "all":
                all_tasks = get_all_tasks(interaction.guild.id)
                roster = get_team_members(interaction.guild.id)
            else:
                all_tasks = _get_all_tasks_for_vp(interaction.guild.id, caller_team)
                roster = _get_members_for_vp(interaction.guild.id, caller_team)

            pending = _sort_pending(all_tasks)

            if not pending:
                await interaction.response.send_message("✅ No pending tasks right now!")
                return

            team_ids = {row["user_id"] for row in roster}
            collab_map = get_all_task_collaborators(interaction.guild.id)

            team_tasks: dict[str, list[dict]] = {}
            other_tasks: dict[str, list[dict]] = {}
            for t in pending:
                if t["assignee_id"] in team_ids:
                    team_tasks.setdefault(t["assignee_id"], []).append(t)
                else:
                    other_tasks.setdefault(t["assignee_id"], []).append(t)

            # Determine role to ping
            team_name_for_role = (
                team.value if team is not None
                else (caller_team[0] if isinstance(caller_team, list) and len(caller_team) == 1 else None)
            )
            role = discord.utils.get(
                interaction.guild.roles,
                name=team_name_for_role.capitalize() if team_name_for_role else "Growth",
            )
            ping_prefix = f"{role.mention} — " if role else ""

            # Build output lines (chunk at assignee boundaries)
            lines: list[str] = [f"{ping_prefix}here are all current pending tasks:", ""]
            for assignee_id, items in team_tasks.items():
                lines.append(f"<@{assignee_id}>")
                for t in items:
                    lines.append(_task_block(t, collab_map.get(t["id"])))
                lines.append("")

            if other_tasks and team is None and caller_team == "all":
                lines.append("📋 Other assigned tasks (not on official team roster):")
                lines.append("")
                for assignee_id, items in other_tasks.items():
                    lines.append(f"<@{assignee_id}>")
                    for t in items:
                        lines.append(_task_block(t, collab_map.get(t["id"])))
                    lines.append("")

            # Split into chunks ≤1900 chars at line boundaries
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

            allowed = discord.AllowedMentions(roles=[role] if role else [], users=False)
            await interaction.response.send_message(chunks[0], allowed_mentions=allowed)
            for chunk in chunks[1:]:
                await interaction.followup.send(
                    chunk,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )

            await self.notify_admin(
                interaction, "pingteam",
                f"Pinged team with {len(pending)} pending task(s)",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="dmtasks", description="DM team member(s) their pending tasks.")
    @app_commands.describe(
        member="Optional: DM only this member",
        team="Optional: limit to a specific team",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def dmtasks(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)

            if member is not None:
                if caller_team != "all":
                    team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                    if str(member.id) not in team_ids:
                        await interaction.response.send_message(
                            f"❌ {member.mention} is not in your team.",
                            ephemeral=True,
                            allowed_mentions=discord.AllowedMentions(users=False),
                        )
                        return

                tasks = get_tasks_by_user(interaction.guild.id, member.id)
                pending = [t for t in tasks if t["status"] not in ("done",)]

                if not pending:
                    await interaction.response.send_message(
                        f"⚠️ {member.mention} has no pending tasks.", ephemeral=True
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

            # Determine team scope and which team channel to post to
            if team is not None:
                team_rows = get_team_members(interaction.guild.id, team=team.value)
                dm_team: Optional[str] = team.value
            elif caller_team == "all":
                team_rows = get_team_members(interaction.guild.id)
                dm_team = None  # admin with no filter — skip channel post
            else:
                team_rows = _get_members_for_vp(interaction.guild.id, caller_team)
                dm_team = caller_team[0] if len(caller_team) == 1 else None

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
                reply = f"✅ DMed {len(successfully_dmed)} team member(s) their pending tasks."
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

            # FIX 9: Post summary to team channel when a specific team is targeted
            if dm_team and successfully_dmed:
                channel_id = get_team_channel(str(interaction.guild.id), dm_team)
                if channel_id:
                    ch = self.bot.get_channel(int(channel_id))
                    if ch:
                        summary = (
                            f"📣 Task reminders sent to {len(successfully_dmed)} member(s).\n"
                            f"Delivered: {', '.join(successfully_dmed)}"
                        )
                        if failed_to_dm:
                            summary += f"\nCould not reach: {', '.join(failed_to_dm)}"
                        try:
                            await ch.send(
                                summary,
                                allowed_mentions=discord.AllowedMentions(users=False),
                            )
                        except Exception:
                            pass

            await self.notify_admin(
                interaction, "dmtasks",
                f"DMed {len(successfully_dmed)} team member(s) their tasks "
                f"({len(failed_to_dm)} failed)",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    # -----------------------------------------------------------------------
    # Team roster management
    # -----------------------------------------------------------------------

    @app_commands.command(name="addmember", description="Add a member to the team roster.")
    @app_commands.describe(
        member="Member to add",
        team="Team to add them to (required if you are VP of multiple teams)",
    )
    @app_commands.choices(team=TEAM_CHOICES)
    async def addmember(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team == "all":
                effective_team = team.value if team is not None else "growth"
            elif team is not None:
                if team.value not in caller_team:
                    await interaction.response.send_message(
                        "❌ You can only add members to your own team.", ephemeral=True
                    )
                    return
                effective_team = team.value
            elif len(caller_team) > 1:
                await interaction.response.send_message(
                    "⚠️ You are VP of multiple teams. Please specify a team with the `team:` parameter.",
                    ephemeral=True,
                )
                return
            else:
                effective_team = caller_team[0]

            if is_team_member(interaction.guild.id, member.id):
                await interaction.response.send_message(
                    f"⚠️ {member.mention} is already on the team.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return

            add_team_member(
                interaction.guild.id, member.id, member.display_name, team=effective_team
            )
            await interaction.response.send_message(
                f"✅ {member.mention} has been added to the **{effective_team}** team!"
            )

            try:
                await member.send(
                    f"👋 You've been added to the progsu Task Management System by "
                    f"{interaction.user.display_name}.\n\n"
                    f"You'll receive task assignments and deadline reminders here.\n"
                    f"Use /mytasks anytime to see your current tasks."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            await self.notify_admin(
                interaction, "addmember",
                f"Added {member.mention} to the {effective_team} team",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="removemember", description="Remove a member from the team roster.")
    @app_commands.describe(member="Member to remove")
    async def removemember(self, interaction: discord.Interaction, member: discord.Member):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if str(member.id) not in team_ids:
                    await interaction.response.send_message(
                        f"⚠️ {member.mention} is not on your team.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
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
                f"✅ {member.mention} has been removed from the team."
            )

            await self.notify_admin(
                interaction, "removemember",
                f"Removed {member.mention} from the team",
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)

    @app_commands.command(name="teammembers", description="List team members and their task counts.")
    @app_commands.describe(team="Optional: filter by team (admin only; VP sees their own team(s))")
    @app_commands.choices(team=TEAM_CHOICES)
    async def teammembers(
        self,
        interaction: discord.Interaction,
        team: Optional[app_commands.Choice[str]] = None,
    ):
        try:
            if interaction.guild is None:
                await interaction.response.send_message(
                    "This command must be used in a server.", ephemeral=True
                )
                return

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)

            if caller_team == "all":
                if team is not None:
                    team_rows = get_team_members(interaction.guild.id, team=team.value)
                    all_tasks = get_all_tasks(interaction.guild.id, team=team.value)
                    team_label = f" — {team.value.capitalize()}"
                else:
                    team_rows = get_team_members(interaction.guild.id)
                    all_tasks = get_all_tasks(interaction.guild.id)
                    team_label = ""
            else:
                if team is not None and team.value not in caller_team:
                    await interaction.response.send_message(
                        "❌ You can only view members of your own team.", ephemeral=True
                    )
                    return
                if team is not None:
                    team_rows = get_team_members(interaction.guild.id, team=team.value)
                    all_tasks = get_all_tasks(interaction.guild.id, team=team.value)
                    team_label = f" — {team.value.capitalize()}"
                else:
                    team_rows = _get_members_for_vp(interaction.guild.id, caller_team)
                    all_tasks = _get_all_tasks_for_vp(interaction.guild.id, caller_team)
                    if len(caller_team) == 1:
                        team_label = f" — {caller_team[0].capitalize()}"
                    else:
                        team_label = f" — {', '.join(t.capitalize() for t in caller_team)}"

            if not team_rows:
                await interaction.response.send_message(
                    "No team members found. Use /addmember to add members.", ephemeral=True
                )
                return

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

            lines = [f"👥 Team Members{team_label} ({len(team_rows)} total):", ""]
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

    # -----------------------------------------------------------------------
    # Reminders
    # -----------------------------------------------------------------------

    @app_commands.command(name="setchannel", description="Set the reminder channel for a member.")
    @app_commands.describe(
        member="Member to configure reminders for",
        channel="Channel to post reminders in",
    )
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

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if str(member.id) not in team_ids:
                    await interaction.response.send_message(
                        f"❌ {member.mention} is not in your team.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
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

            if not await require_admin_or_vp(interaction):
                return

            caller_team = await get_caller_team(interaction)
            if caller_team != "all":
                team_ids = _get_team_ids_for_vp(interaction.guild.id, caller_team)
                if str(member.id) not in team_ids:
                    await interaction.response.send_message(
                        f"❌ {member.mention} is not in your team.",
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions(users=False),
                    )
                    return

            tasks = get_tasks_by_user(interaction.guild.id, member.id)
            collab_tasks = get_tasks_as_collaborator(interaction.guild.id, member.id)
            merged: dict[int, dict] = {t["id"]: t for t in tasks}
            for ct in collab_tasks:
                merged.setdefault(ct["id"], ct)
            active_tasks = sorted(
                [t for t in merged.values() if t["status"] != "done"],
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
                    ch = await self.bot.fetch_channel(int(channel_id))
                    await ch.send(
                        "\n".join(lines),
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                    await interaction.response.send_message(
                        f"✅ Posted reminder for {member.mention} in {ch.mention}.",
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

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @app_commands.command(name="ping", description="Check if the bot is online.")
    async def ping(self, interaction: discord.Interaction):
        try:
            latency_ms = round(self.bot.latency * 1000)
            await interaction.response.send_message(
                f"🟢 progsu pm bot is online! Latency: {latency_ms}ms",
                ephemeral=True,
            )
        except Exception:
            traceback.print_exc()
            await _send_generic_error(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tasks(bot))
