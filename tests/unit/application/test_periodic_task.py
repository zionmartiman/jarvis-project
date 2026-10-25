import threading
import unittest

from jarvis.application.periodic_task import PeriodicTask


class PeriodicTaskTest(unittest.TestCase):
    def test_runs_the_action_repeatedly_until_closed(self) -> None:
        calls = []
        enough_calls = threading.Event()

        def action() -> None:
            calls.append(1)
            if len(calls) >= 3:
                enough_calls.set()

        task = PeriodicTask("test-task", 0.001, action)
        task.start()
        self.assertTrue(enough_calls.wait(timeout=2))
        task.close()

        count_after_close = len(calls)
        self.assertGreaterEqual(count_after_close, 3)
        threading.Event().wait(0.05)
        self.assertEqual(len(calls), count_after_close)

    def test_start_is_idempotent(self) -> None:
        started = threading.Event()
        task = PeriodicTask("test-task", 60, started.set)

        task.start()
        self.assertTrue(started.wait(timeout=2))
        thread = task._thread
        task.start()
        self.assertIs(task._thread, thread)
        task.close()

    def test_a_failing_action_is_logged_and_the_loop_continues(self) -> None:
        attempts = []
        recovered = threading.Event()

        def action() -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("boom")
            recovered.set()

        task = PeriodicTask("test-task", 0.001, action)
        with self.assertLogs("jarvis.application.periodic_task", level="ERROR"):
            task.start()
            self.assertTrue(recovered.wait(timeout=2))
            task.close()

    def test_can_be_restarted_after_close(self) -> None:
        runs = []
        task = PeriodicTask("test-task", 60, lambda: runs.append(1))
        task.start()
        task.close()
        task.start()
        task.close()

        self.assertEqual(len(runs), 2)

    def test_close_without_start_does_nothing(self) -> None:
        PeriodicTask("test-task", 1, lambda: None).close()


if __name__ == "__main__":
    unittest.main()
