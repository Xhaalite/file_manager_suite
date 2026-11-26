"""Unit tests for safe directory diffing."""

import tempfile
import unittest
from pathlib import Path

from file_suite.diff_files import compare_directories


class TestDiffFiles(unittest.TestCase):
    def test_directory_diff_reports_added_removed_and_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"
            right = Path(tmp) / "right"
            left.mkdir()
            right.mkdir()
            (left / "same.txt").write_text("same", encoding="utf-8")
            (right / "same.txt").write_text("same", encoding="utf-8")
            (left / "changed.txt").write_text("left", encoding="utf-8")
            (right / "changed.txt").write_text("right", encoding="utf-8")
            (left / "left_only.txt").write_text("left", encoding="utf-8")
            (right / "right_only.txt").write_text("right", encoding="utf-8")

            report = compare_directories(left, right)
            self.assertEqual(report["report_type"], "directory_diff")
            differences = report["differences"]
            self.assertEqual(len(differences["only_left"]), 1)
            self.assertEqual(len(differences["only_right"]), 1)
            self.assertEqual(len(differences["changed"]), 1)
            self.assertEqual(len(differences["unchanged"]), 1)


if __name__ == "__main__":
    unittest.main()
