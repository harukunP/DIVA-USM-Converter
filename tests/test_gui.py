import json
import os
import unittest

from diva_usm_converter.cli import main


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"),
                     "requires a Windows desktop or active X display")
class GuiSmokeTests(unittest.TestCase):
    def test_conversion_window_opens_without_removed_tabs(self):
        self.assertEqual(main(["--gui-smoke-test"]), 0)


if __name__ == "__main__":
    unittest.main()
