"""Unit tests for file_suite.index_metadata using sample_data."""

import unittest
from pathlib import Path

from file_suite.index_metadata import index_directory, scan_directory

SAMPLE_DISK_C = Path(__file__).resolve().parent.parent / "sample_data" / "disk_c"


class TestIndexMetadata(unittest.TestCase):
    def test_recursive_scan_finds_nested_files(self) -> None:
        records, warnings = scan_directory(SAMPLE_DISK_C, recursive=True)
        self.assertEqual(warnings, [])
        names = {r.name for r in records}
        self.assertIn("notes.txt", names)
        self.assertIn("quarterly_report.pdf", names)
        self.assertIn("budget.csv", names)

    def test_non_recursive_scan_top_level_only(self) -> None:
        records, _ = scan_directory(SAMPLE_DISK_C, recursive=False)
        names = {r.name for r in records}
        self.assertIn("readme.md", names)
        self.assertNotIn("quarterly_report.pdf", names)

    def test_exclude_pattern_and_hidden(self) -> None:
        records, _ = scan_directory(
            SAMPLE_DISK_C,
            recursive=True,
            include_hidden=False,
            exclude_patterns=["*.tmp"],
        )
        names = {r.name for r in records}
        self.assertNotIn("temp_cache.tmp", names)
        self.assertNotIn(".secret_config", names)

    def test_index_directory_json_structure(self) -> None:
        payload = index_directory(SAMPLE_DISK_C)
        self.assertEqual(payload["report_type"], "metadata_index")
        self.assertGreater(payload["summary"]["total_files"], 0)
        self.assertEqual(len(payload["files"]), payload["summary"]["total_files"])


if __name__ == "__main__":
    unittest.main()
