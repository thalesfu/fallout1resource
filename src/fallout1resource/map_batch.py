"""Recoverable batch conversion for Fallout MAP files and their PRO/LST dependencies."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace, sha256_file
from .map_file import (
    MAP_CONVERTER_VERSION,
    MapDocument,
    MapFormatError,
    load_map,
    map_output_paths,
    write_map_export,
)
from .proto import ProtoFormatError
from .safe_io import write_file_atomic


class MapBatchError(ValueError):
    """Raised when a MAP batch cannot be planned or resumed safely."""


@dataclass(frozen=True, slots=True)
class MapBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int


@dataclass(frozen=True, slots=True)
class MapBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    source_bytes: int
    output_bytes: int
    objects: int
    scripts: int
    prototype_links: int
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
            raise MapBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(matches)}"
            )
        if "data" in available:
            raise MapBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", matches[0])
    return available


def _output_path(source_name: str, relative: Path) -> Path:
    return (
        Path("output/maps")
        / source_name
        / relative.parent
        / relative.stem
        / f"{relative.stem}.json"
    )


def build_map_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
    prototype_root: Path | str | None = None,
    scripts_list: Path | str | None = None,
) -> tuple[tuple[MapBatchItem, ...], Path, Path]:
    """Discover MAP sources and resolve explicit read-only PRO/LST dependencies."""
    workspace_path = Path(workspace).resolve()
    available = _available_sources(workspace_path, game_dir)
    requested = {source.casefold() for source in sources}
    unknown = requested.difference(available)
    if unknown:
        raise MapBatchError(f"unknown MAP source: {', '.join(sorted(unknown))}")
    selected_sources = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not selected_sources:
        raise MapBatchError("no extracted or loose MAP source directories are available")

    proto_path = (
        Path(prototype_root).resolve()
        if prototype_root is not None
        else ensure_within_workspace(workspace_path, "raw/master/PROTO")
    )
    scripts_path = (
        Path(scripts_list).resolve()
        if scripts_list is not None
        else ensure_within_workspace(workspace_path, "raw/master/SCRIPTS/SCRIPTS.LST")
    )
    if not proto_path.is_dir():
        raise FileNotFoundError(f"prototype root does not exist: {proto_path}")
    if not scripts_path.is_file():
        raise FileNotFoundError(f"scripts list does not exist: {scripts_path}")

    plan: list[MapBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in selected_sources:
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file() or source_path.suffix.casefold() != ".map":
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            output = _output_path(source_name, relative)
            target = ensure_within_workspace(workspace_path, output)
            key = str(target).casefold()
            if key in targets:
                raise MapBatchError(f"multiple MAP files map to the same output: {target}")
            targets.add(key)
            plan.append(
                MapBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=relative.as_posix(),
                    output=output,
                    size=source_path.stat().st_size,
                )
            )
    if not plan:
        raise MapBatchError("no MAP files matched the selected sources")
    return (
        tuple(
            sorted(
                plan,
                key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()),
            )
        ),
        proto_path,
        scripts_path,
    )


def _manifest_source_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _prototype_fingerprint(document: MapDocument) -> list[tuple[int, int, str]]:
    return sorted(
        (prototype.pid, prototype.source_size, prototype.source_sha256)
        for prototype in document.referenced_prototypes
    )


def _metadata_prototype_fingerprint(metadata: dict[str, Any]) -> list[tuple[int, int, str]]:
    records = metadata.get("referenced_prototypes")
    if not isinstance(records, list):
        raise TypeError("referenced_prototypes must be a list")
    return sorted(
        (record["pid"], record["source"]["size"], record["source"]["sha256"]) for record in records
    )


def _existing_outputs_are_current(
    item: MapBatchItem,
    workspace: Path,
    document: MapDocument,
) -> bool:
    json_path, csv_path, hash_path = map_output_paths(workspace, item.output)
    if not all(path.is_file() for path in (json_path, csv_path, hash_path)):
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        list_records = metadata["prototype_lists"]
        scripts_record = metadata["scripts_list"]
        csv_record = metadata["derived"]["objects_csv"]
        if not all(
            isinstance(value, dict) for value in (source, generator, scripts_record, csv_record)
        ):
            return False
        if not isinstance(list_records, list):
            return False
        actual_lists = {
            pid_type: (lst.source_sha256, len(lst.entries))
            for pid_type, lst in document.prototype_lists.items()
        }
        recorded_lists = {
            record["pid_type"]: (record["sha256"], record["entries"]) for record in list_records
        }
        if (
            metadata.get("schema_version") != 1
            or source.get("sha256") != document.source_sha256
            or source.get("size") != item.size
            or generator.get("name") != "fallout1resource"
            or generator.get("component") != "map"
            or generator.get("component_version") != MAP_CONVERTER_VERSION
            or actual_lists != recorded_lists
            or document.scripts_list is None
            or scripts_record.get("sha256") != document.scripts_list.source_sha256
            or _metadata_prototype_fingerprint(metadata) != _prototype_fingerprint(document)
            or csv_record.get("path") != csv_path.relative_to(workspace).as_posix()
            or csv_record.get("size") != csv_path.stat().st_size
            or csv_record.get("sha256") != sha256_file(csv_path)
        ):
            return False
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    checksum = hash_path.read_text(encoding="ascii").strip().split("  ", 1)
    return (
        len(checksum) == 2
        and checksum[0] == sha256_file(json_path)
        and checksum[1] == json_path.name
    )


def execute_map_batch(
    plan: tuple[MapBatchItem, ...] | list[MapBatchItem],
    prototype_root: Path | str,
    scripts_list: Path | str,
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> MapBatchResult:
    """Convert every planned MAP while preserving per-file failures."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0
    objects = 0
    scripts = 0
    prototype_links = 0

    for item in items:
        try:
            document = load_map(
                item.source_path,
                prototype_root,
                scripts_list_path=scripts_list,
            )
            json_path, csv_path, hash_path = map_output_paths(workspace_path, item.output)
            existing = [path for path in (json_path, csv_path, hash_path) if path.exists()]
            if existing and not overwrite:
                if _existing_outputs_are_current(item, workspace_path, document):
                    skipped += 1
                    status = "skipped_verified"
                else:
                    raise MapBatchError(f"existing outputs are incomplete or stale: {json_path}")
            else:
                write_map_export(
                    document,
                    workspace_path,
                    item.output,
                    overwrite=overwrite,
                )
                output_bytes += sum(
                    path.stat().st_size for path in (json_path, csv_path, hash_path)
                )
                converted += 1
                status = "converted"

            summary_objects = len(document.objects)
            stack = list(document.objects)
            inventory_objects = 0
            while stack:
                current = stack.pop()
                inventory_objects += len(current.inventory)
                stack.extend(entry.item for entry in current.inventory)
            object_count = summary_objects + inventory_objects
            script_count = len(document.scripts)
            prototype_count = len(document.referenced_prototypes)
            objects += object_count
            scripts += script_count
            prototype_links += prototype_count
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": document.source_sha256,
                    "status": status,
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "objects": object_count,
                    "scripts": script_count,
                    "referenced_prototypes": prototype_count,
                    "error": None,
                }
            )
        except (
            FileNotFoundError,
            MapBatchError,
            MapFormatError,
            ProtoFormatError,
            OSError,
            ValueError,
        ) as exc:
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
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
        "mode": "convert-map-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
        "dependencies": {
            "prototype_root": _manifest_source_path(Path(prototype_root).resolve(), workspace_path),
            "scripts_list": _manifest_source_path(Path(scripts_list).resolve(), workspace_path),
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
            "source_bytes": sum(item.size for item in items),
            "output_bytes_written": output_bytes,
            "objects": objects,
            "scripts": scripts,
            "prototype_links": prototype_links,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-map-{timestamp}.json"
    )
    write_file_atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        overwrite=False,
    )
    return MapBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        objects=objects,
        scripts=scripts,
        prototype_links=prototype_links,
        duration_seconds=duration,
    )


def map_batch_plan_summary(plan: tuple[MapBatchItem, ...]) -> dict[str, Any]:
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(Counter(item.source_name for item in plan).items())),
    }
