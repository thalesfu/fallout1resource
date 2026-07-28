"""Recoverable batch conversion for Interplay ACM audio."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .acm import (
    ACM_CONVERTER_VERSION,
    AcmAudio,
    AcmFormatError,
    acm_output_paths,
    load_acm,
    write_acm_export,
)
from .inventory import ensure_within_workspace, sha256_file
from .safe_io import write_file_atomic


class AcmBatchError(ValueError):
    """Raised when an ACM batch cannot be planned or resumed safely."""


@dataclass(frozen=True, slots=True)
class AcmBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int


@dataclass(frozen=True, slots=True)
class AcmBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    source_bytes: int
    output_bytes: int
    samples: int
    audio_duration_seconds: float
    partial_frame_files: int
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
            raise AcmBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(matches)}"
            )
        if "data" in available:
            raise AcmBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", matches[0])
    return available


def _output_path(source_name: str, relative: Path) -> Path:
    return (
        Path("output/audio")
        / source_name
        / relative.parent
        / relative.stem
        / f"{relative.stem}.json"
    )


def build_acm_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
) -> tuple[AcmBatchItem, ...]:
    """Discover extracted and loose ACM files without decoding or writing."""
    workspace_path = Path(workspace).resolve()
    available = _available_sources(workspace_path, game_dir)
    requested = {source.casefold() for source in sources}
    unknown = requested.difference(available)
    if unknown:
        raise AcmBatchError(f"unknown ACM source: {', '.join(sorted(unknown))}")
    selected_sources = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not selected_sources:
        raise AcmBatchError("no extracted or loose ACM source directories are available")

    plan: list[AcmBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in selected_sources:
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file() or source_path.suffix.casefold() != ".acm":
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            output = _output_path(source_name, relative)
            target = ensure_within_workspace(workspace_path, output)
            key = str(target).casefold()
            if key in targets:
                raise AcmBatchError(f"multiple ACM files map to the same output: {target}")
            targets.add(key)
            plan.append(
                AcmBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=relative.as_posix(),
                    output=output,
                    size=source_path.stat().st_size,
                )
            )
    if not plan:
        raise AcmBatchError("no ACM files matched the selected sources")
    return tuple(
        sorted(
            plan,
            key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()),
        )
    )


def _manifest_source_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _existing_outputs_are_current(
    item: AcmBatchItem,
    workspace: Path,
    audio: AcmAudio,
) -> bool:
    json_path, wav_path, hash_path = acm_output_paths(workspace, item.output)
    if not all(path.is_file() for path in (json_path, wav_path, hash_path)):
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        summary = metadata["summary"]
        wav = metadata["derived"]["wav"]
        if not all(isinstance(value, dict) for value in (source, generator, summary, wav)):
            return False
        if (
            metadata.get("schema_version") != 1
            or source.get("sha256") != audio.source_sha256
            or source.get("size") != item.size
            or generator.get("name") != "fallout1resource"
            or generator.get("component") != "acm"
            or generator.get("component_version") != ACM_CONVERTER_VERSION
            or summary.get("bitstream_zero_pad_bytes") != audio.bitstream_zero_pad_bytes
            or wav.get("path") != wav_path.relative_to(workspace).as_posix()
            or wav.get("size") != wav_path.stat().st_size
            or wav.get("sha256") != sha256_file(wav_path)
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


def execute_acm_batch(
    plan: tuple[AcmBatchItem, ...] | list[AcmBatchItem],
    workspace: Path | str,
    *,
    overwrite: bool = False,
) -> AcmBatchResult:
    """Decode every planned ACM while preserving per-file failures."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0
    samples = 0
    audio_duration = 0.0
    partial_frame_files = 0

    for item in items:
        try:
            audio = load_acm(item.source_path)
            json_path, wav_path, hash_path = acm_output_paths(workspace_path, item.output)
            existing = [path for path in (json_path, wav_path, hash_path) if path.exists()]
            if existing and not overwrite:
                if _existing_outputs_are_current(item, workspace_path, audio):
                    skipped += 1
                    status = "skipped_verified"
                else:
                    raise AcmBatchError(f"existing outputs are incomplete or stale: {json_path}")
            else:
                write_acm_export(
                    audio,
                    workspace_path,
                    item.output,
                    overwrite=overwrite,
                )
                output_bytes += sum(
                    path.stat().st_size for path in (json_path, wav_path, hash_path)
                )
                converted += 1
                status = "converted"

            duration = audio.sample_count / (audio.sample_rate * audio.channels)
            partial = audio.sample_count % audio.channels
            samples += audio.sample_count
            audio_duration += duration
            partial_frame_files += bool(partial)
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": audio.source_sha256,
                    "status": status,
                    "output": json_path.relative_to(workspace_path).as_posix(),
                    "channels": audio.channels,
                    "sample_rate": audio.sample_rate,
                    "sample_count": audio.sample_count,
                    "duration_seconds": duration,
                    "wav_padding_samples": (-audio.sample_count) % audio.channels,
                    "error": None,
                }
            )
        except (FileNotFoundError, AcmBatchError, AcmFormatError, OSError, ValueError) as exc:
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
        "mode": "convert-acm-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
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
            "samples": samples,
            "audio_duration_seconds": audio_duration,
            "partial_frame_files": partial_frame_files,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-acm-{timestamp}.json"
    )
    write_file_atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        overwrite=False,
    )
    return AcmBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        samples=samples,
        audio_duration_seconds=audio_duration,
        partial_frame_files=partial_frame_files,
        duration_seconds=duration,
    )


def acm_batch_plan_summary(plan: tuple[AcmBatchItem, ...]) -> dict[str, Any]:
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(Counter(item.source_name for item in plan).items())),
    }
