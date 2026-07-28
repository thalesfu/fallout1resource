"""Recoverable batch disassembly for Fallout INT scripts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .int_script import (
    INT_CONVERTER_VERSION,
    IntFormatError,
    int_output_paths,
    link_messages,
    load_int,
    write_int_export,
)
from .inventory import ensure_within_workspace, sha256_file
from .msg import MsgFormatError, load_msg
from .safe_io import write_file_atomic


class IntBatchError(ValueError):
    """Raised when an INT batch cannot be planned safely."""


@dataclass(frozen=True, slots=True)
class IntBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int
    message_path: Path | None
    message_source_name: str | None
    message_issue: str | None


@dataclass(frozen=True, slots=True)
class IntBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    warning_files: int
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
            raise IntBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(matches)}"
            )
        if "data" in available:
            raise IntBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", matches[0])
    return available


def _message_map(source_directory: Path) -> dict[str, list[Path]]:
    dialog = source_directory / "TEXT" / "ENGLISH" / "DIALOG"
    if not dialog.is_dir():
        return {}
    found: dict[str, list[Path]] = {}
    for path in dialog.rglob("*"):
        if path.is_file() and path.suffix.casefold() == ".msg":
            found.setdefault(path.stem.casefold(), []).append(path.resolve())
    return found


def _select_message(
    stem: str,
    source_name: str,
    message_maps: dict[str, dict[str, list[Path]]],
) -> tuple[Path | None, str | None, str | None]:
    order = ["data", source_name.casefold(), "master"]
    checked: set[str] = set()
    for candidate_source in order:
        if candidate_source in checked:
            continue
        checked.add(candidate_source)
        candidates = message_maps.get(candidate_source, {}).get(stem.casefold(), [])
        if len(candidates) == 1:
            return candidates[0], candidate_source, None
        if len(candidates) > 1:
            return None, None, f"ambiguous_message_candidates:{candidate_source}:{len(candidates)}"
    return None, None, "message_not_found"


def build_int_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
) -> tuple[IntBatchItem, ...]:
    """Discover extracted and loose INT files without writing."""
    workspace_path = Path(workspace).resolve()
    available = _available_sources(workspace_path, game_dir)
    requested = {source.casefold() for source in sources}
    unknown = requested.difference(available)
    if unknown:
        raise IntBatchError(f"unknown INT source: {', '.join(sorted(unknown))}")
    selected_sources = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not selected_sources:
        raise IntBatchError("no extracted or loose INT source directories are available")

    message_maps = {key: _message_map(directory) for key, (_, directory) in available.items()}
    plan: list[IntBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in selected_sources:
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file() or source_path.suffix.casefold() != ".int":
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            internal = relative.as_posix()
            output = Path("output/scripts") / source_name / relative.with_suffix(".json")
            target = int_output_paths(workspace_path, output)[0]
            key = str(target).casefold()
            if key in targets:
                raise IntBatchError(f"multiple INT files map to the same output: {target}")
            targets.add(key)
            message_path, message_source, message_issue = _select_message(
                source_path.stem,
                source_name,
                message_maps,
            )
            plan.append(
                IntBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=internal,
                    output=output,
                    size=source_path.stat().st_size,
                    message_path=message_path,
                    message_source_name=message_source,
                    message_issue=message_issue,
                )
            )
    if not plan:
        raise IntBatchError("no INT files matched the selected sources")
    return tuple(
        sorted(plan, key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()))
    )


def _manifest_source_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _message_encoding(source_name: str | None) -> str | None:
    return "latin-1" if source_name == "master" else None


def _existing_outputs_are_current(
    item: IntBatchItem,
    workspace: Path,
    source_sha256: str,
    message_sha256: str | None,
) -> bool:
    json_path, disasm_path, messages_path, hash_path = int_output_paths(workspace, item.output)
    if not all(path.is_file() for path in (json_path, disasm_path, messages_path, hash_path)):
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        message_link = metadata["message_link"]
        derived = metadata["derived"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    if (
        metadata.get("schema_version") != 1
        or source.get("sha256") != source_sha256
        or source.get("size") != item.size
        or generator.get("name") != "fallout1resource"
        or generator.get("component") != "int"
        or generator.get("component_version") != INT_CONVERTER_VERSION
        or message_link.get("msg_sha256") != message_sha256
    ):
        return False
    for key, path in (("disassembly", disasm_path), ("message_links", messages_path)):
        record = derived.get(key)
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


def execute_int_batch(
    plan: tuple[IntBatchItem, ...] | list[IntBatchItem],
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> IntBatchResult:
    """Disassemble every planned INT and retain per-file failures and warnings."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0

    for item in items:
        json_path, disasm_path, messages_path, hash_path = int_output_paths(
            workspace_path, item.output
        )
        warnings: list[dict[str, str]] = []
        try:
            program = load_int(item.source_path)
            msg = None
            if item.message_path is not None:
                try:
                    msg = load_msg(
                        item.message_path,
                        encoding=_message_encoding(item.message_source_name),
                    )
                except (MsgFormatError, OSError, ValueError) as exc:
                    warnings.append(
                        {
                            "code": "message_load_failed",
                            "message": str(exc),
                        }
                    )
            references, inferred = link_messages(program, msg)
            if references and item.message_issue is not None:
                warnings.append({"code": item.message_issue, "message": item.message_issue})
            message_sha256 = msg.source_sha256 if msg is not None else None
            existing = [
                path for path in (json_path, disasm_path, messages_path, hash_path) if path.exists()
            ]
            if existing and not overwrite:
                if _existing_outputs_are_current(
                    item, workspace_path, program.source_sha256, message_sha256
                ):
                    skipped += 1
                    status = "skipped_verified"
                else:
                    raise IntBatchError(f"existing outputs are incomplete or stale: {json_path}")
            else:
                write_int_export(
                    program,
                    references,
                    inferred,
                    msg,
                    workspace_path,
                    item.output,
                    overwrite=overwrite,
                )
                output_bytes += sum(
                    path.stat().st_size
                    for path in (json_path, disasm_path, messages_path, hash_path)
                )
                converted += 1
                status = "converted"
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": program.source_sha256,
                    "status": status,
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "message_source": (str(msg.source_path) if msg is not None else None),
                    "message_sha256": message_sha256,
                    "message_references": len(references),
                    "linked_message_references": sum(
                        reference.link_status == "linked" for reference in references
                    ),
                    "warnings": warnings,
                    "error": None,
                }
            )
        except (FileNotFoundError, IntBatchError, IntFormatError, OSError, ValueError) as exc:
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "status": "failed",
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "warnings": warnings,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )

    finished_at = datetime.now(UTC)
    duration = time.perf_counter() - started_clock
    failed = sum(record["status"] == "failed" for record in records)
    warning_files = sum(bool(record.get("warnings")) for record in records)
    manifest = {
        "schema_version": 1,
        "mode": "disassemble-int-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(duration, 6),
        "options": {
            "overwrite": overwrite,
            "sources": sorted({item.source_name for item in items}),
            "message_precedence": ["data", "same_source", "master"],
        },
        "summary": {
            "selected": len(items),
            "converted": converted,
            "skipped_verified": skipped,
            "failed": failed,
            "warning_files": warning_files,
            "source_bytes": sum(item.size for item in items),
            "output_bytes_written": output_bytes,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-int-{timestamp}.json"
    )
    write_file_atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        overwrite=False,
    )
    return IntBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        warning_files=warning_files,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        duration_seconds=duration,
    )


def int_batch_plan_summary(plan: tuple[IntBatchItem, ...]) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    message_counts: dict[str, int] = {}
    for item in plan:
        source_counts[item.source_name] = source_counts.get(item.source_name, 0) + 1
        key = item.message_source_name or item.message_issue or "none"
        message_counts[key] = message_counts.get(key, 0) + 1
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(source_counts.items())),
        "message_match_counts": dict(sorted(message_counts.items())),
    }
