"""Render Fallout MAP square-tile floor layers without executing game logic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .frm import FalloutPalette, FrmFrame, encode_indexed_png, load_frm, load_palette
from .inventory import ensure_within_workspace
from .proto import ListDocument, load_lst
from .safe_io import write_file_atomic

MAP_RENDERER_VERSION = 1


class MapRenderError(ValueError):
    """Raised when structured map data cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class TilePlacement:
    square_index: int
    tile_id: int
    filename: str
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class FloorRenderPlan:
    map_json_path: Path
    map_json_size: int
    map_json_sha256: str
    map_name: str
    elevation: int
    grid_width: int
    grid_height: int
    tile_list: ListDocument
    tile_root: Path
    palette: FalloutPalette
    placements: tuple[TilePlacement, ...]
    used_tile_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_png: Path
    output_hash: Path

    @property
    def canvas_width(self) -> int:
        return self.bounds_right - self.bounds_left

    @property
    def canvas_height(self) -> int:
        return self.bounds_bottom - self.bounds_top


def _stable_json(path: Path | str) -> tuple[Path, bytes, dict[str, Any]]:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MapRenderError(f"map JSON changed while reading: {source}")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MapRenderError(f"invalid map JSON: {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MapRenderError("map JSON root must be an object")
    return source, data, payload


def _tile_layer(payload: dict[str, Any], elevation: int) -> tuple[int, int, list[int], list[int]]:
    if payload.get("schema_version") != 1 or payload.get("format") != "Fallout MAP/PRO/LST":
        raise MapRenderError("unsupported structured MAP JSON schema")
    layers = payload.get("tiles")
    if not isinstance(layers, list):
        raise MapRenderError("map JSON tiles must be an array")
    layer = next(
        (item for item in layers if isinstance(item, dict) and item.get("elevation") == elevation),
        None,
    )
    if layer is None:
        raise MapRenderError(f"map does not contain elevation {elevation}")
    width = layer.get("width")
    height = layer.get("height")
    floor_ids = layer.get("floor_ids")
    floor_flags = layer.get("floor_flags")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise MapRenderError("map tile grid has invalid dimensions")
    if not isinstance(floor_ids, list) or not isinstance(floor_flags, list):
        raise MapRenderError("map tile layer is missing floor ids or flags")
    expected = width * height
    if len(floor_ids) != expected or len(floor_flags) != expected:
        raise MapRenderError(
            f"map tile layer requires {expected} floor ids and flags, found "
            f"{len(floor_ids)} and {len(floor_flags)}"
        )
    if any(not isinstance(value, int) or value < 0 for value in floor_ids):
        raise MapRenderError("map tile layer contains an invalid floor id")
    if any(not isinstance(value, int) or value < 0 for value in floor_flags):
        raise MapRenderError("map tile layer contains an invalid floor flag")
    return width, height, floor_ids, floor_flags


def square_tile_screen_position(index: int, width: int) -> tuple[int, int]:
    """Return the top-left floor FRM position used by Fallout's square_coord."""
    if width <= 0 or index < 0:
        raise ValueError("square tile index and width must be positive")
    column = width - 1 - index % width
    row = index // width
    return 48 * column + 32 * row, -12 * column + 24 * row


def _casefold_file_index(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"tile directory does not exist: {root}")
    result: dict[str, Path] = {}
    for path in root.iterdir():
        if not path.is_file():
            continue
        key = path.name.casefold()
        if key in result:
            raise MapRenderError(f"case-insensitive duplicate tile filename: {path.name}")
        result[key] = path.resolve()
    return result


def _tile_frame(
    tile_id: int, tile_list: ListDocument, files: dict[str, Path]
) -> tuple[str, FrmFrame]:
    if tile_id >= len(tile_list.entries):
        raise MapRenderError(
            f"tile id {tile_id} is outside TILES.LST range 0..{len(tile_list.entries) - 1}"
        )
    filename = tile_list.entries[tile_id].filename
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.casefold() != ".frm"
    ):
        raise MapRenderError(f"unsafe or unsupported TILES.LST entry {tile_id}: {filename!r}")
    source = files.get(filename.casefold())
    if source is None:
        raise FileNotFoundError(f"tile FRM for id {tile_id} does not exist: {filename}")
    document = load_frm(source)
    direction = next((item for item in document.directions if item.index == 0), None)
    if direction is None:
        raise MapRenderError(f"tile FRM has no direction 0: {source}")
    sequence = document.sequences[direction.sequence_index]
    if not sequence.frames:
        raise MapRenderError(f"tile FRM has no frames: {source}")
    return filename, sequence.frames[0]


def map_render_output_paths(workspace: Path | str, output: Path | str) -> tuple[Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    png_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    return json_path, png_path, hash_path


def build_floor_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
) -> FloorRenderPlan:
    """Validate inputs and calculate a deterministic floor render plan without writing."""
    if elevation < 0 or elevation > 2:
        raise MapRenderError("elevation must be 0, 1, or 2")
    source, source_data, payload = _stable_json(map_json)
    width, height, floor_ids, floor_flags = _tile_layer(payload, elevation)
    tile_list = load_lst(tiles_list)
    tile_root = Path(tiles_dir).resolve()
    files = _casefold_file_index(tile_root)
    palette = load_palette(palette_path)
    map_name = payload.get("summary", {}).get("name")
    if not isinstance(map_name, str) or not map_name:
        raise MapRenderError("map JSON is missing summary.name")

    frames: dict[int, tuple[str, FrmFrame]] = {}
    for tile_id in sorted(set(floor_ids)):
        frames[tile_id] = _tile_frame(tile_id, tile_list, files)

    placements: list[TilePlacement] = []
    hidden = 0
    transparent = 0
    for index, (tile_id, flags) in enumerate(zip(floor_ids, floor_flags, strict=True)):
        if flags & 0x01:
            hidden += 1
            continue
        filename, frame = frames[tile_id]
        if not any(frame.pixels):
            transparent += 1
            continue
        x, y = square_tile_screen_position(index, width)
        placements.append(TilePlacement(index, tile_id, filename, x, y, frame))
    if not placements:
        raise MapRenderError("map floor contains no visible non-transparent tile pixels")

    left = min(item.screen_x for item in placements)
    top = min(item.screen_y for item in placements)
    right = max(item.screen_x + item.frame.width for item in placements)
    bottom = max(item.screen_y + item.frame.height for item in placements)
    output_json, output_png, output_hash = map_render_output_paths(workspace, output)
    sources = {source, tile_list.source_path, palette.source_path, *files.values()}
    collision = sources.intersection((output_json, output_png, output_hash))
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return FloorRenderPlan(
        map_json_path=source,
        map_json_size=len(source_data),
        map_json_sha256=hashlib.sha256(source_data).hexdigest().upper(),
        map_name=map_name,
        elevation=elevation,
        grid_width=width,
        grid_height=height,
        tile_list=tile_list,
        tile_root=tile_root,
        palette=palette,
        placements=tuple(placements),
        used_tile_ids=tuple(sorted({item.tile_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_png=output_png,
        output_hash=output_hash,
    )


def floor_render_summary(plan: FloorRenderPlan) -> dict[str, Any]:
    return {
        "map": plan.map_name,
        "elevation": plan.elevation,
        "grid_width": plan.grid_width,
        "grid_height": plan.grid_height,
        "visible_placements": len(plan.placements),
        "hidden_placements": plan.hidden_placements,
        "transparent_placements": plan.transparent_placements,
        "unique_tile_ids": len(plan.used_tile_ids),
        "canvas_width": plan.canvas_width,
        "canvas_height": plan.canvas_height,
        "origin_x": plan.bounds_left,
        "origin_y": plan.bounds_top,
    }


def _composite_floor(plan: FloorRenderPlan) -> bytes:
    pixels = bytearray(plan.canvas_width * plan.canvas_height)
    for placement in plan.placements:
        destination_x = placement.screen_x - plan.bounds_left
        destination_y = placement.screen_y - plan.bounds_top
        frame = placement.frame
        for row in range(frame.height):
            source_start = row * frame.width
            destination_start = (destination_y + row) * plan.canvas_width + destination_x
            for column, value in enumerate(frame.pixels[source_start : source_start + frame.width]):
                if value:
                    pixels[destination_start + column] = value
    return encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(pixels),
        plan.palette,
        transparent_index_zero=True,
    )


def write_floor_render(
    plan: FloorRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path]:
    """Compose and atomically write a floor PNG, metadata JSON, and checksum."""
    targets = (plan.output_json, plan.output_png, plan.output_hash)
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    png = _composite_floor(plan)
    png_sha256 = hashlib.sha256(png).hexdigest().upper()
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP floor render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(plan.map_json_path),
                "size": plan.map_json_size,
                "sha256": plan.map_json_sha256,
            },
            "tiles_list": {
                "path": str(plan.tile_list.source_path),
                "size": plan.tile_list.source_size,
                "sha256": plan.tile_list.source_sha256,
            },
            "tiles_directory": str(plan.tile_root),
            "palette": {
                "path": str(plan.palette.source_path),
                "size": plan.palette.source_size,
                "sha256": plan.palette.source_sha256,
            },
        },
        "summary": floor_render_summary(plan),
        "coordinates": {
            "column": "grid_width - 1 - (square_index % grid_width)",
            "row": "square_index // grid_width",
            "screen_x": "48 * column + 32 * row",
            "screen_y": "-12 * column + 24 * row",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": "square_index ascending",
        },
        "used_tiles": [
            {"id": tile_id, "filename": plan.tile_list.entries[tile_id].filename}
            for tile_id in plan.used_tile_ids
        ],
        "derived": {
            "floor_png": {
                "path": plan.output_png.name,
                "size": len(png),
                "sha256": png_sha256,
                "transparency": "palette index 0",
            }
        },
    }
    json_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = (
        f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {plan.output_json.name}\n"
    ).encode("ascii")
    write_file_atomic(plan.output_png, png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return plan.output_json, plan.output_png, plan.output_hash
