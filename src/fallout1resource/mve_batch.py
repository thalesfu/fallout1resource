"""Recoverable batch conversion for Interplay MVE movies."""

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
from .mve import (
    MVE_CONVERTER_VERSION,
    ExternalTool,
    MveDocument,
    MveFormatError,
    inspect_ffmpeg,
    load_mve,
    mve_output_paths,
    write_mve_export,
)
from .safe_io import write_file_atomic


class MveBatchError(ValueError):
    """Raised when an MVE batch cannot be planned or resumed safely."""


@dataclass(frozen=True, slots=True)
class MveBatchItem:
    source_name: str
    source_path: Path
    internal_path: str
    output: Path
    size: int


@dataclass(frozen=True, slots=True)
class MveBatchResult:
    manifest_path: Path
    selected: int
    converted: int
    skipped_verified: int
    failed: int
    source_bytes: int
    output_bytes: int
    frames: int
    movie_duration_seconds: float
    silent_movies: int
    duration_seconds: float


def _available_sources(workspace: Path, game_dir: Path | str | None) -> dict[str, tuple[str, Path]]:
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
            raise MveBatchError(
                f"expected exactly one DATA directory in {game_path}, found {len(matches)}"
            )
        if "data" in available:
            raise MveBatchError("raw source name 'data' conflicts with the loose DATA source")
        available["data"] = ("data", matches[0])
    return available


def _output_path(source_name: str, relative: Path) -> Path:
    return (
        Path("output/video")
        / source_name
        / relative.parent
        / relative.stem
        / f"{relative.stem}.json"
    )


def build_mve_batch_plan(
    workspace: Path | str,
    *,
    sources: list[str] | tuple[str, ...] = (),
    game_dir: Path | str | None = None,
) -> tuple[MveBatchItem, ...]:
    """Discover extracted and loose MVE files without parsing or writing."""
    workspace_path = Path(workspace).resolve()
    available = _available_sources(workspace_path, game_dir)
    requested = {source.casefold() for source in sources}
    unknown = requested.difference(available)
    if unknown:
        raise MveBatchError(f"unknown MVE source: {', '.join(sorted(unknown))}")
    selected_sources = [
        value for key, value in sorted(available.items()) if not requested or key in requested
    ]
    if not selected_sources:
        raise MveBatchError("no extracted or loose MVE source directories are available")

    plan: list[MveBatchItem] = []
    targets: set[str] = set()
    for source_name, source_directory in selected_sources:
        for source_path in sorted(source_directory.rglob("*")):
            if not source_path.is_file() or source_path.suffix.casefold() != ".mve":
                continue
            relative = source_path.relative_to(source_directory)
            if relative.parts and relative.parts[0].casefold() == "savegame":
                continue
            output = _output_path(source_name, relative)
            target = ensure_within_workspace(workspace_path, output)
            key = str(target).casefold()
            if key in targets:
                raise MveBatchError(f"multiple MVE files map to the same output: {target}")
            targets.add(key)
            plan.append(
                MveBatchItem(
                    source_name=source_name,
                    source_path=source_path.resolve(),
                    internal_path=relative.as_posix(),
                    output=output,
                    size=source_path.stat().st_size,
                )
            )
    if not plan:
        raise MveBatchError("no MVE files matched the selected sources")
    return tuple(
        sorted(plan, key=lambda item: (item.source_name.casefold(), item.internal_path.casefold()))
    )


def _manifest_source_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _derived_paths(workspace: Path, item: MveBatchItem, document: MveDocument) -> dict[str, Path]:
    json_path, csv_path, poster_path, audio_path, preview_path, hash_path = mve_output_paths(
        workspace, item.output, document
    )
    paths = {
        "json": json_path,
        "segments_csv": csv_path,
        "poster_png": poster_path,
        "preview_mp4": preview_path,
        "hash": hash_path,
    }
    if audio_path is not None:
        paths["audio_wav"] = audio_path
    return paths


def _existing_outputs_are_current(
    item: MveBatchItem,
    workspace: Path,
    document: MveDocument,
    tool: ExternalTool,
) -> bool:
    paths = _derived_paths(workspace, item, document)
    if not all(path.is_file() for path in paths.values()):
        return False
    json_path = paths["json"]
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        source = metadata["source"]
        generator = metadata["generator"]
        summary = metadata["summary"]
        external = metadata["external_tool"]
        derived = metadata["derived"]
        if not all(
            isinstance(value, dict) for value in (source, generator, summary, external, derived)
        ):
            return False
        if (
            metadata.get("schema_version") != 1
            or source.get("sha256") != document.source_sha256
            or source.get("size") != item.size
            or generator.get("name") != "fallout1resource"
            or generator.get("component") != "mve"
            or generator.get("component_version") != MVE_CONVERTER_VERSION
            or summary.get("frame_count") != document.frame_count
            or summary.get("display_count") != document.display_count
            or external.get("ffmpeg_sha256") != tool.ffmpeg_sha256
            or external.get("ffprobe_sha256") != tool.ffprobe_sha256
            or external.get("runtime_manifest_sha256") != tool.runtime_manifest_sha256
        ):
            return False
        for label, path in paths.items():
            if label in {"json", "hash"}:
                continue
            record = derived.get(label)
            if not isinstance(record, dict) or (
                record.get("path") != path.relative_to(workspace).as_posix()
                or record.get("size") != path.stat().st_size
                or record.get("sha256") != sha256_file(path)
            ):
                return False
    except (KeyError, TypeError, json.JSONDecodeError, OSError):
        return False
    checksum = paths["hash"].read_text(encoding="ascii").strip().split("  ", 1)
    return (
        len(checksum) == 2
        and checksum[0] == sha256_file(json_path)
        and checksum[1] == json_path.name
    )


def execute_mve_batch(
    plan: tuple[MveBatchItem, ...] | list[MveBatchItem],
    workspace: Path | str,
    ffmpeg_path: Path | str,
    *,
    overwrite: bool = False,
) -> MveBatchResult:
    """Convert every planned MVE while preserving per-file failures."""
    workspace_path = Path(workspace).resolve()
    items = list(plan)
    tool = inspect_ffmpeg(ffmpeg_path)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    records: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    output_bytes = 0
    frames = 0
    movie_duration = 0.0
    silent_movies = 0

    for item in items:
        try:
            document = load_mve(item.source_path)
            paths = _derived_paths(workspace_path, item, document)
            existing = [path for path in paths.values() if path.exists()]
            if existing and not overwrite:
                if _existing_outputs_are_current(item, workspace_path, document, tool):
                    skipped += 1
                    status = "skipped_verified"
                else:
                    raise MveBatchError(
                        f"existing outputs are incomplete or stale: {paths['json']}"
                    )
            else:
                write_mve_export(
                    document,
                    workspace_path,
                    item.output,
                    tool.ffmpeg_path,
                    overwrite=overwrite,
                    inspected_tool=tool,
                )
                output_bytes += sum(path.stat().st_size for path in paths.values())
                converted += 1
                status = "converted"

            duration = (
                document.frame_count * document.timing.frame_duration_microseconds / 1_000_000
            )
            frames += document.frame_count
            movie_duration += duration
            silent_movies += document.audio is None
            records.append(
                {
                    "source_path": _manifest_source_path(item.source_path, workspace_path),
                    "source_name": item.source_name,
                    "internal_path": item.internal_path,
                    "source_size": item.size,
                    "source_sha256": document.source_sha256,
                    "status": status,
                    "output": paths["json"].relative_to(workspace_path).as_posix(),
                    "width": document.video.width,
                    "height": document.video.height,
                    "bits_per_pixel": document.video.bits_per_pixel,
                    "frames": document.frame_count,
                    "display_count": document.display_count,
                    "duration_seconds": duration,
                    "has_audio": document.audio is not None,
                    "video_data_formats": [
                        f"0x{value:02X}" for value in document.video_data_formats
                    ],
                    "error": None,
                }
            )
        except (FileNotFoundError, MveBatchError, MveFormatError, OSError, ValueError) as exc:
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
        "mode": "convert-mve-batch",
        "generator": {"name": "fallout1resource", "version": __version__},
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(duration, 6),
        "options": {
            "overwrite": overwrite,
            "sources": sorted({item.source_name for item in items}),
            "ffmpeg_path": str(tool.ffmpeg_path),
            "ffmpeg_sha256": tool.ffmpeg_sha256,
            "ffprobe_sha256": tool.ffprobe_sha256,
            "runtime_manifest_sha256": tool.runtime_manifest_sha256,
        },
        "summary": {
            "selected": len(items),
            "converted": converted,
            "skipped_verified": skipped,
            "failed": failed,
            "source_bytes": sum(item.size for item in items),
            "output_bytes_written": output_bytes,
            "frames": frames,
            "movie_duration_seconds": movie_duration,
            "silent_movies": silent_movies,
        },
        "results": records,
    }
    timestamp = finished_at.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = ensure_within_workspace(
        workspace_path, Path("manifests") / f"batch-mve-{timestamp}.json"
    )
    write_file_atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        overwrite=False,
    )
    return MveBatchResult(
        manifest_path=manifest_path,
        selected=len(items),
        converted=converted,
        skipped_verified=skipped,
        failed=failed,
        source_bytes=sum(item.size for item in items),
        output_bytes=output_bytes,
        frames=frames,
        movie_duration_seconds=movie_duration,
        silent_movies=silent_movies,
        duration_seconds=duration,
    )


def mve_batch_plan_summary(plan: tuple[MveBatchItem, ...]) -> dict[str, Any]:
    return {
        "selected": len(plan),
        "source_bytes": sum(item.size for item in plan),
        "source_counts": dict(sorted(Counter(item.source_name for item in plan).items())),
    }
