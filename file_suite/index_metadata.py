"""
Metadata Indexer — Scans directories or drives and outputs a standardized JSON index.

Usage:
    python -m file_suite.index_metadata "C:\\Users\\Alice\\Documents" -o metadata_index.json
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schema import (
    FileRecord,
    build_envelope,
    classify_file,
    extract_windows_attributes,
    format_size,
    get_creation_time_iso,
    save_json,
)


def _should_exclude(path: Path, exclude_patterns: Iterable[str]) -> bool:
    name = path.name
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(path), pattern):
            return True
    return False


def scan_directory(
    root_dir: Path,
    recursive: bool = True,
    include_hidden: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    max_depth: Optional[int] = None,
) -> Tuple[List[FileRecord], List[str]]:
    """Walk `root_dir` and return (records, warnings)."""
    records: List[FileRecord] = []
    warnings: List[str] = []
    excludes = exclude_patterns or []
    root_resolved = root_dir.resolve()

    def _process_file(file_path: Path) -> None:
        if _should_exclude(file_path, excludes):
            return
        try:
            if file_path.is_symlink():
                warnings.append(f"Skipped symlink {file_path}")
                return
            st = file_path.stat()
        except (PermissionError, OSError) as exc:
            warnings.append(f"Skipped {file_path}: {exc}")
            return

        attrs, is_ro, is_hid = extract_windows_attributes(st, file_path)
        if not include_hidden and is_hid:
            return

        ext = file_path.suffix.lower() or "(none)"
        category, mime_type = classify_file(file_path)
        resolved = file_path.resolve()

        try:
            rel_path = str(resolved.relative_to(root_resolved))
        except ValueError:
            rel_path = str(resolved)

        records.append(
            FileRecord(
                name=file_path.name,
                extension=ext,
                category=category,
                mime_type=mime_type,
                size_bytes=st.st_size,
                size_human=format_size(st.st_size),
                created_at=get_creation_time_iso(st),
                modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                accessed_at=datetime.fromtimestamp(st.st_atime).isoformat(timespec="seconds"),
                attributes=attrs,
                is_readonly=is_ro,
                is_hidden=is_hid,
                drive=resolved.drive or str(resolved.anchor),
                parent_folder=str(resolved.parent),
                relative_path=rel_path,
                full_path=str(resolved),
            )
        )

    if not recursive:
        try:
            for entry in sorted(root_resolved.iterdir(), key=lambda p: p.name.lower()):
                if entry.is_file():
                    _process_file(entry)
        except (PermissionError, OSError) as exc:
            warnings.append(f"Cannot list {root_resolved}: {exc}")
        return records, warnings

    for dirpath, dirnames, filenames in os.walk(
        root_resolved, topdown=True, onerror=lambda e: warnings.append(f"Access error: {e}")
    ):
        current_dir = Path(dirpath)
        depth = len(current_dir.relative_to(root_resolved).parts)

        kept_dirs = []
        for d in sorted(dirnames, key=str.lower):
            d_path = current_dir / d
            if _should_exclude(d_path, excludes):
                continue
            if not include_hidden and d.startswith("."):
                continue
            if max_depth is not None and depth >= max_depth:
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in sorted(filenames, key=str.lower):
            _process_file(current_dir / fname)

    return records, warnings


def index_directory(
    root_dir: Path,
    recursive: bool = True,
    include_hidden: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """Scan a directory and return a standardized metadata_index JSON dictionary."""
    records, warnings = scan_directory(
        root_dir=root_dir,
        recursive=recursive,
        include_hidden=include_hidden,
        exclude_patterns=exclude_patterns,
        max_depth=max_depth,
    )

    total_bytes = sum(r.size_bytes for r in records)
    cat_counts = Counter(r.category for r in records)

    return build_envelope(
        report_type="metadata_index",
        source=str(root_dir.resolve()),
        options={
            "recursive": recursive,
            "include_hidden": include_hidden,
            "exclude_patterns": exclude_patterns or [],
            "max_depth": max_depth,
        },
        summary={
            "total_files": len(records),
            "total_bytes": total_bytes,
            "total_human": format_size(total_bytes),
            "categories": dict(cat_counts.most_common()),
            "warning_count": len(warnings),
        },
        payload_key="files",
        payload_data=[r.to_dict() for r in records],
        warnings=warnings,
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Index file metadata in a Windows/PC directory to standardized JSON."
    )
    parser.add_argument("directory", type=Path, help="Target directory or drive path to index.")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("metadata_index.json"),
        help="Output JSON file path (default: metadata_index.json).",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Scan top-level directory only.")
    parser.add_argument("--exclude-hidden", action="store_true", help="Exclude hidden files.")
    parser.add_argument("--exclude", nargs="*", default=[], help="Glob patterns to exclude.")
    parser.add_argument("--max-depth", type=int, default=None, help="Maximum folder depth.")
    parser.add_argument("--compact", action="store_true", help="Write minified JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.directory.exists() or not args.directory.is_dir():
        print(f"Error: '{args.directory}' is not an accessible directory.", file=sys.stderr)
        return 1

    payload = index_directory(
        root_dir=args.directory,
        recursive=not args.no_recursive,
        include_hidden=not args.exclude_hidden,
        exclude_patterns=args.exclude,
        max_depth=args.max_depth,
    )
    for w in payload["warnings"]:
        print(f"Warning: {w}", file=sys.stderr)

    out_path = save_json(payload, args.output, compact=args.compact)
    s = payload["summary"]
    print(f"Indexed {s['total_files']:,} file(s) ({s['total_human']}) -> {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
