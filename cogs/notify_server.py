import os

import discord
from aiohttp import web

from database import get_reminder_channel
from cogs.views import TaskActionView


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

    message = (
        f"✅ Task #{task_id} assigned to <@{assignee_id}>\n"
        f"📋 {task_name}\n"
        f"📅 Due: {due_str}\n"
        f"Assigned via dashboard"
    )
    if collab_mentions:
        message += f"\n🤝 Collaborators: {collab_mentions}"

    view = TaskActionView(task_id, str(assignee_id), task_name, mode="member")

    channel_id, channel_type = get_reminder_channel(guild_id, str(assignee_id))

    if channel_id:
        channel = bot.get_channel(int(channel_id))
        if channel:
            await channel.send(
                message,
                view=view,
                allowed_mentions=discord.AllowedMentions(users=False),
            )
            return {"notified": True, "method": channel_type}

    try:
        user = await bot.fetch_user(int(assignee_id))
        await user.send(message, view=view)
        return {"notified": True, "method": "dm"}
    except Exception:
        return {
            "notified": False,
            "method": None,
            "warning": "no_channel_and_dm_failed",
        }


async def handle_notify(request):
    auth = request.headers.get("Authorization", "")
    secret = os.getenv("BOT_NOTIFY_SECRET", "")
    if not secret or auth != f"Bearer {secret}":
        return web.Response(status=401, text="Unauthorized")

    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    guild_id = data.get("guild_id")
    task_id = data.get("task_id")
    task_name = data.get("task_name")
    assignee_id = data.get("assignee_id")
    due_date = data.get("due_date")
    team = data.get("team", "growth")
    collaborator_ids = data.get("collaborator_ids", [])

    if not all([guild_id, task_id, task_name, assignee_id]):
        return web.Response(
            status=400,
            text="Missing required fields: guild_id, task_id, task_name, assignee_id",
        )

    result = await notify_task_assigned(
        request.app["bot"],
        guild_id,
        task_id,
        task_name,
        assignee_id,
        due_date,
        team,
        collaborator_ids,
    )
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
