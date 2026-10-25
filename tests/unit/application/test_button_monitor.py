import unittest

from jarvis.application.button_monitor import ButtonMonitor
from jarvis.ports.hardware import ButtonPanel, ButtonPress


class FakePanel(ButtonPanel):
    def __init__(self, *presses: ButtonPress | None) -> None:
        self.presses = list(presses)

    def read_pending_press(self) -> ButtonPress | None:
        return self.presses.pop(0)


class ButtonMonitorTest(unittest.TestCase):
    def test_each_press_calls_its_own_handler(self) -> None:
        calls: list[str] = []
        monitor = ButtonMonitor(
            FakePanel(ButtonPress.SHUTDOWN, ButtonPress.INTERRUPT, None),
            {
                ButtonPress.SHUTDOWN: lambda: calls.append("shutdown"),
                ButtonPress.INTERRUPT: lambda: calls.append("interrupt"),
            },
            poll_interval_seconds=0.1,
        )

        with self.assertLogs("jarvis.application.button_monitor", level="INFO"):
            monitor.poll_once()
            monitor.poll_once()
        monitor.poll_once()

        self.assertEqual(calls, ["shutdown", "interrupt"])

    def test_a_press_without_a_handler_is_ignored(self) -> None:
        monitor = ButtonMonitor(FakePanel(ButtonPress.INTERRUPT), {}, poll_interval_seconds=0.1)

        with self.assertLogs("jarvis.application.button_monitor", level="INFO"):
            monitor.poll_once()

    def test_a_failing_handler_is_logged_and_does_not_propagate(self) -> None:
        calls: list[str] = []

        def failing() -> None:
            raise RuntimeError("boom")

        monitor = ButtonMonitor(
            FakePanel(ButtonPress.SHUTDOWN, ButtonPress.INTERRUPT),
            {ButtonPress.SHUTDOWN: failing, ButtonPress.INTERRUPT: lambda: calls.append("ok")},
            poll_interval_seconds=0.1,
        )

        with self.assertLogs("jarvis.application.button_monitor", level="ERROR"):
            monitor.poll_once()
        monitor.poll_once()

        self.assertEqual(calls, ["ok"])

    def test_start_and_close_do_not_raise(self) -> None:
        monitor = ButtonMonitor(FakePanel(*([None] * 1000)), {}, poll_interval_seconds=0.001)

        monitor.start()
        monitor.close()


if __name__ == "__main__":
    unittest.main()
