"""Recoverable batch conversion for Fallout FRM family images."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .frm import (
    FRM_CONVERTER_VERSION,
    FrmFormatError,
    frm_output_paths,
    load_frm,
    load_palette,
    write_frm_export,
)
from .inventory import ensure_within_workspace, sha256_file
from .safe_io import write_file_atomic

FRM_EXTENSIONS = frozenset({".frm", ".fr0", ".fr1", ".fr2", ".fr3", ".fr4", ".fr5"})


class FrmBatchError(ValueError):
    """Raised when an FRM batch cannot be planned safely."""


@dataclass(frozen=True, slots=True)
class FrmBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int
    extension: str


@dataclass(frozen=True, slots=True)
class FrmBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    frames: int
    source_bytes: int
    output_bytes: int
    duration_seconds: float


def _available_sources(
    workspace: Path,
    game_dir: Path | str | None,
) -> dict[str, tuple[str, Path]]:
    raw_root = ensure_within_workspace(workspace, "raw")
    available: dict[str, tuple[str, Path]] = {}
    if raw_root.is_dir():
        available.update(
            {
                item.name.casefold(): (item.name, item)
                for item in raw_root.iterdir()
                if item.is_dir()
            }
        )
    if game_dir is not None:
        game_path = Path(game_dir).resolve()
        if not game_path.is_dir():
            raise FileNotFoundError(f"game directory does not exist: {game_path}")
        matches = [
            item for item in game_path.iterdir() if item.is_dir() and item.name.casefold() == "data"
        ]
        if len(matches) != 1:
            raise FrmBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(matches)}"
            )
        if "data" in available:
            raise FrmBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", matches[0])
    return available


def _output_path(source_name: str, relative: Path) -> Path:
    extension = relative.suffix.casefold().removeprefix(".")
    asset_name = f"{relative.stem}.{extension}"
    return Path("output/images") / source_name / relative.parent / asset_name / f"{asset_name}.json"


def build_frm_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
    palette: Path | str | None = None,
) -> tuple[tuple[FrmBatchItem, ...], Path]:
    """Discover FRM-family images and resolve one explicit palette without writing."""
    workspace_path = Path(workspace).resolve()
    available = _available_sources(workspace_path, game_dir)
    requested = {source.casefold() for source in sources}
    unknown = requested.difference(available)
    if unknown:
        raise FrmBatchError(f"unknown FRM source: {', '.join(sorted(unknown))}")
    selected_sources = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not selected_sources:
        raise FrmBatchError("no extracted or loose FRM source directories are available")

    palette_path = (
        Path(palette).resolve()
        if palette is not None
        else ensure_within_workspace(workspace_path, "raw/master/COLOR.PAL")
    )
    if not palette_path.is_file():
        raise FileNotFoundError(f"palette does not exist: {palette_path}")

    plan: list[FrmBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in selected_sources:
        for source_path in sorted(source_directory.rglob("*")):
            extension = source_path.suffix.casefold()
            if not source_path.is_file() or extension not in FRM_EXTENSIONS:
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            output = _output_path(source_name, relative)
            target = ensure_within_workspace(workspace_path, output)
            key = str(target).casefold()
            if key in targets:
                raise FrmBatchError(f"multiple FRM files map to the same output: {target}")
            targets.add(key)
            plan.append(
                FrmBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=relative.as_posix(),
                    output=output,
                    size=source_path.stat().st_size,
                    extension=extension,
                )
            )
    if not plan:
        raise FrmBatchError("no FRM files matched the selected sources")
    return (
        tuple(
            sorted(
                plan,
                key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()),
            )
        ),
        palette_path,
    )


def _manifest_source_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _existing_outputs_are_current(
    item: FrmBatchItem,
    workspace: Path,
    document: Any,
    palette_sha256: str,
) -> bool:
    json_path, palette_path, frame_paths, hash_path = frm_output_paths(
        workspace, item.output, document
    )
    if not all(path.is_file() for path in (json_path, palette_path, *frame_paths, hash_path)):
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        palette_source = metadata["palette"]["source"]
        derived = metadata["derived"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    if not all(isinstance(value, dict) for value in (source, generator, palette_source, derived)):
        return False
    if (
        metadata.get("schema_version") != 1
        or source.get("sha256") != document.source_sha256
        or source.get("size") != item.size
        or palette_source.get("sha256") != palette_sha256
        or generator.get("name") != "fallout1resource"
        or generator.get("component") != "frm"
        or generator.get("component_version") != FRM_CONVERTER_VERSION
    ):
        return False
    frame_records = derived.get("frames")
    if not isinstance(frame_records, list):
        return False
    expected = [derived.get("palette_preview"), *frame_records]
    paths = [palette_path, *frame_paths]
    if len(expected) != len(paths):
        return False
    for record, path in zip(expected, paths, strict=True):
        if not isinstance(record, dict):
            return False
        if (
            record.get("path") != path.relative_to(workspace).as_posix()
            or record.get("size") != path.stat().st_size
            or record.get("sha256") != sha256_file(path)
        ):
            return False
    checksum = hash_path.read_text(encoding="ascii").strip().split("  ", 1)
    return (
        len(checksum) == 2
        and checksum[0] == sha256_file(json_path)
        and checksum[1] == json_path.name
    )


def execute_frm_batch(
    plan: tuple[FrmBatchItem, ...] | list[FrmBatchItem],
    palette_path: Path | str,
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> FrmBatchResult:
    """Convert every planned FRM while preserving individual failures."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    palette = load_palette(palette_path)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0
    frames = 0

    for item in items:
        try:
            document = load_frm(item.source_path)
            json_path, palette_output, frame_paths, hash_path = frm_output_paths(
                workspace_path, item.output, document
            )
            existing = [
                path
                for path in (json_path, palette_output, *frame_paths, hash_path)
                if path.exists()
            ]
            if existing and not overwrite:
                if _existing_outputs_are_current(
                    item, workspace_path, document, palette.source_sha256
                ):
                    skipped += 1
                    status = "skipped_verified"
                else:
                    raise FrmBatchError(f"existing outputs are incomplete or stale: {json_path}")
            else:
                write_frm_export(
                    document,
                    palette,
                    workspace_path,
                    item.output,
                    overwrite=overwrite,
                )
                output_bytes += sum(
                    path.stat().st_size
                    for path in (json_path, palette_output, *frame_paths, hash_path)
                )
                converted += 1
                status = "converted"
            frame_count = len(frame_paths)
            frames += frame_count
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": document.source_sha256,
                    "extension": item.extension,
                    "status": status,
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "sequences": len(document.sequences),
                    "frames": frame_count,
                    "error": None,
                }
            )
        except (FileNotFoundError, FrmBatchError, FrmFormatError, OSError, ValueError) as exc:
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "extension": item.extension,
                    "status": "failed",
                    "output": item.output.as_posix(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )

    finished_at = datetime.now(UTC)
    duration = time.perf_counter() - started_clock
    failed = sum(record["status"] == "failed" for record in records)
    manifest = {
        "schema_version": 1,
        "mode": "convert-frm-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
        "palette": {
            "path": _manifest_source_path(palette.source_path, workspace_path),
            "size": palette.source_size,
            "sha256": palette.source_sha256,
        },
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(duration, 6),
        "options": {
            "overwrite": overwrite,
            "sources": sorted({item.source_name for item in items}),
        },
        "summary": {
            "selected": len(items),
            "converted": converted,
            "skipped_verified": skipped,
            "failed": failed,
            "frames": frames,
            "source_bytes": sum(item.size for item in items),
            "output_bytes_written": output_bytes,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-frm-{timestamp}.json"
    )
    write_file_atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        overwrite=False,
    )
    return FrmBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        frames=frames,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        duration_seconds=duration,
    )


def frm_batch_plan_summary(plan: tuple[FrmBatchItem, ...]) -> dict[str, Any]:
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(Counter(item.source_name for item in plan).items())),
        "extension_counts": dict(sorted(Counter(item.extension for item in plan).items())),
    }
