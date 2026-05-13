import io
import sys
import unittest
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database import (
    CLEAR,
    get_connection,
    run_migration,
    insert_task,
    get_task_by_id,
    get_tasks_by_user,
    get_all_tasks,
    update_task_status,
    update_task,
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
    "test_01_connection":                "Test 1  — Connection",
    "test_02_insert_task":               "Test 2  — Insert task",
    "test_03_get_task_by_id":            "Test 3  — Get task by ID",
    "test_04_get_tasks_by_user":         "Test 4  — Get tasks by user",
    "test_05_get_all_tasks":             "Test 5  — Get all tasks",
    "test_06_update_status_in_progress": "Test 6  — Update status: in_progress",
    "test_07_update_status_done":        "Test 7  — Update status: done",
    "test_08_update_task_name_only":     "Test 8  — update_task: name only",
    "test_09_update_task_due_only":      "Test 9  — update_task: due date only",
    "test_10_update_task_clear_due":     "Test 10 — update_task: clear due date",
    "test_11_progress_no_filter":        "Test 11 — Progress query (no filter)",
    "test_12_progress_with_filter":      "Test 12 — Progress query (since yesterday)",
    "test_13_progress_future_filter":    "Test 13 — Progress query (future, excluded)",
    "test_14_mark_reminded_2day":        "Test 14 — mark_reminded_2day",
    "test_15_mark_reminded_day_of":      "Test 15 — mark_reminded_day_of",
    "test_16_get_unreminded_due_tasks":  "Test 16 — get_unreminded_due_tasks",
    "test_17_delete_task":               "Test 17 — Delete task",
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
    # Shared state across tests
    task_id = None     # main task — used in tests 2-13
    task_id_2 = None   # reminder test task — used in tests 14-15
    task_id_3 = None   # due in 2 days (unreminded) — used in test 16
    task_id_4 = None   # due today (unreminded) — used in test 16

    @classmethod
    def setUpClass(cls):
        run_migration()
        _cleanup_test_rows()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_rows()

    # ------------------------------------------------------------------
    # Test 1 — Connection
    # ------------------------------------------------------------------
    def test_01_connection(self):
        conn = get_connection()
        self.assertIsNotNone(conn, "get_connection() returned None")
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 1, "test query SELECT 1 did not return 1")

    # ------------------------------------------------------------------
    # Test 2 — insert_task
    # ------------------------------------------------------------------
    def test_02_insert_task(self):
        due = (date.today() + timedelta(days=5)).isoformat()
        task_id = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Test task from test suite",
            due_date=due,
        )
        self.assertIsInstance(task_id, int, "insert_task did not return an int")
        self.assertGreater(task_id, 0, "task_id is not greater than 0")
        DatabaseTests.task_id = task_id

    # ------------------------------------------------------------------
    # Test 3 — get_task_by_id
    # ------------------------------------------------------------------
    def test_03_get_task_by_id(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "returned None, expected task object")
        self.assertEqual(
            task["task_name"],
            "Test task from test suite",
            f"task_name mismatch: {task['task_name']!r}",
        )
        self.assertEqual(
            task["status"], "todo",
            f"status was {task['status']!r}, expected 'todo'",
        )
        self.assertEqual(
            task["reminded_2day"], False,
            "reminded_2day should default to False",
        )
        self.assertEqual(
            task["reminded_day_of"], False,
            "reminded_day_of should default to False",
        )

    # ------------------------------------------------------------------
    # Test 4 — get_tasks_by_user
    # ------------------------------------------------------------------
    def test_04_get_tasks_by_user(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        tasks = get_tasks_by_user(TEST_GUILD_ID, TEST_USER_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        ids = [t["id"] for t in tasks]
        self.assertIn(DatabaseTests.task_id, ids, "inserted task_id not in result")

    # ------------------------------------------------------------------
    # Test 5 — get_all_tasks
    # ------------------------------------------------------------------
    def test_05_get_all_tasks(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        tasks = get_all_tasks(TEST_GUILD_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        ids = [t["id"] for t in tasks]
        self.assertIn(DatabaseTests.task_id, ids, "inserted task_id not in result")

    # ------------------------------------------------------------------
    # Test 6 — update_task_status to in_progress
    # ------------------------------------------------------------------
    def test_06_update_status_in_progress(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        update_task_status(DatabaseTests.task_id, "in_progress")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "task not found after status update")
        self.assertEqual(
            task["status"], "in_progress",
            f"status was {task['status']!r}, expected 'in_progress'",
        )

    # ------------------------------------------------------------------
    # Test 7 — update_task_status to done
    # ------------------------------------------------------------------
    def test_07_update_status_done(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        update_task_status(DatabaseTests.task_id, "done")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNotNone(task, "task not found after status update")
        self.assertEqual(
            task["status"], "done",
            f"status was {task['status']!r}, expected 'done'",
        )

    # ------------------------------------------------------------------
    # Test 8 — update_task: task_name only, due_date unchanged
    # ------------------------------------------------------------------
    def test_08_update_task_name_only(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        original = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        original_due = original["due_date"]

        update_task(DatabaseTests.task_id, task_name="Updated task name")
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)

        self.assertEqual(
            task["task_name"], "Updated task name",
            f"task_name was {task['task_name']!r}, expected 'Updated task name'",
        )
        self.assertEqual(
            task["due_date"], original_due,
            f"due_date changed unexpectedly to {task['due_date']!r}",
        )

    # ------------------------------------------------------------------
    # Test 9 — update_task: due_date only, task_name unchanged
    # ------------------------------------------------------------------
    def test_09_update_task_due_only(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        new_due = date.today() + timedelta(days=10)
        update_task(DatabaseTests.task_id, due_date=new_due)
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)

        self.assertEqual(
            task["due_date"], new_due,
            f"due_date was {task['due_date']!r}, expected {new_due!r}",
        )
        self.assertEqual(
            task["task_name"], "Updated task name",
            f"task_name changed unexpectedly to {task['task_name']!r}",
        )

    # ------------------------------------------------------------------
    # Test 10 — update_task: CLEAR sentinel sets due_date to NULL
    # ------------------------------------------------------------------
    def test_10_update_task_clear_due(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        update_task(DatabaseTests.task_id, due_date=CLEAR)
        task = get_task_by_id(DatabaseTests.task_id, TEST_GUILD_ID)
        self.assertIsNone(
            task["due_date"],
            f"due_date should be NULL but was {task['due_date']!r}",
        )

    # ------------------------------------------------------------------
    # Test 11 — get_tasks_for_progress, no date filter
    # ------------------------------------------------------------------
    def test_11_progress_no_filter(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        tasks = get_tasks_for_progress(TEST_GUILD_ID)
        self.assertIsInstance(tasks, list, "result is not a list")
        ids = [t["id"] for t in tasks]
        self.assertIn(DatabaseTests.task_id, ids, "test task missing from result")

    # ------------------------------------------------------------------
    # Test 12 — get_tasks_for_progress, since_date=yesterday (task included)
    # ------------------------------------------------------------------
    def test_12_progress_with_filter(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        yesterday = date.today() - timedelta(days=1)
        tasks = get_tasks_for_progress(TEST_GUILD_ID, since_date=yesterday)
        ids = [t["id"] for t in tasks]
        self.assertIn(
            DatabaseTests.task_id, ids,
            "test task missing from yesterday-filtered result",
        )

    # ------------------------------------------------------------------
    # Test 13 — get_tasks_for_progress, since_date=far future (task excluded)
    # ------------------------------------------------------------------
    def test_13_progress_future_filter(self):
        self.assertIsNotNone(DatabaseTests.task_id, "no task_id from Test 2")
        # Use a date far enough out that no timezone offset can bridge the gap
        far_future = date.today() + timedelta(days=365)
        tasks = get_tasks_for_progress(TEST_GUILD_ID, since_date=far_future)
        ids = [t["id"] for t in tasks]
        self.assertNotIn(
            DatabaseTests.task_id, ids,
            "test task should not appear with a far-future since_date filter",
        )

    # ------------------------------------------------------------------
    # Test 14 — mark_reminded_2day
    # ------------------------------------------------------------------
    def test_14_mark_reminded_2day(self):
        due = (date.today() + timedelta(days=2)).isoformat()
        task_id_2 = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Reminder test task",
            due_date=due,
        )
        self.assertIsInstance(task_id_2, int, "insert_task did not return int")
        DatabaseTests.task_id_2 = task_id_2

        mark_reminded_2day(task_id_2)
        task = get_task_by_id(task_id_2, TEST_GUILD_ID)
        self.assertIsNotNone(task, "reminder test task not found")
        self.assertEqual(
            task["reminded_2day"], True,
            "reminded_2day was not set to True",
        )
        self.assertEqual(
            task["reminded_day_of"], False,
            "reminded_day_of should still be False",
        )

    # ------------------------------------------------------------------
    # Test 15 — mark_reminded_day_of
    # ------------------------------------------------------------------
    def test_15_mark_reminded_day_of(self):
        self.assertIsNotNone(DatabaseTests.task_id_2, "no task_id_2 from Test 14")
        mark_reminded_day_of(DatabaseTests.task_id_2)
        task = get_task_by_id(DatabaseTests.task_id_2, TEST_GUILD_ID)
        self.assertIsNotNone(task, "reminder test task not found")
        self.assertEqual(
            task["reminded_day_of"], True,
            "reminded_day_of was not set to True",
        )

    # ------------------------------------------------------------------
    # Test 16 — get_unreminded_due_tasks
    # ------------------------------------------------------------------
    def test_16_get_unreminded_due_tasks(self):
        # Fetch the server's CURRENT_DATE so due_date values match DB-side comparisons
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT CURRENT_DATE, CURRENT_DATE + 2")
                row = cur.fetchone()
                server_today = row[0]
                server_2day = row[1]
        finally:
            conn.close()

        # Insert a task due in exactly 2 days (unreminded)
        due_2day = server_2day.isoformat()
        task_id_3 = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Due in 2 days task",
            due_date=due_2day,
        )
        self.assertIsInstance(task_id_3, int, "insert_task did not return int")
        DatabaseTests.task_id_3 = task_id_3

        # Insert a task due today (unreminded)
        due_today = server_today.isoformat()
        task_id_4 = insert_task(
            guild_id=TEST_GUILD_ID,
            assignee_id=TEST_USER_ID,
            assigner_id=TEST_ADMIN_ID,
            task_name="Due today task",
            due_date=due_today,
        )
        self.assertIsInstance(task_id_4, int, "insert_task did not return int")
        DatabaseTests.task_id_4 = task_id_4

        result = get_unreminded_due_tasks()

        self.assertIsInstance(result, tuple, "expected a tuple")
        self.assertEqual(len(result), 2, "expected (two_day_tasks, day_of_tasks)")
        two_day_tasks, day_of_tasks = result
        self.assertIsInstance(two_day_tasks, list, "two_day_tasks is not a list")
        self.assertIsInstance(day_of_tasks, list, "day_of_tasks is not a list")

        two_day_ids = [t["id"] for t in two_day_tasks]
        day_of_ids = [t["id"] for t in day_of_tasks]

        self.assertIn(task_id_3, two_day_ids, "2-day task not in two_day_tasks")
        self.assertNotIn(task_id_3, day_of_ids, "2-day task should not be in day_of_tasks")
        self.assertIn(task_id_4, day_of_ids, "today task not in day_of_tasks")
        self.assertNotIn(task_id_4, two_day_ids, "today task should not be in two_day_tasks")

    # ------------------------------------------------------------------
    # Test 17 — delete_task
    # ------------------------------------------------------------------
    def test_17_delete_task(self):
        for label, tid in (
            ("task_id",   DatabaseTests.task_id),
            ("task_id_2", DatabaseTests.task_id_2),
            ("task_id_3", DatabaseTests.task_id_3),
            ("task_id_4", DatabaseTests.task_id_4),
        ):
            self.assertIsNotNone(tid, f"{label} was None — earlier test must have failed")
            delete_task(tid)
            task = get_task_by_id(tid, TEST_GUILD_ID)
            self.assertIsNone(task, f"{label} ({tid}) still present after delete")


# ----------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------

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
