from __future__ import annotations

from pathlib import Path


DANGEROUS_CELL_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_cell(value: object) -> str:
    """Convert a value to text and neutralize spreadsheet formula prefixes."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(DANGEROUS_CELL_PREFIXES):
        return f"'{text}"
    return text


def is_within_root(target: Path, allowed_root: Path) -> bool:
    """Return True only if target resolves strictly beneath allowed_root."""
    try:
        resolved_target = target.resolve(strict=True)
        resolved_root = allowed_root.resolve(strict=True)
        return resolved_target.is_relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return False


def resolve_regular_file(path: Path, allowed_roots: list[Path]) -> Path:
    """Resolve a file, reject symlinks and devices, and enforce root containment."""
    try:
        if path.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {path}")
        if not path.exists():
            raise ValueError(f"File does not exist: {path}")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"Path is not a regular file: {resolved}")
        if resolved.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {resolved}")
        if not any(is_within_root(resolved, root) for root in allowed_roots):
            raise ValueError(f"Path is outside the allowed roots: {resolved}")
        return resolved
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot safely resolve file '{path}': {exc}") from exc
