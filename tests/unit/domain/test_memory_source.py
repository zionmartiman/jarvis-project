import unittest

from jarvis.domain.memory_source import MemorySource


class MemorySourceTest(unittest.TestCase):
    def test_which_flows_each_value_includes(self) -> None:
        expected = {
            MemorySource.NONE: (False, False),
            MemorySource.CONVERSATION_LOG: (True, False),
            MemorySource.GRAPH: (False, True),
            MemorySource.BOTH: (True, True),
        }

        for source, (log, graph) in expected.items():
            with self.subTest(source=source):
                self.assertEqual((source.includes_log, source.includes_graph), (log, graph))

    def test_values_are_the_names_to_write_in_the_settings(self) -> None:
        self.assertEqual(
            [source.value for source in MemorySource], ["none", "conversation_log", "graph", "both"]
        )


if __name__ == "__main__":
    unittest.main()
