import os
import asyncio
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from database import run_migration

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in environment")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True


class PMBot(commands.Bot):
    async def setup_hook(self) -> None:
        from cogs.views import TaskActionView
        from cogs.notify_server import start_notify_server
        self.add_view(TaskActionView(0, "0", "", mode="member"))
        self.add_view(TaskActionView(0, "0", "", mode="review"))
        print("✅ Persistent views registered")
        await start_notify_server(self)


bot = PMBot(command_prefix="!", intents=intents)

INITIAL_EXTENSIONS = (
    "cogs.tasks",
    "cogs.reminders",
)


@bot.event
async def on_ready():
    try:
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"Cleared guild commands for '{guild.name}'.")

        global_synced = await bot.tree.sync()
        print(f"Synced {len(global_synced)} slash command(s) globally.")
    except Exception as e:
        print(f"Failed to sync command tree: {e}")
    print("✅ growth-pm-bot is online!")


@bot.command()
@commands.is_owner()
async def sync(ctx):
    bot.tree.clear_commands(guild=ctx.guild)
    bot.tree.copy_global_to(guild=ctx.guild)
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"✅ Synced {len(synced)} command(s) to this server instantly.")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "❌ You don't have permission to use this command."
    else:
        message = (
            "⚠️ Something went wrong. Please try again or contact your server admin."
        )
        traceback.print_exception(type(error), error, error.__traceback__)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        traceback.print_exc()


async def main():
    print("Running database migration…")
    run_migration()
    print("Migration complete.")

    async with bot:
        for ext in INITIAL_EXTENSIONS:
            await bot.load_extension(ext)
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
