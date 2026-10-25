import io
import logging
import unittest

from jarvis.application.conversation.transcript import TRANSCRIPT_LOGGER_NAME
from jarvis.bootstrap.logging_setup import configure_logging


class ConfigureLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        root = logging.getLogger()
        transcript = logging.getLogger(TRANSCRIPT_LOGGER_NAME)
        saved = (root.handlers[:], root.level, transcript.handlers[:], transcript.propagate)
        self.addCleanup(self._restore, saved)
        root.handlers.clear()
        transcript.handlers.clear()

    @staticmethod
    def _restore(saved) -> None:
        root_handlers, root_level, transcript_handlers, propagate = saved
        root = logging.getLogger()
        root.handlers[:] = root_handlers
        root.setLevel(root_level)
        transcript = logging.getLogger(TRANSCRIPT_LOGGER_NAME)
        transcript.handlers[:] = transcript_handlers
        transcript.propagate = propagate

    def test_transcript_lines_are_bare_and_not_repeated_by_the_root_logger(self) -> None:
        stream = io.StringIO()
        configure_logging(stream)

        logging.getLogger(TRANSCRIPT_LOGGER_NAME).info("Yo: %s", "hola")
        logging.getLogger("jarvis.other").info("started")

        lines = stream.getvalue().splitlines()
        self.assertEqual(lines[0], "Yo: hola")
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[1], r"^\d{4}-\d{2}-\d{2} .* INFO jarvis\.other: started$")

    def test_calling_it_twice_does_not_duplicate_transcript_lines(self) -> None:
        stream = io.StringIO()
        configure_logging(stream)
        configure_logging(stream)

        logging.getLogger(TRANSCRIPT_LOGGER_NAME).info("Gemini: %s", "hola")

        self.assertEqual(stream.getvalue().splitlines(), ["Gemini: hola"])


if __name__ == "__main__":
    unittest.main()
