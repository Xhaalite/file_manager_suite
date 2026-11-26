"""Unit tests for file_suite.schema."""

import json
import tempfile
import unittest
from pathlib import Path

from file_suite.schema import (
    SCHEMA_VERSION,
    build_envelope,
    classify_file,
    format_size,
    load_json,
    save_json,
)


class TestSchema(unittest.TestCase):
    def test_format_size(self) -> None:
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1024 * 1024), "1.00 MB")

    def test_classify_file(self) -> None:
        cat, _ = classify_file(Path("report.pdf"))
        self.assertEqual(cat, "Document")
        cat_py, _ = classify_file(Path("app.py"))
        self.assertEqual(cat_py, "Code")
        cat_img, _ = classify_file(Path("photo.png"))
        self.assertEqual(cat_img, "Image")

    def test_save_and_load_json_envelope(self) -> None:
        env = build_envelope(
            report_type="metadata_index",
            source="/tmp/test",
            options={"recursive": True},
            summary={"total_files": 1},
            payload_key="files",
            payload_data=[{"name": "a.txt"}],
        )
        self.assertEqual(env["schema_version"], SCHEMA_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.json"
            save_json(env, out)
            loaded = load_json(out)
            self.assertEqual(loaded["report_type"], "metadata_index")
            self.assertEqual(loaded["files"][0]["name"], "a.txt")

    def test_load_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(bad)


if __name__ == "__main__":
    unittest.main()
