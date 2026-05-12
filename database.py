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
                """
            )
        conn.commit()
    finally:
        conn.close()


def insert_task(guild_id, assignee_id, assigner_id, task_name, due_date):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (guild_id, assignee_id, assigner_id, task_name, due_date)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (str(guild_id), str(assignee_id), str(assigner_id), task_name, due_date),
            )
            task_id = cur.fetchone()[0]
        conn.commit()
        return task_id
    finally:
        conn.close()


def get_tasks_by_user(guild_id, assignee_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at
                FROM tasks
                WHERE guild_id = %s AND assignee_id = %s
                ORDER BY due_date NULLS LAST, created_at
                """,
                (str(guild_id), str(assignee_id)),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_tasks(guild_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, guild_id, assignee_id, assigner_id, task_name,
                       due_date, status, created_at
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
                       reminded_2day, reminded_day_of
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
                  AND status <> 'done'
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
                  AND status <> 'done'
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
