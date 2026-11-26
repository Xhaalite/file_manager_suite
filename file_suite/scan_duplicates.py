"""
Duplicate File Hash Scanner — Multi-stage duplicate detector outputting standardized JSON.

Uses a 3-stage pipeline for speed on massive collections:
  1. Group by exact byte size (unique sizes are skipped immediately).
  2. Partial hash (first 64 KB + last 64 KB) for size-colliding files.
  3. Full cryptographic hash (SHA-256 by default) only on partial-hash matches.

Can scan directories directly OR consume one or more existing `metadata_index.json` files.

Usage:
    python -m file_suite.scan_duplicates "C:\\Data" "D:\\Backup" -o duplicates.json
    python -m file_suite.scan_duplicates --from-index disk_c.json disk_d.json -o duplicates.json
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .index_metadata import scan_directory
from .schema import DuplicateGroup, build_envelope, format_size, load_json, save_json

CHUNK_SIZE = 65536  # 64 KB


def compute_partial_hash(path: Path, algo: str = "sha256", sample_bytes: int = CHUNK_SIZE) -> str:
    """Hash the first and last `sample_bytes` of a file for fast pre-filtering."""
    h = hashlib.new(algo)
    size = path.stat().st_size
    with path.open("rb") as fh:
        h.update(fh.read(sample_bytes))
        if size > sample_bytes:
            fh.seek(max(size - sample_bytes, sample_bytes))
            h.update(fh.read(sample_bytes))
    return h.hexdigest()


def compute_full_hash(path: Path, algo: str = "sha256", chunk_size: int = 1048576) -> str:
    """Stream-hash the entire file (1 MB chunks)."""
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _detect_duplicates_from_entries(
    entries: List[Dict[str, Any]],
    source_desc: str,
    algo: str = "sha256",
    min_size: int = 1,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    warn_list = list(warnings or [])

    # Stage 1: Group by file size
    by_size: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for item in entries:
        size = int(item["size_bytes"])
        if size >= min_size:
            by_size[size].append(item)

    size_candidates = {sz: items for sz, items in by_size.items() if len(items) > 1}

    # Stage 2: Partial hash
    by_partial: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for sz, items in size_candidates.items():
        for item in items:
            p = Path(item["full_path"])
            try:
                phash = compute_partial_hash(p, algo=algo)
                by_partial[(sz, phash)].append(item)
            except (PermissionError, OSError) as exc:
                warn_list.append(f"Hash skipped {p}: {exc}")

    # Stage 3: Full hash on partial-hash collisions
    by_full: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for (sz, _), items in by_partial.items():
        if len(items) < 2:
            continue
        for item in items:
            p = Path(item["full_path"])
            try:
                fhash = compute_full_hash(p, algo=algo)
                by_full[(sz, fhash)].append(item)
            except (PermissionError, OSError) as exc:
                warn_list.append(f"Full hash skipped {p}: {exc}")

    groups: List[DuplicateGroup] = []
    sorted_matches = sorted(
        ((k, v) for k, v in by_full.items() if len(v) > 1),
        key=lambda kv: kv[0][0] * (len(kv[1]) - 1),
        reverse=True,
    )

    total_dup_files = 0
    total_wasted = 0
    for idx, ((sz, fhash), items) in enumerate(sorted_matches, start=1):
        items_sorted = sorted(items, key=lambda x: x["full_path"].lower())
        wasted = sz * (len(items_sorted) - 1)
        total_dup_files += len(items_sorted)
        total_wasted += wasted
        groups.append(
            DuplicateGroup(
                group_id=idx,
                hash_algorithm=algo,
                file_hash=fhash,
                size_bytes=sz,
                size_human=format_size(sz),
                copy_count=len(items_sorted),
                wasted_bytes=wasted,
                wasted_human=format_size(wasted),
                files=items_sorted,
            )
        )

    return build_envelope(
        report_type="duplicates_report",
        source=source_desc,
        options={"algorithm": algo, "min_size_bytes": min_size},
        summary={
            "total_files_evaluated": len(entries),
            "duplicate_groups": len(groups),
            "total_duplicate_files": total_dup_files,
            "reclaimable_bytes": total_wasted,
            "reclaimable_human": format_size(total_wasted),
            "warning_count": len(warn_list),
        },
        payload_key="duplicate_groups",
        payload_data=[g.to_dict() for g in groups],
        warnings=warn_list,
    )


def find_duplicates(
    directories: List[Path],
    algo: str = "sha256",
    min_size: int = 1,
    recursive: bool = True,
    exclude_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Scan one or more directories and return a standardized duplicates_report JSON dict."""
    all_entries: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    seen_paths = set()

    for d in directories:
        records, warns = scan_directory(
            root_dir=d,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
        )
        all_warnings.extend(warns)
        for r in records:
            if r.full_path not in seen_paths:
                seen_paths.add(r.full_path)
                all_entries.append(r.to_dict())

    return _detect_duplicates_from_entries(
        entries=all_entries,
        source_desc=", ".join(str(d.resolve()) for d in directories),
        algo=algo,
        min_size=min_size,
        warnings=all_warnings,
    )


def find_duplicates_from_index(
    index_paths: List[Path],
    algo: str = "sha256",
    min_size: int = 1,
) -> Dict[str, Any]:
    """Load one or more metadata_index.json files and detect duplicates across them."""
    all_entries: List[Dict[str, Any]] = []
    seen_paths = set()

    for idx_path in index_paths:
        data = load_json(idx_path)
        if data.get("report_type") != "metadata_index":
            raise ValueError(f"'{idx_path}' has report_type '{data.get('report_type')}', expected 'metadata_index'.")
        for item in data.get("files", []):
            fp = item["full_path"]
            if fp not in seen_paths:
                seen_paths.add(fp)
                all_entries.append(item)

    return _detect_duplicates_from_entries(
        entries=all_entries,
        source_desc=", ".join(str(p.resolve()) for p in index_paths),
        algo=algo,
        min_size=min_size,
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect duplicate files using multi-stage hashing and output standardized JSON."
    )
    parser.add_argument("directories", nargs="*", type=Path, help="One or more directories to scan.")
    parser.add_argument(
        "--from-index", nargs="+", type=Path, default=None,
        help="Scan files listed in one or more metadata_index.json files instead of walking folders.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("duplicates_report.json"),
        help="Output JSON file path (default: duplicates_report.json).",
    )
    parser.add_argument(
        "--algo", choices=("sha256", "blake2b", "md5"), default="sha256",
        help="Hash algorithm (default: sha256).",
    )
    parser.add_argument(
        "--min-size", type=int, default=1,
        help="Minimum file size in bytes to consider (default: 1, skips empty files).",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Scan top-level directories only.")
    parser.add_argument("--exclude", nargs="*", default=[], help="Glob patterns to exclude.")
    parser.add_argument("--compact", action="store_true", help="Write minified JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.from_index:
        payload = find_duplicates_from_index(args.from_index, algo=args.algo, min_size=args.min_size)
    elif args.directories:
        for d in args.directories:
            if not d.exists() or not d.is_dir():
                print(f"Error: '{d}' is not an accessible directory.", file=sys.stderr)
                return 1
        payload = find_duplicates(
            directories=args.directories,
            algo=args.algo,
            min_size=args.min_size,
            recursive=not args.no_recursive,
            exclude_patterns=args.exclude,
        )
    else:
        print("Error: Provide directory paths or --from-index <json>.", file=sys.stderr)
        return 1

    for w in payload["warnings"]:
        print(f"Warning: {w}", file=sys.stderr)

    out_path = save_json(payload, args.output, compact=args.compact)
    s = payload["summary"]
    print(
        f"Found {s['duplicate_groups']:,} duplicate group(s) "
        f"({s['total_duplicate_files']:,} files, {s['reclaimable_human']} reclaimable) "
        f"-> {out_path.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
