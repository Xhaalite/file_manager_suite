# File Manager Suite

A modular Python toolkit for indexing Windows/PC directories, detecting duplicate files across folders or drives, and exporting formatted reports. Every module reads and writes a standardized JSON schema (`schema_version: "1.0.0"`) so routines can be chained via CLI or imported directly into a unified desktop/web app later.

## Modules

- `file_suite/schema.py` — Shared `FileRecord` / `DuplicateGroup` dataclasses, Windows attribute decoders, and the standardized JSON envelope (`build_envelope`, `save_json`, `load_json`).
- `file_suite/index_metadata.py` — Walks directories/drives and outputs `metadata_index.json`.
- `file_suite/scan_duplicates.py` — 3-stage duplicate detector (size grouping → 64 KB partial hash → full SHA-256/BLAKE2b/MD5 hash) that can scan folders directly or consume multiple `metadata_index.json` files (`--from-index`).
- `file_suite/export_report.py` — Converts `metadata_index.json` and/or `duplicates_report.json` into styled `.xlsx` workbooks or `.png` previews (with large-directory warnings).
- `file_suite/diff_files.py` — Compares two directories by relative path, size, and SHA-256 content; reports left-only, right-only, changed, and unchanged files.

## Quick CLI Workflow

```bash
pip install openpyxl matplotlib

# 1. Index one or more drives/folders to standardized JSON
python -m file_suite.index_metadata "C:\Users\Alice\Documents" -o docs_index.json
python -m file_suite.index_metadata "D:\Backups" -o backups_index.json

# 2. Detect duplicates across both JSON indexes without re-walking disks
python -m file_suite.scan_duplicates --from-index docs_index.json backups_index.json -o duplicates.json

# 3. Export a combined Excel workbook
python -m file_suite.export_report --index docs_index.json --duplicates duplicates.json -o combined_report.xlsx

# 4. Compare two directories
python -m file_suite.diff_files "C:\Users\Alice\Documents" "D:\Backups" -o directory_diff.json
```

## Desktop GUI

Install the application dependencies and launch the PyQt6 desktop interface:

```bash
pip install -r requirements.txt
python -m file_suite.gui
```

The GUI starts with the included sample folders when available. Add or remove
source folders, choose scan and export options, and run the complete
indexing/duplicate-detection pipeline in the background. Results can be
filtered in the file index and duplicate tabs; saved sessions can be reopened
later.

## Importing Into a Unified App

```python
from pathlib import Path
from file_suite import index_directory, find_duplicates_from_index, export_json_to_excel

idx = index_directory(Path(r"C:\Users\Alice\Documents"))
dups = find_duplicates_from_index([Path("docs_index.json"), Path("backups_index.json")])
export_json_to_excel(Path("report.xlsx"), index_data=idx, duplicates_data=dups)
```
