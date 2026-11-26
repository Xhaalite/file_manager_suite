"""
Unified Dataflow & Pipeline Orchestrator for File Manager Suite.

Provides a UI-agnostic controller (`FileSuitePipeline`) with structured
`ProgressEvent` callbacks so a PyQt GUI (via QThread/QRunnable signals),
CLI, or batch script can drive indexing, duplicate detection, and exporting
without blocking or coupling to UI code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .export_report import export_json_to_excel, export_json_to_image
from .index_metadata import index_directory
from .scan_duplicates import find_duplicates_from_index
from .schema import SCHEMA_VERSION, build_envelope, format_size, load_json, save_json


@dataclass
class ScanConfig:
    directories: List[str]
    output_dir: str = "./suite_output"
    recursive: bool = True
    include_hidden: bool = True
    exclude_patterns: List[str] = field(default_factory=list)
    max_depth: Optional[int] = None
    hash_algo: str = "sha256"
    min_size_bytes: int = 1


@dataclass
class ProgressEvent:
    stage: str          # "indexing" | "deduplicating" | "exporting" | "complete"
    message: str
    step: int
    total_steps: int


@dataclass
class AppState:
    config: ScanConfig
    index_files: List[str] = field(default_factory=list)
    merged_index: Optional[Dict[str, Any]] = None
    duplicates_report: Optional[Dict[str, Any]] = None
    exported_reports: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_session_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "config": asdict(self.config),
            "index_files": self.index_files,
            "duplicates_report_path": (
                str(Path(self.config.output_dir) / "duplicates_report.json")
                if self.duplicates_report
                else None
            ),
            "exported_reports": self.exported_reports,
            "warnings": self.warnings,
        }


ProgressCallback = Optional[Callable[[ProgressEvent], None]]


class FileSuitePipeline:
    """Coordinates metadata indexing, duplicate scanning, and report exporting."""

    def __init__(self, config: ScanConfig, on_progress: ProgressCallback = None) -> None:
        self.state = AppState(config=config)
        self._on_progress = on_progress

    def _emit(self, stage: str, message: str, step: int, total_steps: int) -> None:
        if self._on_progress is not None:
            self._on_progress(ProgressEvent(stage=stage, message=message, step=step, total_steps=total_steps))

    def run_index(self) -> Dict[str, Any]:
        """Index all configured directories, write per-source JSONs and a merged index."""
        out_dir = Path(self.state.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        dirs = [Path(d) for d in self.state.config.directories]
        if not dirs:
            raise ValueError("ScanConfig.directories must contain at least one directory.")

        total = len(dirs)
        self.state.index_files.clear()
        all_files: List[Dict[str, Any]] = []
        all_warnings: List[str] = []
        cat_totals: Dict[str, int] = {}

        for idx, d in enumerate(dirs, start=1):
            if not d.exists() or not d.is_dir():
                raise FileNotFoundError(f"Directory not found or inaccessible: {d}")
            self._emit("indexing", f"Indexing {d}...", idx, total)

            payload = index_directory(
                root_dir=d,
                recursive=self.state.config.recursive,
                include_hidden=self.state.config.include_hidden,
                exclude_patterns=self.state.config.exclude_patterns,
                max_depth=self.state.config.max_depth,
            )
            json_path = out_dir / f"index_{idx}_{d.name or 'root'}.json"
            save_json(payload, json_path)
            self.state.index_files.append(str(json_path.resolve()))

            all_files.extend(payload.get("files", []))
            all_warnings.extend(payload.get("warnings", []))
            for cat, count in payload["summary"].get("categories", {}).items():
                cat_totals[cat] = cat_totals.get(cat, 0) + count

        total_bytes = sum(f["size_bytes"] for f in all_files)
        merged = build_envelope(
            report_type="metadata_index",
            source=", ".join(str(d.resolve()) for d in dirs),
            options={
                "recursive": self.state.config.recursive,
                "include_hidden": self.state.config.include_hidden,
                "exclude_patterns": self.state.config.exclude_patterns,
                "max_depth": self.state.config.max_depth,
            },
            summary={
                "total_files": len(all_files),
                "total_bytes": total_bytes,
                "total_human": format_size(total_bytes),
                "categories": dict(sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)),
                "warning_count": len(all_warnings),
            },
            payload_key="files",
            payload_data=all_files,
            warnings=all_warnings,
        )
        merged_path = out_dir / "merged_index.json"
        save_json(merged, merged_path)
        self.state.merged_index = merged
        self.state.warnings.extend(all_warnings)
        return merged

    def run_duplicate_scan(self) -> Dict[str, Any]:
        """Run multi-stage duplicate detection across the indexed JSON files."""
        if not self.state.index_files:
            raise RuntimeError("No index files available. Run run_index() first.")

        self._emit("deduplicating", "Scanning for duplicate files...", 1, 1)
        dups = find_duplicates_from_index(
            index_paths=[Path(p) for p in self.state.index_files],
            algo=self.state.config.hash_algo,
            min_size=self.state.config.min_size_bytes,
        )
        dup_path = Path(self.state.config.output_dir) / "duplicates_report.json"
        save_json(dups, dup_path)
        self.state.duplicates_report = dups
        self.state.warnings.extend(dups.get("warnings", []))
        return dups

    def run_export(
        self,
        export_xlsx: bool = True,
        export_png: bool = False,
        max_image_rows: int = 50,
        skip_large_image: bool = True,
    ) -> List[str]:
        """Export current pipeline state to Excel (.xlsx) and/or PNG preview."""
        out_dir = Path(self.state.config.output_dir)
        created: List[str] = []

        if export_xlsx:
            self._emit("exporting", "Building Excel workbook...", 1, 2 if export_png else 1)
            xlsx_path = out_dir / "suite_report.xlsx"
            export_json_to_excel(
                xlsx_path,
                index_data=self.state.merged_index,
                duplicates_data=self.state.duplicates_report,
            )
            created.append(str(xlsx_path.resolve()))

        if export_png and self.state.merged_index is not None:
            self._emit("exporting", "Rendering PNG preview...", 2 if export_xlsx else 1, 2 if export_xlsx else 1)
            png_path = out_dir / "suite_preview.png"
            written = export_json_to_image(
                png_path,
                self.state.merged_index,
                max_rows=max_image_rows,
                skip_if_too_large=skip_large_image,
            )
            if written:
                created.append(str(png_path.resolve()))

        self.state.exported_reports = created
        return created

    def run_all(
        self,
        export_xlsx: bool = True,
        export_png: bool = False,
        skip_large_image: bool = True,
    ) -> AppState:
        """Execute the full pipeline: index -> deduplicate -> export."""
        self.run_index()
        self.run_duplicate_scan()
        self.run_export(
            export_xlsx=export_xlsx,
            export_png=export_png,
            skip_large_image=skip_large_image,
        )
        self._emit("complete", "Pipeline finished.", 1, 1)
        return self.state

    def save_session(self, session_path: Optional[Path] = None) -> Path:
        """Persist session metadata and JSON pointers so a GUI can reload later."""
        target = session_path or (Path(self.state.config.output_dir) / "session.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            json.dump(self.state.to_session_dict(), fh, indent=2)
        return target

    @classmethod
    def load_session(cls, session_path: Path, on_progress: ProgressCallback = None) -> "FileSuitePipeline":
        """Restore a saved session into a FileSuitePipeline instance."""
        with session_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        cfg = ScanConfig(**raw["config"])
        pipeline = cls(config=cfg, on_progress=on_progress)
        pipeline.state.index_files = raw.get("index_files", [])
        pipeline.state.exported_reports = raw.get("exported_reports", [])
        pipeline.state.warnings = raw.get("warnings", [])

        merged_path = Path(cfg.output_dir) / "merged_index.json"
        if merged_path.exists():
            pipeline.state.merged_index = load_json(merged_path)

        dup_path_str = raw.get("duplicates_report_path")
        if dup_path_str and Path(dup_path_str).exists():
            pipeline.state.duplicates_report = load_json(Path(dup_path_str))

        return pipeline
