import discord
from discord.ext import commands, tasks

from database import (
    get_unreminded_due_tasks,
    mark_reminded_2day,
    mark_reminded_day_of,
    get_reminder_channel,
)


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(hours=1)
    async def reminder_loop(self):
        try:
            two_day_tasks, day_of_tasks = get_unreminded_due_tasks()
        except Exception as e:
            print(f"[reminders] failed to query due tasks: {e}")
            return

        two_day_sent = 0
        for task in two_day_tasks:
            assignee_id = int(task["assignee_id"])
            guild_id = task["guild_id"]

            try:
                channel_id = get_reminder_channel(guild_id, str(assignee_id))
            except Exception as e:
                print(f"[reminders] failed to get reminder channel for {assignee_id}: {e}")
                channel_id = None

            message = (
                "⏰ Heads up — growth-pm-bot\n"
                "You have a task due in 2 days:\n"
                f"#{task['id']}: {task['task_name']}\n"
                f"Due: {task['due_date'].isoformat()}\n"
                f"Use /done {task['id']} to mark it complete."
            )

            if channel_id is not None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                    await channel.send(f"<@{assignee_id}> {message}")
                    two_day_sent += 1
                except Exception as e:
                    print(f"[reminders] could not post in channel {channel_id} for {assignee_id}: {e}")
            else:
                try:
                    user = await self.bot.fetch_user(assignee_id)
                    await user.send(message)
                    two_day_sent += 1
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"[reminders] could not DM user {assignee_id}: {e}")

            try:
                mark_reminded_2day(task["id"])
            except Exception as e:
                print(f"[reminders] failed to mark task {task['id']} 2day reminded: {e}")

        day_of_sent = 0
        for task in day_of_tasks:
            assignee_id = int(task["assignee_id"])
            guild_id = task["guild_id"]

            try:
                channel_id = get_reminder_channel(guild_id, str(assignee_id))
            except Exception as e:
                print(f"[reminders] failed to get reminder channel for {assignee_id}: {e}")
                channel_id = None

            message = (
                "🚨 Due today — growth-pm-bot\n"
                "This task is due TODAY:\n"
                f"#{task['id']}: {task['task_name']}\n"
                f"Due: {task['due_date'].isoformat()}\n"
                f"Use /done {task['id']} to mark it complete."
            )

            if channel_id is not None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                    await channel.send(f"<@{assignee_id}> {message}")
                    day_of_sent += 1
                except Exception as e:
                    print(f"[reminders] could not post in channel {channel_id} for {assignee_id}: {e}")
            else:
                try:
                    user = await self.bot.fetch_user(assignee_id)
                    await user.send(message)
                    day_of_sent += 1
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"[reminders] could not DM user {assignee_id}: {e}")

            try:
                mark_reminded_day_of(task["id"])
            except Exception as e:
                print(f"[reminders] failed to mark task {task['id']} day_of reminded: {e}")

        print(f"🔔 Reminders sent — {two_day_sent} two-day, {day_of_sent} day-of")

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
