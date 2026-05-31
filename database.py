import os
from datetime import date

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# Sentinel passed to update_task() to explicitly set due_date to NULL.
CLEAR = object()


def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in environment")
    return psycopg2.connect(database_url)


def run_migration():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminded_2day BOOLEAN DEFAULT FALSE;
                ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminded_day_of BOOLEAN DEFAULT FALSE;
                ALTER TABLE tasks ADD COLUMN IF NOT EXISTS rejection_reason TEXT DEFAULT NULL;
                ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
                ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
                    CHECK (status IN ('todo', 'in_progress', 'review', 'done'));
                CREATE TABLE IF NOT EXISTS reminder_channels (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    UNIQUE(guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS team_members (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT,
                    added_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(guild_id, user_id)
                );
                """
            )
        conn.commit()
    finally:
        conn.close()

    # Migrate vp_roles to support multiple teams per user.
    # Drops the old (guild_id, user_id) unique constraint and replaces it
    # with (guild_id, user_id, team) so one person can VP multiple teams.
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE vp_roles DROP CONSTRAINT IF EXISTS vp_roles_guild_id_user_id_key"
            )
            cur.execute(
                """
                ALTER TABLE vp_roles ADD CONSTRAINT vp_roles_guild_id_user_id_team_key
                    UNIQUE (guild_id, user_id, team)
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def insert_task(guild_id, assignee_id, assigner_id, task_name, due_date, team="growth"):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (guild_id, assignee_id, assigner_id, task_name, due_date, team)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (str(guild_id), str(assignee_id), str(assigner_id), task_name, due_date, team),
            )
            task_id = cur.fetchone()[0]
        conn.commit()
        return task_id
    finally:
        conn.close()


def get_tasks_by_user(guild_id, assignee_id, team=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if team is not None:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s AND assignee_id = %s AND team = %s
                    ORDER BY due_date NULLS LAST, created_at
                    """,
                    (str(guild_id), str(assignee_id), team),
                )
            else:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s AND assignee_id = %s
                    ORDER BY due_date NULLS LAST, created_at
                    """,
                    (str(guild_id), str(assignee_id)),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_tasks(guild_id, team=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if team is not None:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s AND team = %s
                    ORDER BY due_date NULLS LAST, created_at
                    """,
                    (str(guild_id), team),
                )
            else:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s
                    ORDER BY due_date NULLS LAST, created_at
                    """,
                    (str(guild_id),),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def update_task_status(task_id, status):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = %s WHERE id = %s",
                (status, task_id),
            )
            updated = cur.rowcount
        conn.commit()
        return updated
    finally:
        conn.close()


def update_task(task_id, task_name=None, due_date=None):
    set_clauses = []
    params = []

    if task_name is not None:
        set_clauses.append("task_name = %s")
        params.append(task_name)

    if due_date is not None:
        set_clauses.append("due_date = %s")
        params.append(None if due_date is CLEAR else due_date)

    if not set_clauses:
        return

    params.append(task_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = %s",
                params,
            )
        conn.commit()
    finally:
        conn.close()


def delete_task(task_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM task_collaborators WHERE task_id = %s", (task_id,))
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_task_by_id(task_id, guild_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at,
                       reminded_2day, reminded_day_of, rejection_reason
                FROM tasks
                WHERE id = %s AND guild_id = %s
                """,
                (task_id, str(guild_id)),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_unreminded_due_tasks():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at
                FROM tasks
                WHERE due_date = CURRENT_DATE + INTERVAL '2 days'
                  AND status IN ('todo', 'in_progress')
                  AND reminded_2day = FALSE
                """
            )
            two_day_tasks = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at
                FROM tasks
                WHERE due_date = CURRENT_DATE
                  AND status IN ('todo', 'in_progress')
                  AND reminded_day_of = FALSE
                """
            )
            day_of_tasks = [dict(row) for row in cur.fetchall()]

        return two_day_tasks, day_of_tasks
    finally:
        conn.close()


def mark_reminded_2day(task_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET reminded_2day = TRUE WHERE id = %s",
                (task_id,),
            )
        conn.commit()
    finally:
        conn.close()


def mark_reminded_day_of(task_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET reminded_day_of = TRUE WHERE id = %s",
                (task_id,),
            )
        conn.commit()
    finally:
        conn.close()


def get_tasks_in_review(guild_id, team=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if team is not None:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s AND status = 'review' AND team = %s
                    ORDER BY created_at
                    """,
                    (str(guild_id), team),
                )
            else:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at, rejection_reason, team
                    FROM tasks
                    WHERE guild_id = %s AND status = 'review'
                    ORDER BY created_at
                    """,
                    (str(guild_id),),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def approve_task(task_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'done', rejection_reason = NULL WHERE id = %s",
                (task_id,),
            )
        conn.commit()
    finally:
        conn.close()


def reject_task(task_id, reason):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'in_progress', rejection_reason = %s WHERE id = %s",
                (reason, task_id),
            )
        conn.commit()
    finally:
        conn.close()


def set_reminder_channel(guild_id, user_id, channel_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reminder_channels (guild_id, user_id, channel_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET channel_id = EXCLUDED.channel_id
                """,
                (str(guild_id), str(user_id), str(channel_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_reminder_channel(guild_id, user_id):
    """Returns (channel_id, source) where source is 'personal', 'team', or None."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_id FROM reminder_channels WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
            row = cur.fetchone()
            if row:
                return row[0], "personal"

            cur.execute(
                "SELECT team FROM team_members WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
            row = cur.fetchone()
            if row and row[0]:
                cur.execute(
                    "SELECT channel_id FROM team_channels WHERE guild_id = %s AND team = %s",
                    (str(guild_id), row[0]),
                )
                row = cur.fetchone()
                if row:
                    return row[0], "team"

            return None, None
    finally:
        conn.close()


def get_tasks_for_progress(guild_id, since_date=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since_date is None:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at
                    FROM tasks
                    WHERE guild_id = %s
                    ORDER BY created_at
                    """,
                    (str(guild_id),),
                )
            else:
                cur.execute(
                    """
                    SELECT id, guild_id, assignee_id, assigner_id, task_name,
                           due_date, status, created_at
                    FROM tasks
                    WHERE guild_id = %s AND created_at >= %s
                    ORDER BY created_at
                    """,
                    (str(guild_id), since_date),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def add_team_member(guild_id, user_id, display_name, team=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO team_members (guild_id, user_id, display_name, team)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id, user_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        team = EXCLUDED.team
                """,
                (str(guild_id), str(user_id), display_name, team),
            )
        conn.commit()
    finally:
        conn.close()


def remove_team_member(guild_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM team_members WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_team_members(guild_id, team=None):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if team is not None:
                cur.execute(
                    """
                    SELECT id, guild_id, user_id, display_name, team, added_at
                    FROM team_members
                    WHERE guild_id = %s AND team = %s
                    ORDER BY added_at
                    """,
                    (str(guild_id), team),
                )
            else:
                cur.execute(
                    """
                    SELECT id, guild_id, user_id, display_name, team, added_at
                    FROM team_members
                    WHERE guild_id = %s
                    ORDER BY added_at
                    """,
                    (str(guild_id),),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def is_team_member(guild_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM team_members WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_member_team(guild_id, user_id):
    """Returns the team string for a team member, or None if not in team_members."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT team FROM team_members WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# VP role functions
# ---------------------------------------------------------------------------

def set_vp(guild_id, user_id, team, added_by):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vp_roles (guild_id, user_id, team, added_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id, user_id, team) DO UPDATE
                    SET added_by = EXCLUDED.added_by
                """,
                (str(guild_id), str(user_id), team, str(added_by)),
            )
        conn.commit()
    finally:
        conn.close()


def remove_vp(guild_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vp_roles WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_vp_roles(guild_id, user_id):
    """Returns all VP role rows for this user (list, empty if not a VP)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, user_id, team, added_by, added_at
                FROM vp_roles
                WHERE guild_id = %s AND user_id = %s
                ORDER BY added_at
                """,
                (str(guild_id), str(user_id)),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_team_for_user(guild_id, user_id):
    """Returns list of teams the user is VP of, or [] if not a VP."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT team FROM vp_roles WHERE guild_id = %s AND user_id = %s ORDER BY added_at",
                (str(guild_id), str(user_id)),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def is_vp(guild_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM vp_roles WHERE guild_id = %s AND user_id = %s",
                (str(guild_id), str(user_id)),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_all_vps(guild_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, user_id, team, added_by, added_at
                FROM vp_roles
                WHERE guild_id = %s
                ORDER BY added_at
                """,
                (str(guild_id),),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Team channel functions
# ---------------------------------------------------------------------------

def set_team_channel(guild_id, team, channel_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO team_channels (guild_id, team, channel_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, team) DO UPDATE SET channel_id = EXCLUDED.channel_id
                """,
                (str(guild_id), team, str(channel_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_team_channel(guild_id, team):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_id FROM team_channels WHERE guild_id = %s AND team = %s",
                (str(guild_id), team),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task query functions
# ---------------------------------------------------------------------------

def get_tasks_for_team(guild_id, team):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at, rejection_reason, team
                FROM tasks
                WHERE guild_id = %s AND team = %s
                ORDER BY due_date NULLS LAST, created_at
                """,
                (str(guild_id), team),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Collaborator functions
# ---------------------------------------------------------------------------

def add_collaborator(task_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO task_collaborators (task_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (task_id, user_id) DO NOTHING
                """,
                (task_id, str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()


def remove_collaborator(task_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM task_collaborators WHERE task_id = %s AND user_id = %s",
                (task_id, str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()


def get_collaborators(task_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, task_id, user_id, submitted, submitted_at
                FROM task_collaborators
                WHERE task_id = %s
                ORDER BY id
                """,
                (task_id,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def submit_collaborator(task_id, user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_collaborators
                SET submitted = TRUE, submitted_at = NOW()
                WHERE task_id = %s AND user_id = %s
                """,
                (task_id, str(user_id)),
            )
        conn.commit()
    finally:
        conn.close()


def all_collaborators_submitted(task_id):
    """Returns True if every collaborator has submitted, or if there are no collaborators."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT submitted FROM task_collaborators WHERE task_id = %s",
                (task_id,),
            )
            rows = cur.fetchall()
            if not rows:
                return True
            return all(row[0] for row in rows)
    finally:
        conn.close()


def get_pending_collaborators(task_id):
    """Returns list of user_ids that have not yet submitted."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM task_collaborators WHERE task_id = %s AND submitted = FALSE",
                (task_id,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_tasks_as_collaborator(guild_id, user_id):
    """Returns tasks where user is a collaborator, including their own submitted status."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.guild_id, t.assignee_id, t.task_name,
                       t.due_date, t.status, t.created_at, t.rejection_reason,
                       tc.submitted, tc.submitted_at
                FROM tasks t
                JOIN task_collaborators tc ON t.id = tc.task_id AND tc.user_id = %s
                WHERE t.guild_id = %s
                ORDER BY t.due_date NULLS LAST, t.created_at
                """,
                (str(user_id), str(guild_id)),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_task_collaborators(guild_id):
    """Returns {task_id: [{'user_id': ..., 'submitted': bool}]} for all tasks in the guild."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT tc.task_id, tc.user_id, tc.submitted
                FROM task_collaborators tc
                JOIN tasks t ON t.id = tc.task_id
                WHERE t.guild_id = %s
                ORDER BY tc.task_id, tc.id
                """,
                (str(guild_id),),
            )
            result: dict = {}
            for row in cur.fetchall():
                result.setdefault(row["task_id"], []).append(
                    {"user_id": row["user_id"], "submitted": row["submitted"]}
                )
            return result
    finally:
        conn.close()
