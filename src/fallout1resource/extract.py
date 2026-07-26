"""Safe, source-isolated extraction for selected DAT1 entries."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .dat1 import Dat1Entry, parse_dat1
from .inventory import ensure_within_workspace, resource_type
from .lzss import LzssError, decompress_dat1_payload


MAX_ENTRY_SIZE = 512 * 1024 * 1024


class ExtractionError(ValueError):
    """Raised when selection, validation, decompression, or output safety fails."""


@dataclass(frozen=True, slots=True)
class ExtractionPlanItem:
    archive_path: Path
    archive_name: str
    archive_size: int
    archive_mtime_ns: int
    entry: Dat1Entry
    target_path: Path


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    archive_name: str
    archive_path: Path
    internal_path: str
    target_path: Path
    offset: int
    stored_size: int
    size: int
    sha256: str
    compression_mode: int


def _find_archive(game_dir: Path, name: str) -> Path:
    matches = [item for item in game_dir.iterdir() if item.is_file() and item.name.casefold() == name.casefold()]
    if len(matches) != 1:
        raise ExtractionError(f"expected exactly one {name} in {game_dir}, found {len(matches)}")
    return matches[0]


def _normalize_filter(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./").casefold()


def build_extraction_plan(
    game_dir: Path | str,
    workspace: Path | str,
    *,
    paths: Iterable[str] = (),
    extensions: Iterable[str] = (),
    resource_types: Iterable[str] = (),
    archives: Iterable[str] = (),
) -> list[ExtractionPlanItem]:
    game_path = Path(game_dir).resolve()
    workspace_path = Path(workspace).resolve()
    if not game_path.is_dir():
        raise ExtractionError(f"game directory does not exist: {game_path}")

    path_filters = {_normalize_filter(value) for value in paths}
    extension_filters = {
        (value if value.startswith(".") else f".{value}").casefold()
        for value in extensions
    }
    type_filters = {value.casefold() for value in resource_types}
    if not path_filters and not extension_filters and not type_filters:
        raise ExtractionError("at least one --path, --extension, or --type selector is required")

    requested_archives = {value.casefold() for value in archives}
    known_archives = ("MASTER.DAT", "CRITTER.DAT")
    unknown_archives = requested_archives - {name.casefold() for name in known_archives}
    if unknown_archives:
        raise ExtractionError(f"unknown archive selector: {', '.join(sorted(unknown_archives))}")

    plan: list[ExtractionPlanItem] = []
    target_keys: set[str] = set()
    for archive_name in known_archives:
        if requested_archives and archive_name.casefold() not in requested_archives:
            continue
        archive_path = _find_archive(game_path, archive_name)
        archive_stat = archive_path.stat()
        archive = parse_dat1(archive_path)
        source_folder = archive_path.stem.casefold()
        for entry in archive.entries:
            selected = (
                entry.internal_path.casefold() in path_filters
                or Path(entry.internal_path).suffix.casefold() in extension_filters
                or resource_type(entry.internal_path).casefold() in type_filters
            )
            if not selected:
                continue
            if not entry.path_is_safe:
                raise ExtractionError(
                    f"unsafe archive path {entry.internal_path!r}: {', '.join(entry.path_issues)}"
                )
            if entry.compression_mode not in (0x20, 0x40):
                raise ExtractionError(
                    f"unsupported compression mode 0x{entry.compression_mode:02X}: {entry.internal_path}"
                )
            if entry.size > MAX_ENTRY_SIZE:
                raise ExtractionError(f"entry exceeds extraction size limit: {entry.internal_path}")
            target = ensure_within_workspace(
                workspace_path,
                workspace_path / "raw" / source_folder / Path(*entry.internal_path.split("/")),
            )
            target_key = str(target).casefold()
            if target_key in target_keys:
                raise ExtractionError(f"multiple entries map to the same output: {target}")
            target_keys.add(target_key)
            plan.append(
                ExtractionPlanItem(
                    archive_path=archive_path,
                    archive_name=archive_path.name,
                    archive_size=archive_stat.st_size,
                    archive_mtime_ns=archive_stat.st_mtime_ns,
                    entry=entry,
                    target_path=target,
                )
            )

    if not plan:
        raise ExtractionError("selectors matched no DAT1 entries")
    return sorted(plan, key=lambda item: (item.archive_name.casefold(), item.entry.internal_path.casefold()))


def _read_entry(item: ExtractionPlanItem) -> bytes:
    entry = item.entry
    with item.archive_path.open("rb") as stream:
        stream.seek(entry.offset)
        packed = stream.read(entry.stored_size)
    if len(packed) != entry.stored_size:
        raise ExtractionError(f"truncated entry data: {entry.internal_path}")
    if entry.compression_mode == 0x20:
        data = packed
    elif entry.compression_mode == 0x40:
        try:
            data = decompress_dat1_payload(packed, expected_size=entry.size)
        except LzssError as exc:
            raise ExtractionError(f"cannot decompress {entry.internal_path}: {exc}") from exc
    else:
        raise ExtractionError(
            f"unsupported compression mode 0x{entry.compression_mode:02X}: {entry.internal_path}"
        )
    if len(data) != entry.size:
        raise ExtractionError(f"size mismatch after reading {entry.internal_path}")
    return data


def _write_file_atomic(target: Path, data: bytes, *, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as stream:
                temporary_name = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
        return

    created = False
    try:
        with target.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise


def execute_extraction(
    plan: Iterable[ExtractionPlanItem],
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> list[ExtractionResult]:
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    for item in items:
        ensure_within_workspace(workspace_path, item.target_path)
        current_stat = item.archive_path.stat()
        if (
            current_stat.st_size != item.archive_size
            or current_stat.st_mtime_ns != item.archive_mtime_ns
        ):
            raise ExtractionError(f"source archive changed after planning: {item.archive_path}")
        if item.target_path.exists() and not overwrite:
            raise ExtractionError(f"output already exists; refusing to overwrite: {item.target_path}")

    results: list[ExtractionResult] = []
    for item in items:
        data = _read_entry(item)
        ensure_within_workspace(workspace_path, item.target_path)
        _write_file_atomic(item.target_path, data, overwrite=overwrite)
        results.append(
            ExtractionResult(
                archive_name=item.archive_name,
                archive_path=item.archive_path,
                internal_path=item.entry.internal_path,
                target_path=item.target_path,
                offset=item.entry.offset,
                stored_size=item.entry.stored_size,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest().upper(),
                compression_mode=item.entry.compression_mode,
            )
        )
    return results


def write_extraction_manifest(results: Iterable[ExtractionResult], workspace: Path | str) -> Path:
    workspace_path = Path(workspace).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = ensure_within_workspace(
        workspace_path,
        workspace_path / "manifests" / f"extraction-{timestamp}.json",
    )
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "extract",
        "results": [
            {
                "source_archive": result.archive_name,
                "source_archive_path": str(result.archive_path.resolve()),
                "internal_path": result.internal_path,
                "source_offset": result.offset,
                "stored_size": result.stored_size,
                "output_path": str(result.target_path),
                "size": result.size,
                "sha256": result.sha256,
                "compression_mode": f"0x{result.compression_mode:02X}",
            }
            for result in results
        ],
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_file_atomic(target, encoded, overwrite=False)
    return target
