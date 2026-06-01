import os

import discord
from aiohttp import web

from database import get_reminder_channel, get_team_channel
from cogs.views import TaskActionView


async def get_team_channel_obj(bot, guild_id, team):
    """Returns the Discord channel object for a team's default channel, or None."""
    channel_id = get_team_channel(guild_id, team)
    if channel_id:
        return bot.get_channel(int(channel_id))
    return None


async def notify_task_assigned(
    bot,
    guild_id,
    task_id,
    task_name,
    assignee_id,
    due_date,
    team,
    collaborator_ids=None,
):
    if collaborator_ids is None:
        collaborator_ids = []

    due_str = due_date if due_date else "No due date"
    collab_mentions = " ".join(f"<@{uid}>" for uid in collaborator_ids)

    team_channel_ok = False
    personal_channel_ok = False
    dm_ok = False

    # 1. Always post summary to team channel
    team_channel = await get_team_channel_obj(bot, guild_id, team)
    if team_channel:
        try:
            summary = (
                f"📋 New task assigned via dashboard\n"
                f"**#{task_id}: {task_name}**\n"
                f"Assigned to <@{assignee_id}> · Due: {due_str}"
            )
            await team_channel.send(
                summary,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            team_channel_ok = True
        except Exception:
            pass

    member_message = (
        f"✅ Task #{task_id} assigned to <@{assignee_id}>\n"
        f"📋 {task_name}\n"
        f"📅 Due: {due_str}\n"
        f"Assigned via dashboard"
    )
    if collab_mentions:
        member_message += f"\n🤝 Collaborators: {collab_mentions}"

    view = TaskActionView(task_id, str(assignee_id), task_name, mode="member")

    # 2. Post to personal reminder channel if configured
    channel_id, channel_type = get_reminder_channel(guild_id, str(assignee_id))
    if channel_id:
        reminder_channel = bot.get_channel(int(channel_id))
        if reminder_channel:
            try:
                await reminder_channel.send(
                    member_message,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                personal_channel_ok = True
            except Exception:
                pass

    # 3. Always try to DM the assignee directly
    try:
        user = await bot.fetch_user(int(assignee_id))
        await user.send(member_message, view=view)
        dm_ok = True
    except Exception:
        pass

    return {
        "team_channel": team_channel_ok,
        "personal_channel": personal_channel_ok,
        "dm": dm_ok,
    }


async def notify_member_added(bot, guild_id, user_id, display_name, team, added_by):
    team_channel_ok = False
    dm_ok = False

    channel = await get_team_channel_obj(bot, guild_id, team)
    if channel:
        try:
            await channel.send(
                f"👋 New member added to the progsu Task Management System\n"
                f"**{display_name}** (<@{user_id}>) has been added to the "
                f"**{team.capitalize()}** team by {added_by}.",
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            team_channel_ok = True
        except Exception:
            pass

    try:
        user = await bot.fetch_user(int(user_id))
        await user.send(
            f"👋 You've been added to the progsu Task Management System.\n"
            f"You'll receive task assignments and deadline reminders here.\n"
            f"Use /mytasks anytime to see your current tasks."
        )
        dm_ok = True
    except Exception:
        pass

    return {"team_channel": team_channel_ok, "personal_channel": False, "dm": dm_ok}


async def notify_task_approved(
    bot, guild_id, task_id, task_name, assignee_id, team, approved_by
):
    team_channel_ok = False
    dm_ok = False

    channel = await get_team_channel_obj(bot, guild_id, team)
    if channel:
        try:
            await channel.send(
                f"✅ Task approved via dashboard\n"
                f"**#{task_id}: {task_name}**\n"
                f"<@{assignee_id}>'s task was approved by {approved_by}.",
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            team_channel_ok = True
        except Exception:
            pass

    try:
        user = await bot.fetch_user(int(assignee_id))
        await user.send(
            f"✅ Task approved — progsu pm bot\n"
            f"Your task has been reviewed and approved!\n"
            f"Task #{task_id}: {task_name}\n"
            f"Great work!"
        )
        dm_ok = True
    except Exception:
        pass

    return {"team_channel": team_channel_ok, "personal_channel": False, "dm": dm_ok}


async def notify_task_rejected(
    bot, guild_id, task_id, task_name, assignee_id, team, rejected_by, reason
):
    team_channel_ok = False
    dm_ok = False

    channel = await get_team_channel_obj(bot, guild_id, team)
    if channel:
        try:
            await channel.send(
                f"↩️ Task sent back via dashboard\n"
                f"**#{task_id}: {task_name}**\n"
                f"<@{assignee_id}>'s task was sent back by {rejected_by}.\n"
                f"Reason: {reason}",
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            team_channel_ok = True
        except Exception:
            pass

    try:
        user = await bot.fetch_user(int(assignee_id))
        await user.send(
            f"↩️ Task sent back — progsu pm bot\n"
            f"Your task has been reviewed and needs more work:\n"
            f"Task #{task_id}: {task_name}\n"
            f"Feedback: {reason}\n"
            f"Please update your work and set a new due date if needed:\n"
            f"→ Update due date: /edittask {task_id} due:YYYY-MM-DD\n"
            f"→ Resubmit when ready: /done {task_id}"
        )
        dm_ok = True
    except Exception:
        pass

    return {"team_channel": team_channel_ok, "personal_channel": False, "dm": dm_ok}


async def notify_task_edited(
    bot, guild_id, task_id, task_name, assignee_id, team, edited_by, changes
):
    team_channel_ok = False

    channel = await get_team_channel_obj(bot, guild_id, team)
    if not channel:
        return {"team_channel": False, "personal_channel": False, "dm": False}

    changes_str = "\n".join(f"  {k}: {v}" for k, v in changes.items())
    try:
        await channel.send(
            f"✏️ Task updated via dashboard\n"
            f"**#{task_id}: {task_name}**\n"
            f"Updated by {edited_by}:\n"
            f"{changes_str}",
            allowed_mentions=discord.AllowedMentions(users=False),
        )
        team_channel_ok = True
    except Exception:
        pass

    return {"team_channel": team_channel_ok, "personal_channel": False, "dm": False}


async def notify_task_deleted(bot, guild_id, task_id, task_name, team, deleted_by):
    team_channel_ok = False

    channel = await get_team_channel_obj(bot, guild_id, team)
    if not channel:
        return {"team_channel": False, "personal_channel": False, "dm": False}

    try:
        await channel.send(
            f"🗑️ Task deleted via dashboard\n"
            f"**#{task_id}: {task_name}** was deleted by {deleted_by}.",
            allowed_mentions=discord.AllowedMentions(users=False),
        )
        team_channel_ok = True
    except Exception:
        pass

    return {"team_channel": team_channel_ok, "personal_channel": False, "dm": False}


async def handle_notify(request):
    auth = request.headers.get("Authorization", "")
    secret = os.getenv("BOT_NOTIFY_SECRET", "")
    if not secret or auth != f"Bearer {secret}":
        return web.Response(status=401, text="Unauthorized")

    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    bot = request.app["bot"]
    event = data.get("event", "task_assigned")
    guild_id = data.get("guild_id")
    team = data.get("team", "growth")

    if not guild_id:
        return web.Response(status=400, text="Missing required field: guild_id")

    if event == "task_assigned":
        task_id = data.get("task_id")
        task_name = data.get("task_name")
        assignee_id = data.get("assignee_id")
        if not all([task_id, task_name, assignee_id]):
            return web.Response(
                status=400,
                text="task_assigned requires: task_id, task_name, assignee_id",
            )
        result = await notify_task_assigned(
            bot, guild_id, task_id, task_name, assignee_id,
            data.get("due_date"), team, data.get("collaborator_ids", []),
        )

    elif event == "member_added":
        user_id = data.get("user_id")
        if not user_id:
            return web.Response(status=400, text="member_added requires: user_id")
        result = await notify_member_added(
            bot, guild_id, user_id,
            data.get("display_name", ""),
            team,
            data.get("added_by", "the dashboard"),
        )

    elif event == "task_approved":
        task_id = data.get("task_id")
        assignee_id = data.get("assignee_id")
        if not all([task_id, assignee_id]):
            return web.Response(
                status=400, text="task_approved requires: task_id, assignee_id"
            )
        result = await notify_task_approved(
            bot, guild_id, task_id,
            data.get("task_name", ""),
            assignee_id, team,
            data.get("approved_by", "an admin"),
        )

    elif event == "task_rejected":
        task_id = data.get("task_id")
        assignee_id = data.get("assignee_id")
        reason = data.get("reason", "")
        if not all([task_id, assignee_id, reason]):
            return web.Response(
                status=400, text="task_rejected requires: task_id, assignee_id, reason"
            )
        result = await notify_task_rejected(
            bot, guild_id, task_id,
            data.get("task_name", ""),
            assignee_id, team,
            data.get("rejected_by", "an admin"),
            reason,
        )

    elif event == "task_edited":
        task_id = data.get("task_id")
        changes = data.get("changes", {})
        if not task_id:
            return web.Response(status=400, text="task_edited requires: task_id")
        result = await notify_task_edited(
            bot, guild_id, task_id,
            data.get("task_name", ""),
            data.get("assignee_id"),
            team,
            data.get("edited_by", "an admin"),
            changes,
        )

    elif event == "task_deleted":
        task_id = data.get("task_id")
        if not task_id:
            return web.Response(status=400, text="task_deleted requires: task_id")
        result = await notify_task_deleted(
            bot, guild_id, task_id,
            data.get("task_name", ""),
            team,
            data.get("deleted_by", "an admin"),
        )

    else:
        return web.Response(status=400, text=f"Unknown event type: {event}")

    return web.json_response(result)


async def start_notify_server(bot):
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/notify", handle_notify)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("NOTIFY_PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Notify server listening on port {port}")
