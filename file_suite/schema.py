"""
Shared data models, Windows metadata helpers, and standardized JSON envelope utilities.
All modules in file_suite read and write JSON conforming to SCHEMA_VERSION.
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import socket
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"

WINDOWS_ATTR_FLAGS: List[Tuple[str, str]] = [
    ("FILE_ATTRIBUTE_READONLY", "R"),
    ("FILE_ATTRIBUTE_HIDDEN", "H"),
    ("FILE_ATTRIBUTE_SYSTEM", "S"),
    ("FILE_ATTRIBUTE_ARCHIVE", "A"),
    ("FILE_ATTRIBUTE_COMPRESSED", "C"),
    ("FILE_ATTRIBUTE_ENCRYPTED", "E"),
    ("FILE_ATTRIBUTE_TEMPORARY", "T"),
    ("FILE_ATTRIBUTE_OFFLINE", "O"),
]

EXTENSION_CATEGORIES: Dict[str, set] = {
    "Document": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".tex"},
    "Spreadsheet": {".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".ods"},
    "Presentation": {".pptx", ".ppt", ".odp", ".key"},
    "Image": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"},
    "Archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code": {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".xml",
        ".yaml", ".yml", ".c", ".cpp", ".h", ".cs", ".java", ".go", ".rs",
        ".ps1", ".bat", ".cmd", ".sh", ".sql",
    },
    "Executable": {".exe", ".msi", ".dll", ".sys", ".com"},
}


@dataclass
class FileRecord:
    name: str
    extension: str
    category: str
    mime_type: str
    size_bytes: int
    size_human: str
    created_at: str
    modified_at: str
    accessed_at: str
    attributes: str
    is_readonly: bool
    is_hidden: bool
    drive: str
    parent_folder: str
    relative_path: str
    full_path: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DuplicateGroup:
    group_id: int
    hash_algorithm: str
    file_hash: str
    size_bytes: int
    size_human: str
    copy_count: int
    wasted_bytes: int
    wasted_human: str
    files: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def format_size(num_bytes: int) -> str:
    """Convert byte count into a human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024.0 or unit == "PB":
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def classify_file(path: Path) -> Tuple[str, str]:
    """Return (friendly_category, mime_type) for a file path."""
    ext = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    mime_str = mime or "application/octet-stream"

    for category, extensions in EXTENSION_CATEGORIES.items():
        if ext in extensions:
            return category, mime_str

    if mime:
        return mime.split("/", 1)[0].capitalize(), mime_str

    return ("File" if ext else "Unknown"), mime_str


def extract_windows_attributes(st: os.stat_result, path: Path) -> Tuple[str, bool, bool]:
    """Decode Windows file attributes, with POSIX fallback on Linux/macOS."""
    file_attrs = getattr(st, "st_file_attributes", None)
    if file_attrs is not None:
        flags = []
        for attr_name, short_code in WINDOWS_ATTR_FLAGS:
            flag_val = getattr(stat, attr_name, 0)
            if flag_val and (file_attrs & flag_val):
                flags.append(short_code)
        is_ro = bool(getattr(stat, "FILE_ATTRIBUTE_READONLY", 0) & file_attrs)
        is_hid = bool(getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0) & file_attrs) or path.name.startswith(".")
        return ("".join(flags) if flags else "-"), is_ro, is_hid

    is_ro = not bool(st.st_mode & stat.S_IWUSR)
    is_hid = path.name.startswith(".")
    return stat.filemode(st.st_mode), is_ro, is_hid


def get_creation_time_iso(st: os.stat_result) -> str:
    """Return ISO-8601 creation timestamp (local time with offset-naive precision)."""
    birth = getattr(st, "st_birthtime", None)
    ts = birth if birth is not None else st.st_ctime
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def build_envelope(
    report_type: str,
    source: str,
    options: Dict[str, Any],
    summary: Dict[str, Any],
    payload_key: str,
    payload_data: Any,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a standardized JSON envelope shared across all suite tools."""
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": report_type,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
        },
        "source": source,
        "options": options,
        "summary": summary,
        "warnings": warnings or [],
        payload_key: payload_data,
    }


def save_json(data: Dict[str, Any], output_path: Path, compact: bool = False) -> Path:
    """Write standardized JSON to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        if compact:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    return output_path


def load_json(input_path: Path) -> Dict[str, Any]:
    """Load and validate a standardized JSON file."""
    with input_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if "schema_version" not in data or "report_type" not in data:
        raise ValueError(f"'{input_path}' is not a valid file_suite JSON report.")
    return data
