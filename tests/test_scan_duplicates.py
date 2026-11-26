"""Unit tests for file_suite.scan_duplicates using sample_data."""

import tempfile
import unittest
from pathlib import Path

from file_suite.index_metadata import index_directory
from file_suite.scan_duplicates import find_duplicates, find_duplicates_from_index
from file_suite.schema import save_json

SAMPLE_ROOT = Path(__file__).resolve().parent.parent / "sample_data"
DISK_C = SAMPLE_ROOT / "disk_c"
DISK_D = SAMPLE_ROOT / "disk_d"


class TestScanDuplicates(unittest.TestCase):
    def test_find_duplicates_across_disks(self) -> None:
        report = find_duplicates([DISK_C, DISK_D], algo="sha256")
        self.assertEqual(report["report_type"], "duplicates_report")
        groups = report["duplicate_groups"]
        # Expect exact duplicates (logo.png and quarterly_report.pdf),
        # while same_size_A.bin vs same_size_B.bin must NOT be grouped.
        grouped_names = {f["name"] for g in groups for f in g["files"]}
        self.assertIn("logo.png", grouped_names)
        self.assertIn("quarterly_report.pdf", grouped_names)
        self.assertNotIn("same_size_A.bin", grouped_names)
        self.assertNotIn("same_size_B.bin", grouped_names)
        self.assertGreater(report["summary"]["reclaimable_bytes"], 0)

    def test_find_duplicates_from_index_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            idx_c = Path(tmp) / "disk_c.json"
            idx_d = Path(tmp) / "disk_d.json"
            save_json(index_directory(DISK_C), idx_c)
            save_json(index_directory(DISK_D), idx_d)

            report = find_duplicates_from_index([idx_c, idx_d], algo="blake2b")
            self.assertEqual(report["options"]["algorithm"], "blake2b")
            self.assertEqual(report["summary"]["duplicate_groups"], 2)


if __name__ == "__main__":
    unittest.main()
