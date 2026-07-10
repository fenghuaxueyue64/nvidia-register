import unittest

from ui.widgets.terminal_widget import TerminalWidget


class TerminalWidgetTests(unittest.TestCase):
    def test_info_tag_has_color_mapping(self):
        self.assertIn("info", TerminalWidget.TAG_COLORS)


if __name__ == "__main__":
    unittest.main()
