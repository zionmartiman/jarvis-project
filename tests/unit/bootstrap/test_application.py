import unittest

from jarvis.bootstrap.app import Application


class RecordingComponent:
    def __init__(self, name: str, events: list[str], fail_on_start: bool = False) -> None:
        self._name = name
        self._events = events
        self._fail_on_start = fail_on_start

    def start(self) -> None:
        if self._fail_on_start:
            raise RuntimeError(f"{self._name} cannot start")
        self._events.append(f"start {self._name}")

    def close(self) -> None:
        self._events.append(f"close {self._name}")


class RecordingMicrophone:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __enter__(self) -> "RecordingMicrophone":
        self._events.append("microphone on")
        return self

    def __exit__(self, *args) -> None:
        self._events.append("microphone off")


class RecordingOrchestrator:
    def __init__(self, events: list[str], error: BaseException | None = None) -> None:
        self._events = events
        self._error = error

    def run_forever(self) -> None:
        self._events.append("conversation")
        if self._error is not None:
            raise self._error


class ApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[str] = []

    def application(self, orchestrator=None, components=None) -> Application:
        return Application(
            orchestrator or RecordingOrchestrator(self.events),
            RecordingMicrophone(self.events),
            components
            or [RecordingComponent("a", self.events), RecordingComponent("b", self.events)],
        )

    def test_components_start_in_order_and_close_in_reverse(self) -> None:
        self.application().run()

        self.assertEqual(
            self.events,
            [
                "start a",
                "start b",
                "microphone on",
                "conversation",
                "microphone off",
                "close b",
                "close a",
            ],
        )

    def test_components_are_closed_when_the_conversation_is_interrupted(self) -> None:
        application = self.application(RecordingOrchestrator(self.events, KeyboardInterrupt()))

        with self.assertRaises(KeyboardInterrupt):
            application.run()

        self.assertEqual(self.events[-3:], ["microphone off", "close b", "close a"])

    def test_only_the_components_that_started_are_closed(self) -> None:
        application = self.application(
            components=[
                RecordingComponent("a", self.events),
                RecordingComponent("b", self.events, fail_on_start=True),
                RecordingComponent("c", self.events),
            ]
        )

        with self.assertRaises(RuntimeError):
            application.run()

        self.assertEqual(self.events, ["start a", "close a"])

    def test_the_ready_message_is_logged_once_everything_is_running(self) -> None:
        with self.assertLogs("jarvis.bootstrap.app", level="INFO") as logs:
            self.application().run()

        self.assertEqual(logs.output, ['INFO:jarvis.bootstrap.app:Jarvis voice is ready. Say "Jarvis".'])


if __name__ == "__main__":
    unittest.main()
