"""
Report Exporter — Converts standardized file_suite JSON files into formatted
Excel (.xlsx) workbooks or PNG table previews.

Usage:
    python -m file_suite.export_report --index metadata_index.json --duplicates duplicates_report.json -o report.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import load_json

RECOMMENDED_MAX_IMAGE_ROWS = 150


def export_json_to_excel(
    output_path: Path,
    index_data: Optional[Dict[str, Any]] = None,
    duplicates_data: Optional[Dict[str, Any]] = None,
) -> Path:
    """Build a multi-sheet styled Excel workbook from standardized JSON reports."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError("openpyxl is required. Install with: pip install openpyxl") from exc

    if not index_data and not duplicates_data:
        raise ValueError("Provide at least one of index_data or duplicates_data.")

    wb = Workbook()
    wb.remove(wb.active)

    navy_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    warn_fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", size=10, color="0F172A")
    bold_font = Font(name="Calibri", size=10, bold=True, color="0F172A")
    thin_side = Side(style="thin", color="CBD5E1")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    if index_data:
        ws = wb.create_sheet("File Index")
        headers = [
            "File Name", "Extension", "Category", "MIME Type", "Size (Bytes)",
            "Size", "Created Date", "Modified Date", "Attributes", "Drive", "Full Path",
        ]
        ws.append(headers)
        ws.row_dimensions[1].height = 25
        for c_idx in range(1, len(headers) + 1):
            c = ws.cell(row=1, column=c_idx)
            c.fill = navy_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border

        for r_idx, item in enumerate(index_data.get("files", []), start=2):
            ws.append([
                item["name"], item["extension"], item["category"], item["mime_type"],
                item["size_bytes"], item["size_human"], item["created_at"],
                item["modified_at"], item["attributes"], item.get("drive", ""),
                item["full_path"],
            ])
            for c_idx in range(1, len(headers) + 1):
                c = ws.cell(row=r_idx, column=c_idx)
                c.font = body_font
                c.border = border
                if r_idx % 2 == 1:
                    c.fill = zebra_fill
                if c_idx == 5:
                    c.number_format = "#,##0"
                    c.alignment = Alignment(horizontal="right", vertical="center")
                elif c_idx == 6:
                    c.alignment = Alignment(horizontal="right", vertical="center")

        ws.freeze_panes = "A2"
        last_r = max(len(index_data.get("files", [])) + 1, 1)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_r}"
        widths = [28, 12, 14, 24, 15, 12, 20, 20, 12, 10, 56]
        for idx, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = w

    if duplicates_data:
        ws_dup = wb.create_sheet("Duplicate Groups")
        dup_headers = [
            "Group ID", "Copy Count", "File Size (Bytes)", "File Size",
            "Reclaimable", "Hash", "File Name", "Full Path",
        ]
        ws_dup.append(dup_headers)
        ws_dup.row_dimensions[1].height = 25
        for c_idx in range(1, len(dup_headers) + 1):
            c = ws_dup.cell(row=1, column=c_idx)
            c.fill = warn_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border

        r_idx = 2
        for grp in duplicates_data.get("duplicate_groups", []):
            for f in grp["files"]:
                ws_dup.append([
                    grp["group_id"], grp["copy_count"], grp["size_bytes"],
                    grp["size_human"], grp["wasted_human"], grp["file_hash"][:16] + "...",
                    f["name"], f["full_path"],
                ])
                for c_idx in range(1, len(dup_headers) + 1):
                    c = ws_dup.cell(row=r_idx, column=c_idx)
                    c.font = body_font
                    c.border = border
                    if grp["group_id"] % 2 == 0:
                        c.fill = zebra_fill
                    if c_idx == 3:
                        c.number_format = "#,##0"
                        c.alignment = Alignment(horizontal="right", vertical="center")
                    elif c_idx in (4, 5):
                        c.alignment = Alignment(horizontal="right", vertical="center")
                r_idx += 1

        ws_dup.freeze_panes = "A2"
        ws_dup.auto_filter.ref = f"A1:{get_column_letter(len(dup_headers))}{max(r_idx - 1, 1)}"
        dup_widths = [12, 12, 18, 13, 14, 22, 28, 56]
        for idx, w in enumerate(dup_widths, start=1):
            ws_dup.column_dimensions[get_column_letter(idx)].width = w

    ws_sum = wb.create_sheet("Summary")
    ws_sum["A1"] = "File Manager Suite Summary"
    ws_sum["A1"].font = Font(name="Calibri", size=14, bold=True, color="1E293B")
    row = 3
    if index_data:
        s = index_data["summary"]
        for k, v in [
            ("Index Source", index_data["source"]),
            ("Total Indexed Files", s["total_files"]),
            ("Total Size", s["total_human"]),
        ]:
            ws_sum.cell(row=row, column=1, value=k).font = bold_font
            ws_sum.cell(row=row, column=2, value=v).font = body_font
            row += 1
        row += 1
    if duplicates_data:
        ds = duplicates_data["summary"]
        for k, v in [
            ("Duplicate Scan Source", duplicates_data["source"]),
            ("Duplicate Groups", ds["duplicate_groups"]),
            ("Total Duplicate Files", ds["total_duplicate_files"]),
            ("Reclaimable Space", ds["reclaimable_human"]),
        ]:
            ws_sum.cell(row=row, column=1, value=k).font = bold_font
            ws_sum.cell(row=row, column=2, value=v).font = body_font
            row += 1
    ws_sum.column_dimensions["A"].width = 24
    ws_sum.column_dimensions["B"].width = 60

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def export_json_to_image(
    output_path: Path,
    index_data: Dict[str, Any],
    max_rows: int = 50,
    skip_if_too_large: bool = False,
) -> bool:
    """Render a PNG table preview from a metadata_index JSON with large-output warnings."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib") from exc

    files = index_data.get("files", [])
    total = len(files)
    if total > max_rows:
        print(
            f"Warning: Index has {total:,} files, exceeding PNG limit ({max_rows:,} rows). "
            + (
                "Skipping PNG export; use .xlsx for the full listing."
                if skip_if_too_large
                else f"Rendering first {max_rows:,} rows only. Use .xlsx for the full listing."
            ),
            file=sys.stderr,
        )
        if skip_if_too_large:
            return False

    if max_rows > RECOMMENDED_MAX_IMAGE_ROWS and total > RECOMMENDED_MAX_IMAGE_ROWS:
        print(
            f"Warning: Rendering {min(total, max_rows):,} rows in a PNG may be unreadable.",
            file=sys.stderr,
        )

    rows = [
        [
            f["name"][:27] + "..." if len(f["name"]) > 30 else f["name"],
            f["category"],
            f["size_human"],
            f["modified_at"].replace("T", " ")[:16],
            f["attributes"],
            f["relative_path"][-39:] if len(f["relative_path"]) > 42 else f["relative_path"],
        ]
        for f in files[:max_rows]
    ] or [["(No files)", "-", "-", "-", "-", "-"]]

    fig_h = max(3.2, 1.4 + (len(rows) + 1) * 0.34)
    fig, ax = plt.subplots(figsize=(15.0, fig_h), dpi=200)
    ax.axis("off")
    fig.text(0.02, 0.96, "Directory File Listing", fontsize=14, fontweight="bold", color="#0F172A", va="top")
    fig.text(
        0.02, 0.92,
        f"Source: {index_data['source']}  |  Files: {total:,}  |  Total: {index_data['summary']['total_human']}",
        fontsize=9.5, color="#475569", va="top",
    )

    tbl = ax.table(
        cellText=rows,
        colLabels=["File Name", "Type", "Size", "Modified", "Attrs", "Relative Path"],
        colWidths=[0.22, 0.11, 0.10, 0.16, 0.10, 0.31],
        loc="center",
        bbox=[0.0, 0.02, 1.0, 0.85],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    for (r_i, c_i), cell in tbl.get_celld().items():
        cell.set_edgecolor("#CBD5E1")
        cell.set_linewidth(0.6)
        if r_i == 0:
            cell.set_facecolor("#1E293B")
            cell.set_text_props(color="#FFFFFF", fontweight="bold", ha="center")
        else:
            cell.set_facecolor("#F8FAFC" if r_i % 2 == 0 else "#FFFFFF")
            cell.set_text_props(color="#0F172A", ha="right" if c_i == 2 else "left")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return True


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export file_suite JSON reports to Excel or PNG.")
    parser.add_argument("--index", type=Path, default=None, help="Path to metadata_index.json.")
    parser.add_argument("--duplicates", type=Path, default=None, help="Path to duplicates_report.json.")
    parser.add_argument("-o", "--output", type=Path, default=Path("suite_report.xlsx"), help="Output file path.")
    parser.add_argument("-f", "--format", choices=("xlsx", "png"), default="xlsx", help="Output format.")
    parser.add_argument("--max-image-rows", type=int, default=50, help="Max rows for PNG output.")
    parser.add_argument("--skip-large-image", action="store_true", help="Skip PNG if files exceed max-image-rows.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.index and not args.duplicates:
        print("Error: Provide --index and/or --duplicates.", file=sys.stderr)
        return 1

    idx_data = load_json(args.index) if args.index else None
    dup_data = load_json(args.duplicates) if args.duplicates else None

    if args.format == "xlsx":
        out = export_json_to_excel(args.output.with_suffix(".xlsx"), idx_data, dup_data)
        print(f"Saved Excel workbook: {out.resolve()}")
    else:
        if not idx_data:
            print("Error: PNG export requires --index.", file=sys.stderr)
            return 1
        written = export_json_to_image(
            args.output.with_suffix(".png"), idx_data,
            max_rows=args.max_image_rows, skip_if_too_large=args.skip_large_image,
        )
        if written:
            print(f"Saved table image: {args.output.with_suffix('.png').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
