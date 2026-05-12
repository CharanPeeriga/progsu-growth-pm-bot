from datetime import date, timedelta

import discord
from discord.ext import commands, tasks

import database

CHECK_INTERVAL_MINUTES = 60


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def reminder_loop(self):
        try:
            due_tasks = database.get_unreminded_due_tasks()
        except Exception as e:
            print(f"[reminders] failed to query due tasks: {e}")
            return

        today = date.today()
        tomorrow = today + timedelta(days=1)

        for task in due_tasks:
            assignee_id = int(task["assignee_id"])
            user = self.bot.get_user(assignee_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(assignee_id)
                except discord.HTTPException as e:
                    print(f"[reminders] could not fetch user {assignee_id}: {e}")
                    continue

            due = task["due_date"]
            if due == today:
                when = "today"
            elif due == tomorrow:
                when = "tomorrow"
            else:
                when = due.isoformat()

            message = (
                f"⏰ Reminder: task `#{task['id']}` **{task['task_name']}** "
                f"is due {when} ({due.isoformat()})."
            )

            try:
                await user.send(message)
            except discord.Forbidden:
                print(f"[reminders] cannot DM user {assignee_id} (DMs closed)")
            except discord.HTTPException as e:
                print(f"[reminders] failed to DM user {assignee_id}: {e}")
                continue

            try:
                database.mark_reminded(task["id"])
            except Exception as e:
                print(f"[reminders] failed to mark task {task['id']} reminded: {e}")

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminders(bot))
