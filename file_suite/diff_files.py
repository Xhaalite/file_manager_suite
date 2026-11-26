"""Directory diffing with safe path containment and SHA-based content comparison."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from .index_metadata import scan_directory
from .schema import build_envelope, save_json
from .security import resolve_regular_file


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_directories(
    left: Path,
    right: Path,
    recursive: bool = True,
    include_hidden: bool = True,
    exclude_patterns: Optional[List[str]] = None,
    algo: str = "sha256",
) -> Dict[str, Any]:
    """Compare two directories by relative path, size, and content hash."""
    if algo != "sha256":
        raise ValueError("Directory diff currently supports sha256 only.")

    left_root = left.resolve(strict=True)
    right_root = right.resolve(strict=True)
    if not left_root.is_dir() or not right_root.is_dir():
        raise ValueError("Both diff roots must be existing directories.")

    left_records, left_warnings = scan_directory(
        left_root, recursive=recursive, include_hidden=include_hidden,
        exclude_patterns=exclude_patterns,
    )
    right_records, right_warnings = scan_directory(
        right_root, recursive=recursive, include_hidden=include_hidden,
        exclude_patterns=exclude_patterns,
    )
    warnings = left_warnings + right_warnings

    left_map = {record.relative_path: record.to_dict() for record in left_records}
    right_map = {record.relative_path: record.to_dict() for record in right_records}
    only_left: List[Dict[str, Any]] = []
    only_right: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []
    unchanged: List[Dict[str, Any]] = []

    for rel in sorted(set(left_map) | set(right_map), key=str.lower):
        left_item = left_map.get(rel)
        right_item = right_map.get(rel)
        if left_item and not right_item:
            only_left.append({"relative_path": rel, "left": left_item})
        elif right_item and not left_item:
            only_right.append({"relative_path": rel, "right": right_item})
        else:
            assert left_item is not None and right_item is not None
            left_path = resolve_regular_file(Path(left_item["full_path"]), [left_root])
            right_path = resolve_regular_file(Path(right_item["full_path"]), [right_root])
            hashes_match = (
                left_item["size_bytes"] == right_item["size_bytes"]
                and _sha256(left_path) == _sha256(right_path)
            )
            entry = {
                "relative_path": rel,
                "left": left_item,
                "right": right_item,
            }
            (unchanged if hashes_match else changed).append(entry)

    return build_envelope(
        report_type="directory_diff",
        source=f"{left_root} <> {right_root}",
        options={
            "recursive": recursive,
            "include_hidden": include_hidden,
            "exclude_patterns": exclude_patterns or [],
            "algorithm": algo,
        },
        summary={
            "only_left": len(only_left),
            "only_right": len(only_right),
            "changed": len(changed),
            "unchanged": len(unchanged),
            "total_differences": len(only_left) + len(only_right) + len(changed),
        },
        payload_key="differences",
        payload_data={
            "only_left": only_left,
            "only_right": only_right,
            "changed": changed,
            "unchanged": unchanged,
        },
        warnings=warnings,
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two directories safely.")
    parser.add_argument("left", type=Path, help="Left directory.")
    parser.add_argument("right", type=Path, help="Right directory.")
    parser.add_argument("-o", "--output", type=Path, default=Path("directory_diff.json"))
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--exclude-hidden", action="store_true")
    parser.add_argument("--exclude", nargs="*", default=[], help="Glob patterns to exclude.")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    report = compare_directories(
        args.left,
        args.right,
        recursive=not args.no_recursive,
        include_hidden=not args.exclude_hidden,
        exclude_patterns=args.exclude,
    )
    out = save_json(report, args.output, compact=args.compact)
    summary = report["summary"]
    print(
        f"Found {summary['total_differences']:,} difference(s): "
        f"{summary['only_left']} left-only, {summary['only_right']} right-only, "
        f"{summary['changed']} changed -> {out.resolve()}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
