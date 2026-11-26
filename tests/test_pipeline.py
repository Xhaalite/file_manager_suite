"""Unit tests for file_suite.pipeline (unified app dataflow)."""

import tempfile
import unittest
from pathlib import Path
from typing import List

from file_suite.pipeline import FileSuitePipeline, ProgressEvent, ScanConfig

SAMPLE_ROOT = Path(__file__).resolve().parent.parent / "sample_data"
DISK_C = SAMPLE_ROOT / "disk_c"
DISK_D = SAMPLE_ROOT / "disk_d"


class TestPipeline(unittest.TestCase):
    def test_full_pipeline_and_session_roundtrip(self) -> None:
        events: List[ProgressEvent] = []

        with tempfile.TemporaryDirectory() as tmp:
            cfg = ScanConfig(
                directories=[str(DISK_C), str(DISK_D)],
                output_dir=tmp,
                hash_algo="sha256",
            )
            pipeline = FileSuitePipeline(cfg, on_progress=events.append)
            state = pipeline.run_all(export_xlsx=True, export_png=False)

            self.assertEqual(len(state.index_files), 2)
            self.assertIsNotNone(state.merged_index)
            self.assertIsNotNone(state.duplicates_report)
            self.assertEqual(state.duplicates_report["summary"]["duplicate_groups"], 2)
            self.assertTrue(Path(state.exported_reports[0]).exists())

            stages = [e.stage for e in events]
            self.assertIn("indexing", stages)
            self.assertIn("deduplicating", stages)
            self.assertIn("exporting", stages)
            self.assertEqual(stages[-1], "complete")

            session_file = pipeline.save_session()
            restored = FileSuitePipeline.load_session(session_file)
            self.assertEqual(
                restored.state.merged_index["summary"]["total_files"],
                state.merged_index["summary"]["total_files"],
            )
            self.assertEqual(
                restored.state.duplicates_report["summary"]["duplicate_groups"], 2
            )


if __name__ == "__main__":
    unittest.main()
