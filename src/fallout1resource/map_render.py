"""Render Fallout MAP square-tile floor layers without executing game logic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .frm import (
    FalloutPalette,
    FrmDirection,
    FrmDocument,
    FrmFrame,
    encode_indexed_png,
    load_frm,
    load_palette,
)
from .inventory import ensure_within_workspace
from .proto import ListDocument, load_lst
from .safe_io import write_file_atomic

MAP_RENDERER_VERSION = 2
HEX_GRID_WIDTH = 200
HEX_GRID_HEIGHT = 200
OBJECT_HIDDEN = 0x01
OBJECT_FLAT = 0x08
WALL_FID_TYPE = 3


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


@dataclass(frozen=True, slots=True)
class WallPlacement:
    source_index: int
    object_id: int
    tile: int
    art_id: int
    filename: str
    rotation: int
    frame_index: int
    flags: int
    direction_x_offset: int
    direction_y_offset: int
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class WallRenderPlan:
    floor: FloorRenderPlan
    wall_list: ListDocument
    wall_root: Path
    placements: tuple[WallPlacement, ...]
    used_wall_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    flat_placements: int
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_wall_png: Path
    output_composite_png: Path
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


def hex_tile_screen_position(tile: int, width: int = HEX_GRID_WIDTH) -> tuple[int, int]:
    """Return Fallout's hex tile origin in the floor renderer's global coordinates."""
    if width <= 0 or tile < 0 or tile >= width * HEX_GRID_HEIGHT:
        raise ValueError("hex tile must be inside the 200-row map grid")
    column = width - 1 - tile % width
    row = tile // width
    half_column = column // 2
    x = 48 * half_column + 16 * row
    y = -12 * half_column + 12 * row
    if column & 1:
        x += 32
    # tile_coord is expressed relative to square_coord's (-16, -2) viewport offset.
    return x + 16, y + 2


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


def wall_render_output_paths(
    workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    composite_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    stem = json_path.stem
    wall_stem = f"{stem[:-len('-floor-walls')]}-walls" if stem.endswith("-floor-walls") else f"{stem}-walls"
    wall_path = ensure_within_workspace(workspace, json_path.with_name(f"{wall_stem}.png"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, wall_path, composite_path, hash_path}) != 4:
        raise MapRenderError("wall render output paths collide")
    return json_path, wall_path, composite_path, hash_path


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


def _wall_document(
    art_id: int, wall_list: ListDocument, files: dict[str, Path]
) -> tuple[str, FrmDocument]:
    if art_id >= len(wall_list.entries):
        raise MapRenderError(
            f"wall art id {art_id} is outside WALLS.LST range 0..{len(wall_list.entries) - 1}"
        )
    filename = wall_list.entries[art_id].filename
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.casefold() != ".frm"
    ):
        raise MapRenderError(f"unsafe or unsupported WALLS.LST entry {art_id}: {filename!r}")
    source = files.get(filename.casefold())
    if source is None:
        raise FileNotFoundError(f"wall FRM for art id {art_id} does not exist: {filename}")
    return filename, load_frm(source)


def _wall_frame(
    document: FrmDocument, rotation: int, frame_index: int
) -> tuple[FrmDirection, FrmFrame]:
    direction = next((item for item in document.directions if item.index == rotation), None)
    if direction is None:
        raise MapRenderError(f"wall FRM has no direction {rotation}: {document.source_path}")
    sequence = document.sequences[direction.sequence_index]
    if frame_index < 0 or frame_index >= len(sequence.frames):
        raise MapRenderError(
            f"wall frame {frame_index} is outside range 0..{len(sequence.frames) - 1}: "
            f"{document.source_path}"
        )
    return direction, sequence.frames[frame_index]


def build_wall_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    walls_list: Path | str,
    walls_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
) -> WallRenderPlan:
    """Validate and plan matching wall-only and floor-plus-wall renders."""
    output_json, output_wall_png, output_composite_png, output_hash = wall_render_output_paths(
        workspace, output
    )
    floor_output = output_json.with_name(f"elevation-{elevation}-floor.json")
    floor = build_floor_render_plan(
        map_json,
        tiles_list,
        tiles_dir,
        palette_path,
        elevation,
        workspace,
        floor_output,
    )
    source, source_data, payload = _stable_json(map_json)
    if (
        source != floor.map_json_path
        or hashlib.sha256(source_data).hexdigest().upper() != floor.map_json_sha256
    ):
        raise MapRenderError(f"map JSON changed while building render plan: {source}")
    objects = payload.get("objects")
    entries = objects.get("entries") if isinstance(objects, dict) else None
    if not isinstance(entries, list):
        raise MapRenderError("map JSON objects.entries must be an array")

    wall_list = load_lst(walls_list)
    wall_root = Path(walls_dir).resolve()
    files = _casefold_file_index(wall_root)
    selected: list[tuple[int, dict[str, Any]]] = []
    hidden = 0
    flat = 0
    for source_index, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("elevation_group") != elevation:
            continue
        prototype = item.get("prototype")
        if not isinstance(prototype, dict) or prototype.get("type") != "wall":
            continue
        flags = item.get("flags")
        if not isinstance(flags, int):
            raise MapRenderError(f"wall object {source_index} has invalid flags")
        if flags & OBJECT_FLAT:
            flat += 1
        if flags & OBJECT_HIDDEN:
            hidden += 1
            continue
        selected.append((source_index, item))

    documents: dict[int, tuple[str, FrmDocument]] = {}
    for source_index, item in selected:
        fid = item.get("fid")
        if not isinstance(fid, int) or fid < 0:
            raise MapRenderError(f"wall object {source_index} has invalid FID")
        if (fid >> 24) & 0x0F != WALL_FID_TYPE:
            raise MapRenderError(f"wall object {source_index} FID is not wall art: 0x{fid:08X}")
        art_id = fid & 0x0FFF
        if art_id not in documents:
            documents[art_id] = _wall_document(art_id, wall_list, files)

    placements: list[WallPlacement] = []
    transparent = 0
    for source_index, item in selected:
        tile = item.get("tile")
        object_id = item.get("object_id")
        rotation = item.get("rotation")
        frame_index = item.get("frame")
        object_x = item.get("x")
        object_y = item.get("y")
        flags = item["flags"]
        if not isinstance(tile, int) or tile < 0 or tile >= HEX_GRID_WIDTH * HEX_GRID_HEIGHT:
            raise MapRenderError(f"wall object {source_index} has invalid tile")
        if not isinstance(object_id, int):
            raise MapRenderError(f"wall object {source_index} has invalid object id")
        if not isinstance(rotation, int) or rotation < 0 or rotation >= 6:
            raise MapRenderError(f"wall object {source_index} has invalid rotation")
        if not isinstance(frame_index, int):
            raise MapRenderError(f"wall object {source_index} has invalid frame")
        if not isinstance(object_x, int) or not isinstance(object_y, int):
            raise MapRenderError(f"wall object {source_index} has invalid pixel offset")
        art_id = item["fid"] & 0x0FFF
        filename, document = documents[art_id]
        direction, frame = _wall_frame(document, rotation, frame_index)
        if not any(frame.pixels):
            transparent += 1
            continue
        hex_x, hex_y = hex_tile_screen_position(tile)
        anchor_x = hex_x + 16 + direction.x_offset + object_x
        anchor_y = hex_y + 8 + direction.y_offset + object_y
        placements.append(
            WallPlacement(
                source_index=source_index,
                object_id=object_id,
                tile=tile,
                art_id=art_id,
                filename=filename,
                rotation=rotation,
                frame_index=frame_index,
                flags=flags,
                direction_x_offset=direction.x_offset,
                direction_y_offset=direction.y_offset,
                screen_x=anchor_x - frame.width // 2,
                screen_y=anchor_y - (frame.height - 1),
                frame=frame,
            )
        )
    if not placements:
        raise MapRenderError("map elevation contains no visible non-transparent wall pixels")
    placements.sort(
        key=lambda item: (0 if item.flags & OBJECT_FLAT else 1, item.tile, item.source_index)
    )

    left = min(floor.bounds_left, *(item.screen_x for item in placements))
    top = min(floor.bounds_top, *(item.screen_y for item in placements))
    right = max(floor.bounds_right, *(item.screen_x + item.frame.width for item in placements))
    bottom = max(floor.bounds_bottom, *(item.screen_y + item.frame.height for item in placements))
    sources = {source, wall_list.source_path, *files.values()}
    collision = sources.intersection(
        (output_json, output_wall_png, output_composite_png, output_hash)
    )
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return WallRenderPlan(
        floor=floor,
        wall_list=wall_list,
        wall_root=wall_root,
        placements=tuple(placements),
        used_wall_ids=tuple(sorted({item.art_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        flat_placements=flat,
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_wall_png=output_wall_png,
        output_composite_png=output_composite_png,
        output_hash=output_hash,
    )


def wall_render_summary(plan: WallRenderPlan) -> dict[str, Any]:
    return {
        "map": plan.floor.map_name,
        "elevation": plan.floor.elevation,
        "visible_floor_placements": len(plan.floor.placements),
        "validated_wall_objects": (
            len(plan.placements) + plan.hidden_placements + plan.transparent_placements
        ),
        "visible_wall_placements": len(plan.placements),
        "hidden_wall_placements": plan.hidden_placements,
        "transparent_wall_placements": plan.transparent_placements,
        "flat_wall_objects": plan.flat_placements,
        "unique_visible_wall_ids": len(plan.used_wall_ids),
        "canvas_width": plan.canvas_width,
        "canvas_height": plan.canvas_height,
        "origin_x": plan.bounds_left,
        "origin_y": plan.bounds_top,
    }


def _blit_placements(
    pixels: bytearray,
    canvas_width: int,
    bounds_left: int,
    bounds_top: int,
    placements: tuple[TilePlacement, ...] | tuple[WallPlacement, ...],
) -> None:
    for placement in placements:
        destination_x = placement.screen_x - bounds_left
        destination_y = placement.screen_y - bounds_top
        frame = placement.frame
        for row in range(frame.height):
            source_start = row * frame.width
            destination_start = (destination_y + row) * canvas_width + destination_x
            for column, value in enumerate(frame.pixels[source_start : source_start + frame.width]):
                if value:
                    pixels[destination_start + column] = value


def _composite_floor(plan: FloorRenderPlan) -> bytes:
    pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
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


def _wall_pngs(plan: WallRenderPlan) -> tuple[bytes, bytes]:
    wall_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        wall_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
    composite_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.floor.placements,
    )
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
    wall_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(wall_pixels),
        plan.floor.palette,
        transparent_index_zero=True,
    )
    composite_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(composite_pixels),
        plan.floor.palette,
        transparent_index_zero=True,
    )
    return wall_png, composite_png


def write_wall_render(
    plan: WallRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path, Path]:
    """Atomically write a wall layer, floor-wall composite, metadata, and checksum."""
    targets = (
        plan.output_json,
        plan.output_wall_png,
        plan.output_composite_png,
        plan.output_hash,
    )
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    wall_png, composite_png = _wall_pngs(plan)
    wall_sha256 = hashlib.sha256(wall_png).hexdigest().upper()
    composite_sha256 = hashlib.sha256(composite_png).hexdigest().upper()
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP floor and wall render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(plan.floor.map_json_path),
                "size": plan.floor.map_json_size,
                "sha256": plan.floor.map_json_sha256,
            },
            "tiles_list": {
                "path": str(plan.floor.tile_list.source_path),
                "size": plan.floor.tile_list.source_size,
                "sha256": plan.floor.tile_list.source_sha256,
            },
            "tiles_directory": str(plan.floor.tile_root),
            "walls_list": {
                "path": str(plan.wall_list.source_path),
                "size": plan.wall_list.source_size,
                "sha256": plan.wall_list.source_sha256,
            },
            "walls_directory": str(plan.wall_root),
            "palette": {
                "path": str(plan.floor.palette.source_path),
                "size": plan.floor.palette.source_size,
                "sha256": plan.floor.palette.source_sha256,
            },
        },
        "summary": wall_render_summary(plan),
        "coordinates": {
            "hex_column": "199 - (tile % 200)",
            "hex_row": "tile // 200",
            "anchor_x": "hex_x + 16 + direction_x_offset + object_x",
            "anchor_y": "hex_y + 8 + direction_y_offset + object_y",
            "frame_left": "anchor_x - frame_width // 2",
            "frame_top": "anchor_y - (frame_height - 1)",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": "OBJECT_FLAT first, then non-flat; tile and MAP source order ascending",
        },
        "used_walls": [
            {
                "id": art_id,
                "filename": plan.wall_list.entries[art_id].filename,
                "placements": sum(item.art_id == art_id for item in plan.placements),
            }
            for art_id in plan.used_wall_ids
        ],
        "derived": {
            "wall_png": {
                "path": plan.output_wall_png.name,
                "size": len(wall_png),
                "sha256": wall_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_png": {
                "path": plan.output_composite_png.name,
                "size": len(composite_png),
                "sha256": composite_sha256,
                "transparency": "palette index 0",
            },
        },
    }
    json_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = (
        f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {plan.output_json.name}\n"
    ).encode("ascii")
    write_file_atomic(plan.output_wall_png, wall_png, overwrite=overwrite)
    write_file_atomic(plan.output_composite_png, composite_png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return (
        plan.output_json,
        plan.output_wall_png,
        plan.output_composite_png,
        plan.output_hash,
    )
