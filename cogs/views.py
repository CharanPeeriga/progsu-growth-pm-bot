import discord
from discord.ui import View, Button, Modal, TextInput

from database import is_vp, get_collaborators


class RejectModal(Modal, title="Reject Task"):
    reason = TextInput(
        label="Feedback for the member",
        style=discord.TextStyle.paragraph,
        placeholder="What needs to change?",
        required=True,
        max_length=500,
    )

    def __init__(self, task_id: int, assignee_id: str, task_name: str):
        super().__init__()
        self.task_id = task_id
        self.assignee_id = assignee_id
        self.task_name = task_name

    async def on_submit(self, interaction: discord.Interaction):
        from database import reject_task
        reject_task(self.task_id, self.reason.value)
        try:
            assignee = await interaction.client.fetch_user(int(self.assignee_id))
            await assignee.send(
                f"↩️ Task sent back — progsu pm bot\n"
                f"Your task has been reviewed and needs more work:\n"
                f"Task #{self.task_id}: {self.task_name}\n"
                f"Feedback: {self.reason.value}\n"
                f"Please update your work and set a new due date if needed:\n"
                f"→ Update due date: /edittask {self.task_id} due:YYYY-MM-DD\n"
                f"→ Resubmit when ready: /done {self.task_id}"
            )
        except Exception:
            pass
        for c in get_collaborators(self.task_id):
            if c["user_id"] == self.assignee_id:
                continue
            try:
                cu = await interaction.client.fetch_user(int(c["user_id"]))
                await cu.send(
                    f"↩️ Task sent back — progsu pm bot\n"
                    f"Task #{self.task_id}: {self.task_name}\n"
                    f"Feedback: {self.reason.value}\n"
                    f"Please update your work and set a new due date if needed:\n"
                    f"→ Update due date: /edittask {self.task_id} due:YYYY-MM-DD\n"
                    f"→ Resubmit when ready: /done {self.task_id}"
                )
            except Exception:
                pass
        await interaction.response.send_message(
            f"↩️ Task #{self.task_id} sent back with feedback.", ephemeral=True
        )


class MarkInProgressButton(Button):
    def __init__(self, task_id: int):
        super().__init__(
            label="Mark In Progress",
            style=discord.ButtonStyle.secondary,
            emoji="🟡",
            custom_id=f"inprogress_{task_id}",
        )
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        from database import get_task_by_id, update_task_status
        task = get_task_by_id(self.task_id, interaction.guild_id)
        if not task:
            await interaction.response.send_message("❌ Task not found.", ephemeral=True)
            return
        if str(interaction.user.id) != task["assignee_id"]:
            await interaction.response.send_message(
                "❌ This is not your task.", ephemeral=True
            )
            return
        if task["status"] != "todo":
            await interaction.response.send_message(
                f"⚠️ Task is already {task['status']}.", ephemeral=True
            )
            return
        update_task_status(self.task_id, "in_progress")
        await interaction.response.send_message(
            f"🟡 {interaction.user.mention} is now working on task "
            f"#{self.task_id}: {task['task_name']}"
        )


class SubmitForReviewButton(Button):
    def __init__(self, task_id: int):
        super().__init__(
            label="Submit for Review",
            style=discord.ButtonStyle.primary,
            emoji="⏳",
            custom_id=f"submit_{task_id}",
        )
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        from database import (
            get_task_by_id,
            update_task_status,
            get_collaborators,
            submit_collaborator,
            all_collaborators_submitted,
            get_pending_collaborators,
        )
        task = get_task_by_id(self.task_id, interaction.guild_id)
        if not task:
            await interaction.response.send_message("❌ Task not found.", ephemeral=True)
            return
        collabs = get_collaborators(self.task_id)
        collab_ids = [c["user_id"] for c in collabs]
        is_assignee = str(interaction.user.id) == task["assignee_id"]
        is_collab = str(interaction.user.id) in collab_ids
        if not (is_assignee or is_collab):
            await interaction.response.send_message(
                "❌ You are not assigned to this task.", ephemeral=True
            )
            return
        if task["status"] == "review":
            await interaction.response.send_message("⏳ Already in review.", ephemeral=True)
            return
        if task["status"] == "done":
            await interaction.response.send_message("✅ Already complete.", ephemeral=True)
            return
        if collabs:
            if is_collab:
                submit_collaborator(self.task_id, str(interaction.user.id))
            if not all_collaborators_submitted(self.task_id):
                pending = get_pending_collaborators(self.task_id)
                mentions = ", ".join(f"<@{uid}>" for uid in pending)
                await interaction.response.send_message(
                    f"⏳ Your part is submitted. Still waiting on: {mentions}",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions(users=False),
                )
                return
        update_task_status(self.task_id, "review")
        review_view = TaskActionView(
            self.task_id, task["assignee_id"], task["task_name"], mode="review"
        )
        try:
            owner = await interaction.client.fetch_user(interaction.guild.owner_id)
            await owner.send(
                f"📋 Task submitted for review — progsu pm bot\n"
                f"{interaction.user.mention} submitted task "
                f"#{self.task_id}: {task['task_name']}\n"
                f"Use the buttons below to approve or reject.",
                view=review_view,
            )
        except Exception:
            pass
        await interaction.response.send_message(
            f"⏳ {interaction.user.mention} submitted task "
            f"#{self.task_id} for review: {task['task_name']}"
        )


class ApproveButton(Button):
    def __init__(self, task_id: int, assignee_id: str, task_name: str):
        super().__init__(
            label="Approve",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"approve_{task_id}",
        )
        self.task_id = task_id
        self.assignee_id = assignee_id
        self.task_name = task_name

    async def callback(self, interaction: discord.Interaction):
        from database import approve_task
        # In guild context, enforce admin/VP; in DM context (owner's DM), allow
        if interaction.guild is not None:
            is_admin = interaction.user.guild_permissions.manage_guild
            vp = is_vp(str(interaction.guild.id), str(interaction.user.id))
            if not (is_admin or vp):
                await interaction.response.send_message(
                    "❌ You don't have permission to approve tasks.", ephemeral=True
                )
                return
        approve_task(self.task_id)
        try:
            assignee = await interaction.client.fetch_user(int(self.assignee_id))
            await assignee.send(
                f"✅ Task approved — progsu pm bot\n"
                f"Your task has been reviewed and approved!\n"
                f"Task #{self.task_id}: {self.task_name}\n"
                f"Great work!"
            )
        except Exception:
            pass
        for c in get_collaborators(self.task_id):
            if c["user_id"] == self.assignee_id:
                continue
            try:
                cu = await interaction.client.fetch_user(int(c["user_id"]))
                await cu.send(
                    f"✅ Task approved — progsu pm bot\n"
                    f"Task #{self.task_id}: {self.task_name} was approved.\n"
                    f"Great work!"
                )
            except Exception:
                pass
        await interaction.response.send_message(
            f"✅ Task #{self.task_id} approved: {self.task_name}", ephemeral=True
        )


class RejectButton(Button):
    def __init__(self, task_id: int, assignee_id: str, task_name: str):
        super().__init__(
            label="Reject",
            style=discord.ButtonStyle.danger,
            emoji="↩️",
            custom_id=f"reject_{task_id}",
        )
        self.task_id = task_id
        self.assignee_id = assignee_id
        self.task_name = task_name

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is not None:
            is_admin = interaction.user.guild_permissions.manage_guild
            vp = is_vp(str(interaction.guild.id), str(interaction.user.id))
            if not (is_admin or vp):
                await interaction.response.send_message(
                    "❌ You don't have permission to reject tasks.", ephemeral=True
                )
                return
        modal = RejectModal(self.task_id, self.assignee_id, self.task_name)
        await interaction.response.send_modal(modal)


class TaskActionView(View):
    def __init__(
        self,
        task_id: int,
        assignee_id: str,
        task_name: str,
        mode: str = "member",
    ):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.assignee_id = assignee_id
        self.task_name = task_name
        self.mode = mode

        if mode == "member":
            self.add_item(MarkInProgressButton(task_id))
            self.add_item(SubmitForReviewButton(task_id))
        elif mode == "review":
            self.add_item(ApproveButton(task_id, assignee_id, task_name))
            self.add_item(RejectButton(task_id, assignee_id, task_name))
