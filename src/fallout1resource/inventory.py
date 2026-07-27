"""Build reproducible resource inventories without extracting archive contents."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dat1 import COMPRESSION_NAMES, Dat1Archive, parse_dat1

RESOURCE_TYPES = {
    ".ACM": "audio",
    ".FRM": "image",
    ".INT": "script",
    ".LST": "index",
    ".MAP": "map",
    ".MSG": "text",
    ".MVE": "video",
    ".PAL": "palette",
    ".PRO": "prototype",
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest().upper()


def resource_type(path: str) -> str:
    return RESOURCE_TYPES.get(Path(path).suffix.upper(), "other")


def ensure_within_workspace(workspace: Path | str, target: Path | str) -> Path:
    workspace_path = Path(workspace).resolve()
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = workspace_path / target_path
    target_path = target_path.resolve(strict=False)
    try:
        target_path.relative_to(workspace_path)
    except ValueError as exc:
        raise ValueError(f"output must stay inside workspace: {target_path}") from exc
    if target_path == workspace_path:
        raise ValueError("output must be a file below workspace")
    return target_path


def _find_case_insensitive(directory: Path, name: str) -> Path:
    matches = [
        item
        for item in directory.iterdir()
        if item.is_file() and item.name.casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly one {name} in {directory}, found {len(matches)}")
    return matches[0]


def _archive_entries(
    archive: Dat1Archive, source_hash: str | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = {
        "kind": "dat1",
        "path": str(archive.path.resolve()),
        "name": archive.path.name,
        "size": archive.path.stat().st_size,
        "sha256": source_hash,
        "directory_count": archive.directory_count,
        "entry_count": len(archive.entries),
        "metadata_size": archive.metadata_size,
    }
    entries = [
        {
            "source_kind": "dat1",
            "source_name": archive.path.name,
            "internal_path": entry.internal_path,
            "type": resource_type(entry.internal_path),
            "size": entry.size,
            "stored_size": entry.stored_size,
            "offset": entry.offset,
            "compression_mode": f"0x{entry.compression_mode:02X}",
            "compression": COMPRESSION_NAMES[entry.compression_mode],
            "sha256": None,
            "path_is_safe": entry.path_is_safe,
            "path_issues": list(entry.path_issues),
        }
        for entry in archive.entries
    ]
    return source, entries


def _scan_loose_data(
    data_dir: Path, hash_files: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    for root, directories, files in os.walk(data_dir):
        directories[:] = sorted(name for name in directories if name.casefold() != "savegame")
        root_path = Path(root)
        for name in sorted(files):
            file_path = root_path / name
            relative_path = file_path.relative_to(data_dir).as_posix()
            stat = file_path.stat()
            entries.append(
                {
                    "source_kind": "loose",
                    "source_name": "DATA",
                    "internal_path": relative_path,
                    "type": resource_type(relative_path),
                    "size": stat.st_size,
                    "stored_size": stat.st_size,
                    "offset": None,
                    "compression_mode": None,
                    "compression": "none",
                    "sha256": sha256_file(file_path) if hash_files else None,
                    "path_is_safe": True,
                    "path_issues": [],
                }
            )
    source = {
        "kind": "loose",
        "path": str(data_dir.resolve()),
        "name": "DATA",
        "entry_count": len(entries),
        "excluded_directories": ["SAVEGAME"],
        "files_hashed": hash_files,
    }
    return source, entries


def _duplicates(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    names: dict[str, str] = {}
    for entry in entries:
        key = entry["internal_path"].casefold()
        names.setdefault(key, entry["internal_path"])
        groups[key].append(
            {"source_kind": entry["source_kind"], "source_name": entry["source_name"]}
        )
    return [
        {"internal_path": names[key], "sources": sources}
        for key, sources in sorted(groups.items())
        if len(sources) > 1
    ]


def build_inventory(
    game_dir: Path | str,
    *,
    hash_sources: bool = True,
    hash_loose_files: bool = False,
) -> dict[str, Any]:
    game_path = Path(game_dir).resolve()
    if not game_path.is_dir():
        raise FileNotFoundError(f"game directory does not exist: {game_path}")

    sources: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for archive_name in ("MASTER.DAT", "CRITTER.DAT"):
        archive_path = _find_case_insensitive(game_path, archive_name)
        archive = parse_dat1(archive_path)
        source, archive_entries = _archive_entries(
            archive,
            sha256_file(archive_path) if hash_sources else None,
        )
        sources.append(source)
        entries.extend(archive_entries)

    data_dir = next(
        (item for item in game_path.iterdir() if item.is_dir() and item.name.casefold() == "data"),
        None,
    )
    if data_dir is not None:
        source, loose_entries = _scan_loose_data(data_dir, hash_loose_files)
        sources.append(source)
        entries.extend(loose_entries)

    type_counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        type_counts[entry["type"]] += 1
    unsafe_paths = [entry["internal_path"] for entry in entries if not entry["path_is_safe"]]

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "game_directory": str(game_path),
        "mode": "inventory-only",
        "sources": sources,
        "summary": {
            "entry_count": len(entries),
            "type_counts": dict(sorted(type_counts.items())),
            "unsafe_path_count": len(unsafe_paths),
            "duplicate_path_count": 0,
        },
        "unsafe_paths": unsafe_paths,
        "duplicates": [],
        "entries": entries,
    }


def write_inventory(
    manifest: dict[str, Any], workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path]:
    output_path = ensure_within_workspace(workspace, output)
    csv_path = output_path.with_suffix(".csv")
    hash_path = output_path.with_suffix(output_path.suffix + ".sha256")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duplicates = _duplicates(manifest["entries"])
    manifest["duplicates"] = duplicates
    manifest["summary"]["duplicate_path_count"] = len(duplicates)

    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fieldnames = [
        "source_kind",
        "source_name",
        "internal_path",
        "type",
        "size",
        "stored_size",
        "offset",
        "compression_mode",
        "compression",
        "sha256",
        "path_is_safe",
        "path_issues",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for entry in manifest["entries"]:
            row = dict(entry)
            row["path_issues"] = "; ".join(row["path_issues"])
            writer.writerow(row)

    digest = sha256_file(output_path)
    hash_path.write_text(f"{digest}  {output_path.name}\n", encoding="ascii")
    return output_path, csv_path, hash_path
