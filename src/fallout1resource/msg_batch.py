"""Recoverable batch conversion for extracted Fallout MSG files."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace, sha256_file
from .msg import (
    MSG_CONVERTER_VERSION,
    MsgFormatError,
    load_msg,
    msg_output_paths,
    write_msg_export,
)
from .safe_io import write_file_atomic


class MsgBatchError(ValueError):
    """Raised when a MSG batch cannot be planned safely."""


@dataclass(frozen=True, slots=True)
class MsgBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int


@dataclass(frozen=True, slots=True)
class MsgBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    source_bytes: int
    output_bytes: int
    duration_seconds: float


def build_msg_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
) -> tuple[MsgBatchItem, ...]:
    """Discover extracted and loose MSG files without reading or writing contents."""
    workspace_path = Path(workspace).resolve()
    raw_root = ensure_within_workspace(workspace_path, "raw")
    requested = {source.casefold() for source in sources}
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
        data_matches = [
            item for item in game_path.iterdir() if item.is_dir() and item.name.casefold() == "data"
        ]
        if len(data_matches) != 1:
            raise MsgBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(data_matches)}"
            )
        if "data" in available:
            raise MsgBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", data_matches[0])
    unknown = requested.difference(available)
    if unknown:
        raise MsgBatchError(f"unknown MSG source: {', '.join(sorted(unknown))}")
    source_directories = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not source_directories:
        raise MsgBatchError("no extracted or loose MSG source directories are available")

    plan: list[MsgBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in source_directories:
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file() or source_path.suffix.casefold() != ".msg":
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            internal = relative.as_posix()
            output = Path("output/text") / source_name / Path(internal).with_suffix(".json")
            target = msg_output_paths(workspace_path, output)[0]
            key = str(target).casefold()
            if key in targets:
                raise MsgBatchError(f"multiple MSG files map to the same output: {target}")
            targets.add(key)
            plan.append(
                MsgBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=internal,
                    output=output,
                    size=source_path.stat().st_size,
                )
            )
    if not plan:
        raise MsgBatchError("no MSG files matched the selected sources")
    return tuple(
        sorted(plan, key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()))
    )


def _existing_outputs_are_current(
    item: MsgBatchItem,
    workspace: Path,
    source_sha256: str,
) -> bool:
    json_path, csv_path, hash_path = msg_output_paths(workspace, item.output)
    if not all(path.is_file() for path in (json_path, csv_path, hash_path)):
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        derived_csv = metadata["derived"]["csv"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    if (
        metadata.get("schema_version") != 1
        or source.get("sha256") != source_sha256
        or source.get("size") != item.size
        or generator.get("name") != "fallout1resource"
        or generator.get("component") != "msg"
        or generator.get("component_version") != MSG_CONVERTER_VERSION
    ):
        return False
    if (
        derived_csv.get("path") != csv_path.relative_to(workspace).as_posix()
        or derived_csv.get("size") != csv_path.stat().st_size
        or derived_csv.get("sha256") != sha256_file(csv_path)
    ):
        return False
    checksum = hash_path.read_text(encoding="ascii").strip().split("  ", 1)
    return (
        len(checksum) == 2
        and checksum[0] == sha256_file(json_path)
        and checksum[1] == json_path.name
    )


def _source_encoding(item: MsgBatchItem) -> str | None:
    if item.source_name.casefold() == "master":
        return "latin-1"
    return None


def execute_msg_batch(
    plan: tuple[MsgBatchItem, ...] | list[MsgBatchItem],
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> MsgBatchResult:
    """Convert every planned item, preserving per-file failures for resumption."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0

    for item in items:
        try:
            source_manifest_path = item.source_path.relative_to(workspace_path).as_posix()
        except ValueError:
            source_manifest_path = str(item.source_path)
        json_path, csv_path, hash_path = msg_output_paths(workspace_path, item.output)
        try:
            document = load_msg(item.source_path, encoding=_source_encoding(item))
            existing = [path for path in (json_path, csv_path, hash_path) if path.exists()]
            if existing and not overwrite:
                if _existing_outputs_are_current(item, workspace_path, document.source_sha256):
                    skipped += 1
                    records.append(
                        {
                            "source_path": source_manifest_path,
                            "source_name": item.source_name,
                            "internal_path": item.internal_path,
                            "source_size": item.size,
                            "source_sha256": document.source_sha256,
                            "status": "skipped_verified",
                            "output": json_path.relative_to(workspace_path).as_posix(),
                            "error": None,
                        }
                    )
                    continue
                raise MsgBatchError(f"existing outputs are incomplete or stale: {json_path}")
            write_msg_export(document, workspace_path, item.output, overwrite=overwrite)
            produced_bytes = sum(path.stat().st_size for path in (json_path, csv_path, hash_path))
            output_bytes += produced_bytes
            converted += 1
            records.append(
                {
                    "source_path": source_manifest_path,
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": document.source_sha256,
                    "status": "converted",
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "output_bytes": produced_bytes,
                    "error": None,
                }
            )
        except (FileNotFoundError, MsgBatchError, MsgFormatError, OSError, ValueError) as exc:
            records.append(
                {
                    "source_path": source_manifest_path,
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "status": "failed",
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )

    finished_at = datetime.now(UTC)
    duration = time.perf_counter() - started_clock
    failed = sum(record["status"] == "failed" for record in records)
    manifest = {
        "schema_version": 1,
        "mode": "convert-msg-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(duration, 6),
        "options": {
            "overwrite": overwrite,
            "sources": sorted({item.source_name for item in items}),
            "encoding_policy": {
                item.source_name: _source_encoding(item) or "auto" for item in items
            },
        },
        "summary": {
            "selected": len(items),
            "converted": converted,
            "skipped_verified": skipped,
            "failed": failed,
            "source_bytes": sum(item.size for item in items),
            "output_bytes_written": output_bytes,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-msg-{timestamp}.json"
    )
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_file_atomic(manifest_path, encoded, overwrite=False)
    return MsgBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        duration_seconds=duration,
    )


def msg_batch_plan_summary(plan: tuple[MsgBatchItem, ...]) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    for item in plan:
        source_counts[item.source_name] = source_counts.get(item.source_name, 0) + 1
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(source_counts.items())),
    }
