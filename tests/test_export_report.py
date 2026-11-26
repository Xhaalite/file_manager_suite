"""Unit tests for file_suite.export_report."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from openpyxl import load_workbook

from file_suite.export_report import export_json_to_excel, export_json_to_image
from file_suite.index_metadata import index_directory
from file_suite.scan_duplicates import find_duplicates

SAMPLE_ROOT = Path(__file__).resolve().parent.parent/"sample_data"
DISK_C = SAMPLE_ROOT / "disk_c"
DISK_D = SAMPLE_ROOT / "disk_d"


class TestExportReport(unittest.TestCase):
    def test_export_json_to_excel_creates_all_sheets(self) -> None:
        idx = index_directory(DISK_C)
        dups = find_duplicates([DISK_C, DISK_D])

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "suite_report.xlsx"
            export_json_to_excel(xlsx_path, index_data=idx, duplicates_data=dups)
            self.assertTrue(xlsx_path.exists())

            wb = load_workbook(xlsx_path)
            self.assertEqual(wb.sheetnames, ["File Index", "Duplicate Groups", "Summary"])
            self.assertGreater(wb["File Index"].max_row, 1)
            self.assertGreater(wb["Duplicate Groups"].max_row, 1)

    def test_excel_formula_prefixes_are_stored_as_text(self) -> None:
        idx = index_directory(DISK_C)
        idx["files"][0]["name"] = "=HYPERLINK(\"https://example.test\")"
        idx["source"] = "@untrusted-source"

        with tempfile.TemporaryDirectory() as tmp:
            xlsx_path = Path(tmp) / "suite_report.xlsx"
            export_json_to_excel(xlsx_path, index_data=idx)
            wb = load_workbook(xlsx_path)
            name_cell = wb["File Index"].cell(row=2, column=1)
            source_cell = wb["Summary"]["B3"]
            self.assertEqual(name_cell.data_type, "s")
            self.assertTrue(str(name_cell.value).startswith("'"))
            self.assertEqual(source_cell.data_type, "s")

    def test_export_json_to_image_warns_and_skips_when_too_large(self) -> None:
        idx = index_directory(DISK_C)
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "preview.png"
            stderr_buf = io.StringIO()
            with redirect_stderr(stderr_buf):
                written = export_json_to_image(
                    png_path, idx, max_rows=2, skip_if_too_large=True
                )
            self.assertFalse(written)
            self.assertFalse(png_path.exists())
            self.assertIn("Warning:", stderr_buf.getvalue())

            png_path2 = Path(tmp) / "preview_ok.png"
            written2 = export_json_to_image(png_path2, idx, max_rows=50)
            self.assertTrue(written2)
            self.assertTrue(png_path2.exists())


if __name__ == "__main__":
    unittest.main()
