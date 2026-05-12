import io
import sys
import unittest
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database import (
    get_connection,
    run_migration,
    insert_task,
    get_task_by_id,
    get_tasks_by_user,
    get_all_tasks,
    update_task_status,
    delete_task,
    get_tasks_for_progress,
    get_unreminded_due_tasks,
    mark_reminded_2day,
    mark_reminded_day_of,
)

TEST_GUILD_ID = "test_guild_123"
TEST_USER_ID = "test_user_456"
TEST_ADMIN_ID = "test_admin_789"

TEST_NAMES = {
    "test_01_connection": "Test 1  — Connection",
    "test_02_insert_task": "Test 2  — Insert task",
    "test_03_get_task_by_id": "Test 3  — Get task by ID",
    "test_04_get_tasks_by_user": "Test 4  — Get tasks by user",
    "test_05_get_all_tasks": "Test 5  — Get all tasks for guild",
    "test_06_update_status_in_progress": "Test 6  — Update status: in_progress",
    "test_07_update_status_done": "Test 7  — Update status: done",
    "test_08_progress_no_filter": "Test 8  — Progress query (no filter)",
    "test_09_progress_with_filter": "Test 9  — Progress query (date filter)",
    "test_10_mark_reminded_2day": "Test 10 — Mark reminded_2day",
    "test_11_mark_reminded_day_of": "Test 11 — Mark reminded_day_of",
    "test_12_get_unreminded_due_tasks": "Test 12 — get_unreminded_due_tasks",
    "test_13_delete_task": "Test 13 — Delete task",
}

TEST_ORDER = list(TEST_NAMES.keys())


def _cleanup_test_rows():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE guild_id = %s", (TEST_GUILD_ID,))
        conn.commit()
    finally:
        conn.close()


class DatabaseTests(unittest.TestCase):
    task_id = None
    task_id_2 = None
    task_id_3 = None

    @classmethod
    def setUpClass(cls):
        run_migration()
        _cleanup_test_rows()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_rows()

    def test_01_connection(self):
        conn = get_connection()
        self.assertIsNotNone(conn, "get_connection() returned None")
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 1, "SELECT 1 did not return 1")

    def test_02_insert_task(self):
        due_date = (date.today() + timedelta(days=5)).isoformat()
        task_id = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Test task from test suite",
            due_date=due_date,
        )
        self.assertIsInstance(task_id, int, "insert_task did not return an int")
        self.assertGreater(task_id, 0, "task_id is not greater than 0")
        DatabaseTests.task_id = task_id

    def test_03_get_task_by_id(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "returned None, expected task object")
        self.assertEqual(
            task["task_name"],
            "Test task from test suite",
            f"task_name was {task['task_name']!r}",
        )
        self.assertEqual(
            task["status"], "todo", f"status was {task['status']!r}, expected 'todo'"
        )
        self.assertEqual(
            task["reminded_2day"], False, "reminded_2day should default to False"
        )
        self.assertEqual(
            task["reminded_day_of"], False, "reminded_day_of should default to False"
        )

    def test_04_get_tasks_by_user(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        tasks = get_tasks_by_user(TEST_GUILD_ID, TEST_USER_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        ids = [t["id"] for t in tasks]
        self.assertIn(DatabaseTests.task_id, ids, "test task_id not in result")

    def test_05_get_all_tasks(self):
        tasks = get_all_tasks(TEST_GUILD_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        assignees = [t["assignee_id"] for t in tasks]
        self.assertIn(TEST_USER_ID, assignees, "no task for test_user_456 found")

    def test_06_update_status_in_progress(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        update_task_status(DatabaseTests.task_id, "in_progress")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "task vanished after update")
        self.assertEqual(
            task["status"], "in_progress", f"status was {task['status']!r}"
        )

    def test_07_update_status_done(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        update_task_status(DatabaseTests.task_id, "done")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "task vanished after update")
        self.assertEqual(task["status"], "done", f"status was {task['status']!r}")

    def test_08_progress_no_filter(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        tasks = get_tasks_for_progress(TEST_GUILD_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        ids = [t["id"] for t in tasks]
        self.assertIn(
            DatabaseTests.task_id, ids, "test task missing from progress result"
        )

    def test_09_progress_with_filter(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        yesterday = date.today() - timedelta(days=1)
        tomorrow = date.today() + timedelta(days=1)

        recent = get_tasks_for_progress(TEST_GUILD_ID, since_date=yesterday)
        recent_ids = [t["id"] for t in recent]
        self.assertIn(
            DatabaseTests.task_id,
            recent_ids,
            "test task missing from yesterday-filter result",
        )

        future = get_tasks_for_progress(TEST_GUILD_ID, since_date=tomorrow)
        future_ids = [t["id"] for t in future]
        self.assertNotIn(
            DatabaseTests.task_id,
            future_ids,
            "test task should not appear in tomorrow-filter result",
        )

    def test_10_mark_reminded_2day(self):
        due_date = (date.today() + timedelta(days=2)).isoformat()
        task_id_2 = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Reminder test task",
            due_date=due_date,
        )
        self.assertIsInstance(task_id_2, int, "insert_task did not return an int")
        DatabaseTests.task_id_2 = task_id_2

        mark_reminded_2day(task_id_2)
        task = get_task_by_id(task_id_2, TEST_GUILD_ID)
        self.assertIsNotNone(task, "second test task not found")
        self.assertEqual(
            task["reminded_2day"], True, "reminded_2day was not set to True"
        )
        self.assertEqual(
            task["reminded_day_of"], False, "reminded_day_of should still be False"
        )

    def test_11_mark_reminded_day_of(self):
        self.assertIsNotNone(
            DatabaseTests.task_id_2, "no task_id_2 from Test 10"
        )
        mark_reminded_day_of(DatabaseTests.task_id_2)
        task = get_task_by_id(DatabaseTests.task_id_2, TEST_GUILD_ID)
        self.assertIsNotNone(task, "second test task not found")
        self.assertEqual(
            task["reminded_day_of"], True, "reminded_day_of was not set to True"
        )

    def test_12_get_unreminded_due_tasks(self):
        due_date = (date.today() + timedelta(days=2)).isoformat()
        task_id_3 = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Due soon task",
            due_date=due_date,
        )
        self.assertIsInstance(task_id_3, int, "insert_task did not return an int")
        DatabaseTests.task_id_3 = task_id_3

        result = get_unreminded_due_tasks()
        self.assertIsInstance(result, tuple, "expected a tuple")
        self.assertEqual(
            len(result), 2, "expected tuple of (two_day_tasks, day_of_tasks)"
        )
        two_day_tasks, day_of_tasks = result
        self.assertIsInstance(two_day_tasks, list, "two_day_tasks is not a list")
        self.assertIsInstance(day_of_tasks, list, "day_of_tasks is not a list")

        two_day_ids = [t["id"] for t in two_day_tasks]
        day_of_ids = [t["id"] for t in day_of_tasks]
        self.assertIn(task_id_3, two_day_ids, "new task not in two_day_tasks")
        self.assertNotIn(
            task_id_3, day_of_ids, "new task should not be in day_of_tasks"
        )

    def test_13_delete_task(self):
        for label, tid in (
            ("task_id", DatabaseTests.task_id),
            ("task_id_2", DatabaseTests.task_id_2),
            ("task_id_3", DatabaseTests.task_id_3),
        ):
            self.assertIsNotNone(
                tid, f"{label} was None — earlier test must have failed"
            )
            delete_task(tid)
            task = get_task_by_id(tid, TEST_GUILD_ID)
            self.assertIsNone(task, f"task {tid} ({label}) still present after delete")


def _extract_reason(err_text: str) -> str:
    lines = [l for l in err_text.strip().split("\n") if l.strip()]
    if not lines:
        return "unknown error"
    last = lines[-1]
    head, sep, tail = last.partition(":")
    if sep and (head.strip().endswith("Error") or head.strip().endswith("Exception")):
        return tail.strip()[:200]
    return last[:200]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

    suite = unittest.TestSuite()
    for test_name in TEST_ORDER:
        suite.addTest(DatabaseTests(test_name))

    runner = unittest.TextTestRunner(verbosity=0, stream=io.StringIO())
    result = runner.run(suite)

    fail_map: dict[str, str] = {}
    for test, err in result.failures:
        fail_map[test.id().split(".")[-1]] = _extract_reason(err)
    for test, err in result.errors:
        fail_map[test.id().split(".")[-1]] = _extract_reason(err)

    passed = 0
    print()
    print("================================")
    print(" growth-pm-bot — Test Results")
    print("================================")
    for test_name in TEST_ORDER:
        display = TEST_NAMES[test_name]
        if test_name in fail_map:
            print(f"❌ {display}: {fail_map[test_name]}")
        else:
            print(f"✅ {display}")
            passed += 1

    total = len(TEST_ORDER)
    print("--------------------------------")
    print(f"Passed: {passed} / {total}")
    print("================================")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
