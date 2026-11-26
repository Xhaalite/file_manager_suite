"""
File Manager Suite — Modular routines for indexing Windows/PC directories,
detecting duplicate files via multi-stage hashing, and exporting reports.
"""

from .export_report import export_json_to_excel, export_json_to_image
from .index_metadata import index_directory, scan_directory
from .scan_duplicates import find_duplicates, find_duplicates_from_index
from .schema import SCHEMA_VERSION, DuplicateGroup, FileRecord, load_json, save_json

__all__ = [
    "SCHEMA_VERSION",
    "FileRecord",
    "DuplicateGroup",
    "scan_directory",
    "index_directory",
    "find_duplicates",
    "find_duplicates_from_index",
    "export_json_to_excel",
    "export_json_to_image",
    "load_json",
    "save_json",
]
