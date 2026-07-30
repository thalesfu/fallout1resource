"""Render Fallout MAP square-tile floor layers without executing game logic."""

from __future__ import annotations

import hashlib
import io
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
from .msg import MsgDocument, load_msg
from .proto import ListDocument, load_lst
from .safe_io import write_file_atomic

MAP_RENDERER_VERSION = 11
HEX_GRID_WIDTH = 200
HEX_GRID_HEIGHT = 200
ITEM_OUTLINE_RADIUS = 2
ITEM_OUTLINE_TARGET_RGB = (255, 255, 0)
CRITTER_OUTLINE_RADIUS = 2
CRITTER_OUTLINE_TARGET_RGB = (0, 255, 255)
OBJECT_HIDDEN = 0x01
OBJECT_FLAT = 0x08
ITEM_FID_TYPE = 0
CRITTER_FID_TYPE = 1
SCENERY_FID_TYPE = 2
WALL_FID_TYPE = 3
DOOR_OPEN = 0x01
DOOR_LOCKED = 0x02000000
DOOR_JAMMED = 0x04000000


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


@dataclass(frozen=True, slots=True)
class DoorPlacement:
    source_index: int
    object_id: int
    tile: int
    art_id: int
    filename: str
    rotation: int
    frame_index: int
    flags: int
    open_flags: int
    direction_x_offset: int
    direction_y_offset: int
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class DoorRenderPlan:
    wall: WallRenderPlan
    scenery_list: ListDocument
    scenery_root: Path
    placements: tuple[DoorPlacement, ...]
    used_door_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    flat_placements: int
    closed_placements: int
    open_or_transition_placements: int
    target_open_placements: int
    locked_placements: int
    jammed_placements: int
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_door_png: Path
    output_composite_png: Path
    output_hash: Path

    @property
    def canvas_width(self) -> int:
        return self.bounds_right - self.bounds_left

    @property
    def canvas_height(self) -> int:
        return self.bounds_bottom - self.bounds_top


@dataclass(frozen=True, slots=True)
class SceneryPlacement:
    source_index: int
    object_id: int
    tile: int
    art_id: int
    filename: str
    subtype: int
    subtype_name: str
    rotation: int
    frame_index: int
    flags: int
    direction_x_offset: int
    direction_y_offset: int
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class SceneryRenderPlan:
    door: DoorRenderPlan
    placements: tuple[SceneryPlacement, ...]
    used_scenery_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    flat_placements: int
    subtype_counts: tuple[tuple[str, int], ...]
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_scenery_png: Path
    output_composite_png: Path
    output_hash: Path

    @property
    def canvas_width(self) -> int:
        return self.bounds_right - self.bounds_left

    @property
    def canvas_height(self) -> int:
        return self.bounds_bottom - self.bounds_top


@dataclass(frozen=True, slots=True)
class ItemPlacement:
    source_index: int
    object_id: int
    tile: int
    art_id: int
    filename: str
    subtype: int
    subtype_name: str
    prototype_list_index: int | None
    inventory: tuple[ItemInventoryEntry, ...]
    rotation: int
    frame_index: int
    flags: int
    direction_x_offset: int
    direction_y_offset: int
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class ItemInventoryEntry:
    prototype_list_index: int
    quantity: int


@dataclass(frozen=True, slots=True)
class ItemLabelContent:
    prototype_list_index: int
    source_name: str
    chinese_name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class ItemNameLabel:
    object_id: int
    tile: int
    prototype_list_index: int
    subtype_name: str
    source_name: str
    chinese_name: str
    contents: tuple[ItemLabelContent, ...]
    target_x: int
    target_y: int


@dataclass(frozen=True, slots=True)
class ItemLabelResources:
    names_message: MsgDocument
    translations_path: Path
    translations_size: int
    translations_sha256: str
    locale: str


@dataclass(frozen=True, slots=True)
class ItemRenderPlan:
    scenery: SceneryRenderPlan
    item_list: ListDocument
    item_root: Path
    placements: tuple[ItemPlacement, ...]
    used_item_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    flat_placements: int
    subtype_counts: tuple[tuple[str, int], ...]
    contained_item_objects: int
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_item_png: Path
    output_composite_png: Path
    output_highlight_png: Path
    output_hash: Path

    @property
    def canvas_width(self) -> int:
        return self.bounds_right - self.bounds_left

    @property
    def canvas_height(self) -> int:
        return self.bounds_bottom - self.bounds_top


@dataclass(frozen=True, slots=True)
class CritterPlacement:
    source_index: int
    object_id: int
    tile: int
    fid: int
    art_id: int
    resolved_art_id: int
    base_name: str
    filename: str
    weapon_animation: int
    animation: int
    prototype_list_index: int
    script_filename: str | None
    rotation: int
    frame_index: int
    flags: int
    direction_x_offset: int
    direction_y_offset: int
    screen_x: int
    screen_y: int
    frame: FrmFrame


@dataclass(frozen=True, slots=True)
class MissingCritterArt:
    source_index: int
    object_id: int
    tile: int
    fid: int
    art_id: int
    resolved_art_id: int
    base_name: str
    filename: str
    prototype_list_index: int
    script_filename: str | None
    anchor_x: int
    anchor_y: int


@dataclass(frozen=True, slots=True)
class CritterNameLabel:
    object_id: int
    tile: int
    prototype_list_index: int
    source_name: str
    chinese_name: str
    english_name: str | None
    name_source: str
    script_filename: str | None
    target_x: int
    target_y: int
    missing_art: bool


@dataclass(frozen=True, slots=True)
class CritterLabelResources:
    names_message: MsgDocument
    translations_path: Path
    translations_size: int
    translations_sha256: str
    locale: str
    font_path: Path
    font_size_bytes: int
    font_sha256: str
    font_pixels: int


@dataclass(frozen=True, slots=True)
class CritterRenderPlan:
    item: ItemRenderPlan
    critter_list: ListDocument
    critter_root: Path
    placements: tuple[CritterPlacement, ...]
    missing_art: tuple[MissingCritterArt, ...]
    name_labels: tuple[CritterNameLabel, ...]
    label_resources: CritterLabelResources | None
    item_name_labels: tuple[ItemNameLabel, ...]
    item_label_resources: ItemLabelResources | None
    used_critter_ids: tuple[int, ...]
    hidden_placements: int
    transparent_placements: int
    flat_placements: int
    bounds_left: int
    bounds_top: int
    bounds_right: int
    bounds_bottom: int
    output_json: Path
    output_critter_png: Path
    output_composite_png: Path
    output_highlight_png: Path
    output_label_png: Path | None
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
    wall_stem = (
        f"{stem[: -len('-floor-walls')]}-walls"
        if stem.endswith("-floor-walls")
        else f"{stem}-walls"
    )
    wall_path = ensure_within_workspace(workspace, json_path.with_name(f"{wall_stem}.png"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, wall_path, composite_path, hash_path}) != 4:
        raise MapRenderError("wall render output paths collide")
    return json_path, wall_path, composite_path, hash_path


def door_render_output_paths(
    workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    composite_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    stem = json_path.stem
    suffix = "-floor-walls-doors"
    door_stem = f"{stem[: -len(suffix)]}-doors" if stem.endswith(suffix) else f"{stem}-doors"
    door_path = ensure_within_workspace(workspace, json_path.with_name(f"{door_stem}.png"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, door_path, composite_path, hash_path}) != 4:
        raise MapRenderError("door render output paths collide")
    return json_path, door_path, composite_path, hash_path


def scenery_render_output_paths(
    workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    composite_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    stem = json_path.stem
    suffix = "-floor-walls-doors-scenery"
    scenery_stem = f"{stem[: -len(suffix)]}-scenery" if stem.endswith(suffix) else f"{stem}-scenery"
    scenery_path = ensure_within_workspace(workspace, json_path.with_name(f"{scenery_stem}.png"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, scenery_path, composite_path, hash_path}) != 4:
        raise MapRenderError("scenery render output paths collide")
    return json_path, scenery_path, composite_path, hash_path


def item_render_output_paths(
    workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    composite_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    stem = json_path.stem
    suffix = "-floor-walls-doors-scenery-items"
    item_stem = f"{stem[: -len(suffix)]}-items" if stem.endswith(suffix) else f"{stem}-items"
    item_path = ensure_within_workspace(workspace, json_path.with_name(f"{item_stem}.png"))
    highlight_path = ensure_within_workspace(
        workspace, json_path.with_name(f"{stem}-highlighted.png")
    )
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, item_path, composite_path, highlight_path, hash_path}) != 5:
        raise MapRenderError("item render output paths collide")
    return json_path, item_path, composite_path, highlight_path, hash_path


def critter_render_output_paths(
    workspace: Path | str, output: Path | str
) -> tuple[Path, Path, Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise MapRenderError("map render output must use a .json metadata filename")
    composite_path = ensure_within_workspace(workspace, json_path.with_suffix(".png"))
    stem = json_path.stem
    suffix = "-floor-walls-doors-scenery-items-critters"
    critter_stem = (
        f"{stem[: -len(suffix)]}-critters" if stem.endswith(suffix) else f"{stem}-critters"
    )
    critter_path = ensure_within_workspace(workspace, json_path.with_name(f"{critter_stem}.png"))
    highlight_path = ensure_within_workspace(
        workspace, json_path.with_name(f"{stem}-highlighted.png")
    )
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    if len({json_path, critter_path, composite_path, highlight_path, hash_path}) != 5:
        raise MapRenderError("critter render output paths collide")
    return json_path, critter_path, composite_path, highlight_path, hash_path


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


def _object_placement_sort_key(
    item: WallPlacement | DoorPlacement | SceneryPlacement | ItemPlacement | CritterPlacement,
) -> tuple[int, int, int]:
    return 0 if item.flags & OBJECT_FLAT else 1, item.tile, item.source_index


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
    placements.sort(key=_object_placement_sort_key)

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


def _scenery_document(
    art_id: int, scenery_list: ListDocument, files: dict[str, Path]
) -> tuple[str, FrmDocument]:
    if art_id >= len(scenery_list.entries):
        raise MapRenderError(
            f"scenery art id {art_id} is outside SCENERY.LST range "
            f"0..{len(scenery_list.entries) - 1}"
        )
    filename = scenery_list.entries[art_id].filename
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.casefold() != ".frm"
    ):
        raise MapRenderError(f"unsafe or unsupported SCENERY.LST entry {art_id}: {filename!r}")
    source = files.get(filename.casefold())
    if source is None:
        raise FileNotFoundError(f"scenery FRM for art id {art_id} does not exist: {filename}")
    return filename, load_frm(source)


def _scenery_frame(
    document: FrmDocument, rotation: int, frame_index: int
) -> tuple[FrmDirection, FrmFrame]:
    direction = next((item for item in document.directions if item.index == rotation), None)
    if direction is None:
        raise MapRenderError(f"scenery FRM has no direction {rotation}: {document.source_path}")
    sequence = document.sequences[direction.sequence_index]
    if frame_index < 0 or frame_index >= len(sequence.frames):
        raise MapRenderError(
            f"scenery frame {frame_index} is outside range 0..{len(sequence.frames) - 1}: "
            f"{document.source_path}"
        )
    return direction, sequence.frames[frame_index]


def build_door_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    walls_list: Path | str,
    walls_dir: Path | str,
    scenery_list: Path | str,
    scenery_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
) -> DoorRenderPlan:
    """Validate and plan door-only and game-ordered floor-wall-door renders."""
    output_json, output_door_png, output_composite_png, output_hash = door_render_output_paths(
        workspace, output
    )
    wall_output = output_json.with_name(f"elevation-{elevation}-floor-walls.json")
    wall = build_wall_render_plan(
        map_json,
        tiles_list,
        tiles_dir,
        walls_list,
        walls_dir,
        palette_path,
        elevation,
        workspace,
        wall_output,
    )
    source, source_data, payload = _stable_json(map_json)
    if (
        source != wall.floor.map_json_path
        or hashlib.sha256(source_data).hexdigest().upper() != wall.floor.map_json_sha256
    ):
        raise MapRenderError(f"map JSON changed while building render plan: {source}")
    objects = payload.get("objects")
    entries = objects.get("entries") if isinstance(objects, dict) else None
    if not isinstance(entries, list):
        raise MapRenderError("map JSON objects.entries must be an array")

    scenery = load_lst(scenery_list)
    scenery_root = Path(scenery_dir).resolve()
    files = _casefold_file_index(scenery_root)
    selected: list[tuple[int, dict[str, Any]]] = []
    for source_index, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("elevation_group") != elevation:
            continue
        prototype = item.get("prototype")
        if (
            not isinstance(prototype, dict)
            or prototype.get("type") != "scenery"
            or prototype.get("subtype") != 0
            or prototype.get("subtype_name") != "door"
        ):
            continue
        selected.append((source_index, item))
    if not selected:
        raise MapRenderError("map elevation contains no door objects")

    documents: dict[int, tuple[str, FrmDocument]] = {}
    for source_index, item in selected:
        fid = item.get("fid")
        if not isinstance(fid, int) or fid < 0:
            raise MapRenderError(f"door object {source_index} has invalid FID")
        if (fid >> 24) & 0x0F != SCENERY_FID_TYPE:
            raise MapRenderError(f"door object {source_index} FID is not scenery art: 0x{fid:08X}")
        art_id = fid & 0x0FFF
        if art_id not in documents:
            documents[art_id] = _scenery_document(art_id, scenery, files)

    placements: list[DoorPlacement] = []
    hidden = 0
    transparent = 0
    flat = 0
    closed = 0
    open_or_transition = 0
    target_open = 0
    locked = 0
    jammed = 0
    for source_index, item in selected:
        tile = item.get("tile")
        object_id = item.get("object_id")
        rotation = item.get("rotation")
        frame_index = item.get("frame")
        object_x = item.get("x")
        object_y = item.get("y")
        flags = item.get("flags")
        update_data = item.get("update_data")
        open_flags = update_data.get("open_flags") if isinstance(update_data, dict) else None
        if not isinstance(tile, int) or tile < 0 or tile >= HEX_GRID_WIDTH * HEX_GRID_HEIGHT:
            raise MapRenderError(f"door object {source_index} has invalid tile")
        if not isinstance(object_id, int):
            raise MapRenderError(f"door object {source_index} has invalid object id")
        if not isinstance(rotation, int) or rotation < 0 or rotation >= 6:
            raise MapRenderError(f"door object {source_index} has invalid rotation")
        if not isinstance(frame_index, int):
            raise MapRenderError(f"door object {source_index} has invalid frame")
        if not isinstance(object_x, int) or not isinstance(object_y, int):
            raise MapRenderError(f"door object {source_index} has invalid pixel offset")
        if not isinstance(flags, int):
            raise MapRenderError(f"door object {source_index} has invalid flags")
        if not isinstance(open_flags, int):
            raise MapRenderError(f"door object {source_index} has invalid open flags")

        flat += bool(flags & OBJECT_FLAT)
        closed += frame_index == 0
        open_or_transition += frame_index != 0
        target_open += bool(open_flags & DOOR_OPEN)
        locked += bool(open_flags & DOOR_LOCKED)
        jammed += bool(open_flags & DOOR_JAMMED)
        art_id = item["fid"] & 0x0FFF
        filename, document = documents[art_id]
        direction, frame = _scenery_frame(document, rotation, frame_index)
        if flags & OBJECT_HIDDEN:
            hidden += 1
            continue
        if not any(frame.pixels):
            transparent += 1
            continue
        hex_x, hex_y = hex_tile_screen_position(tile)
        anchor_x = hex_x + 16 + direction.x_offset + object_x
        anchor_y = hex_y + 8 + direction.y_offset + object_y
        placements.append(
            DoorPlacement(
                source_index=source_index,
                object_id=object_id,
                tile=tile,
                art_id=art_id,
                filename=filename,
                rotation=rotation,
                frame_index=frame_index,
                flags=flags,
                open_flags=open_flags,
                direction_x_offset=direction.x_offset,
                direction_y_offset=direction.y_offset,
                screen_x=anchor_x - frame.width // 2,
                screen_y=anchor_y - (frame.height - 1),
                frame=frame,
            )
        )
    if not placements:
        raise MapRenderError("map elevation contains no visible non-transparent door pixels")
    placements.sort(key=_object_placement_sort_key)

    left = min(wall.bounds_left, *(item.screen_x for item in placements))
    top = min(wall.bounds_top, *(item.screen_y for item in placements))
    right = max(wall.bounds_right, *(item.screen_x + item.frame.width for item in placements))
    bottom = max(wall.bounds_bottom, *(item.screen_y + item.frame.height for item in placements))
    sources = {source, scenery.source_path, *files.values()}
    collision = sources.intersection(
        (output_json, output_door_png, output_composite_png, output_hash)
    )
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return DoorRenderPlan(
        wall=wall,
        scenery_list=scenery,
        scenery_root=scenery_root,
        placements=tuple(placements),
        used_door_ids=tuple(sorted({item.art_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        flat_placements=flat,
        closed_placements=closed,
        open_or_transition_placements=open_or_transition,
        target_open_placements=target_open,
        locked_placements=locked,
        jammed_placements=jammed,
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_door_png=output_door_png,
        output_composite_png=output_composite_png,
        output_hash=output_hash,
    )


def door_render_summary(plan: DoorRenderPlan) -> dict[str, Any]:
    return {
        "map": plan.wall.floor.map_name,
        "elevation": plan.wall.floor.elevation,
        "visible_floor_placements": len(plan.wall.floor.placements),
        "visible_wall_placements": len(plan.wall.placements),
        "validated_door_objects": (
            len(plan.placements) + plan.hidden_placements + plan.transparent_placements
        ),
        "visible_door_placements": len(plan.placements),
        "hidden_door_placements": plan.hidden_placements,
        "transparent_door_placements": plan.transparent_placements,
        "flat_door_objects": plan.flat_placements,
        "closed_door_objects": plan.closed_placements,
        "open_or_transition_door_objects": plan.open_or_transition_placements,
        "target_open_door_objects": plan.target_open_placements,
        "locked_door_objects": plan.locked_placements,
        "jammed_door_objects": plan.jammed_placements,
        "unique_visible_door_ids": len(plan.used_door_ids),
        "canvas_width": plan.canvas_width,
        "canvas_height": plan.canvas_height,
        "origin_x": plan.bounds_left,
        "origin_y": plan.bounds_top,
    }


def build_scenery_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    walls_list: Path | str,
    walls_dir: Path | str,
    scenery_list: Path | str,
    scenery_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
) -> SceneryRenderPlan:
    """Plan non-door scenery and the complete pre-roof static map layer."""
    output_json, output_scenery_png, output_composite_png, output_hash = (
        scenery_render_output_paths(workspace, output)
    )
    door_output = output_json.with_name(f"elevation-{elevation}-floor-walls-doors.json")
    door = build_door_render_plan(
        map_json,
        tiles_list,
        tiles_dir,
        walls_list,
        walls_dir,
        scenery_list,
        scenery_dir,
        palette_path,
        elevation,
        workspace,
        door_output,
    )
    source, source_data, payload = _stable_json(map_json)
    if (
        source != door.wall.floor.map_json_path
        or hashlib.sha256(source_data).hexdigest().upper() != door.wall.floor.map_json_sha256
    ):
        raise MapRenderError(f"map JSON changed while building render plan: {source}")
    objects = payload.get("objects")
    entries = objects.get("entries") if isinstance(objects, dict) else None
    if not isinstance(entries, list):
        raise MapRenderError("map JSON objects.entries must be an array")

    selected: list[tuple[int, dict[str, Any], int, str]] = []
    for source_index, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("elevation_group") != elevation:
            continue
        prototype = item.get("prototype")
        if not isinstance(prototype, dict) or prototype.get("type") != "scenery":
            continue
        subtype = prototype.get("subtype")
        subtype_name = prototype.get("subtype_name")
        if not isinstance(subtype, int) or not isinstance(subtype_name, str):
            raise MapRenderError(f"scenery object {source_index} has invalid prototype subtype")
        if subtype == 0:
            continue
        selected.append((source_index, item, subtype, subtype_name))
    if not selected:
        raise MapRenderError("map elevation contains no non-door scenery objects")

    files = _casefold_file_index(door.scenery_root)
    documents: dict[int, tuple[str, FrmDocument]] = {}
    for source_index, item, _, _ in selected:
        fid = item.get("fid")
        if not isinstance(fid, int) or fid < 0:
            raise MapRenderError(f"scenery object {source_index} has invalid FID")
        if (fid >> 24) & 0x0F != SCENERY_FID_TYPE:
            raise MapRenderError(
                f"scenery object {source_index} FID is not scenery art: 0x{fid:08X}"
            )
        art_id = fid & 0x0FFF
        if art_id not in documents:
            documents[art_id] = _scenery_document(art_id, door.scenery_list, files)

    placements: list[SceneryPlacement] = []
    hidden = 0
    transparent = 0
    flat = 0
    subtype_counts: dict[str, int] = {}
    for source_index, item, subtype, subtype_name in selected:
        tile = item.get("tile")
        object_id = item.get("object_id")
        rotation = item.get("rotation")
        frame_index = item.get("frame")
        object_x = item.get("x")
        object_y = item.get("y")
        flags = item.get("flags")
        if not isinstance(tile, int) or tile < 0 or tile >= HEX_GRID_WIDTH * HEX_GRID_HEIGHT:
            raise MapRenderError(f"scenery object {source_index} has invalid tile")
        if not isinstance(object_id, int):
            raise MapRenderError(f"scenery object {source_index} has invalid object id")
        if not isinstance(rotation, int) or rotation < 0 or rotation >= 6:
            raise MapRenderError(f"scenery object {source_index} has invalid rotation")
        if not isinstance(frame_index, int):
            raise MapRenderError(f"scenery object {source_index} has invalid frame")
        if not isinstance(object_x, int) or not isinstance(object_y, int):
            raise MapRenderError(f"scenery object {source_index} has invalid pixel offset")
        if not isinstance(flags, int):
            raise MapRenderError(f"scenery object {source_index} has invalid flags")
        subtype_counts[subtype_name] = subtype_counts.get(subtype_name, 0) + 1
        flat += bool(flags & OBJECT_FLAT)
        art_id = item["fid"] & 0x0FFF
        filename, document = documents[art_id]
        direction, frame = _scenery_frame(document, rotation, frame_index)
        if flags & OBJECT_HIDDEN:
            hidden += 1
            continue
        if not any(frame.pixels):
            transparent += 1
            continue
        hex_x, hex_y = hex_tile_screen_position(tile)
        anchor_x = hex_x + 16 + direction.x_offset + object_x
        anchor_y = hex_y + 8 + direction.y_offset + object_y
        placements.append(
            SceneryPlacement(
                source_index=source_index,
                object_id=object_id,
                tile=tile,
                art_id=art_id,
                filename=filename,
                subtype=subtype,
                subtype_name=subtype_name,
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
        raise MapRenderError("map elevation contains no visible non-transparent scenery pixels")
    placements.sort(key=_object_placement_sort_key)

    left = min(door.bounds_left, *(item.screen_x for item in placements))
    top = min(door.bounds_top, *(item.screen_y for item in placements))
    right = max(door.bounds_right, *(item.screen_x + item.frame.width for item in placements))
    bottom = max(door.bounds_bottom, *(item.screen_y + item.frame.height for item in placements))
    sources = {source, *files.values()}
    collision = sources.intersection(
        (output_json, output_scenery_png, output_composite_png, output_hash)
    )
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return SceneryRenderPlan(
        door=door,
        placements=tuple(placements),
        used_scenery_ids=tuple(sorted({item.art_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        flat_placements=flat,
        subtype_counts=tuple(sorted(subtype_counts.items())),
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_scenery_png=output_scenery_png,
        output_composite_png=output_composite_png,
        output_hash=output_hash,
    )


def scenery_render_summary(plan: SceneryRenderPlan) -> dict[str, Any]:
    return {
        "map": plan.door.wall.floor.map_name,
        "elevation": plan.door.wall.floor.elevation,
        "visible_floor_placements": len(plan.door.wall.floor.placements),
        "visible_wall_placements": len(plan.door.wall.placements),
        "visible_door_placements": len(plan.door.placements),
        "validated_scenery_objects": (
            len(plan.placements) + plan.hidden_placements + plan.transparent_placements
        ),
        "visible_scenery_placements": len(plan.placements),
        "hidden_scenery_placements": plan.hidden_placements,
        "transparent_scenery_placements": plan.transparent_placements,
        "flat_scenery_objects": plan.flat_placements,
        "scenery_subtypes": dict(plan.subtype_counts),
        "unique_visible_scenery_ids": len(plan.used_scenery_ids),
        "canvas_width": plan.canvas_width,
        "canvas_height": plan.canvas_height,
        "origin_x": plan.bounds_left,
        "origin_y": plan.bounds_top,
    }


def _item_document(
    art_id: int, item_list: ListDocument, files: dict[str, Path]
) -> tuple[str, FrmDocument]:
    if art_id >= len(item_list.entries):
        raise MapRenderError(
            f"item art id {art_id} is outside ITEMS.LST range 0..{len(item_list.entries) - 1}"
        )
    filename = item_list.entries[art_id].filename
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.casefold() != ".frm"
    ):
        raise MapRenderError(f"unsafe or unsupported ITEMS.LST entry {art_id}: {filename!r}")
    source = files.get(filename.casefold())
    if source is None:
        raise FileNotFoundError(f"item FRM for art id {art_id} does not exist: {filename}")
    return filename, load_frm(source)


def _item_frame(
    document: FrmDocument, rotation: int, frame_index: int
) -> tuple[FrmDirection, FrmFrame]:
    direction = next((item for item in document.directions if item.index == rotation), None)
    if direction is None:
        raise MapRenderError(f"item FRM has no direction {rotation}: {document.source_path}")
    sequence = document.sequences[direction.sequence_index]
    if frame_index < 0 or frame_index >= len(sequence.frames):
        raise MapRenderError(
            f"item frame {frame_index} is outside range 0..{len(sequence.frames) - 1}: "
            f"{document.source_path}"
        )
    return direction, sequence.frames[frame_index]


def _item_inventory_entries(
    item: dict[str, Any], source_index: int
) -> tuple[ItemInventoryEntry, ...]:
    raw_inventory = item.get("inventory", [])
    if not isinstance(raw_inventory, list):
        raise MapRenderError(f"item object {source_index} has invalid inventory")
    entries: list[ItemInventoryEntry] = []
    for inventory_index, raw_entry in enumerate(raw_inventory):
        if not isinstance(raw_entry, dict):
            raise MapRenderError(
                f"item object {source_index} inventory {inventory_index} is invalid"
            )
        quantity = raw_entry.get("quantity")
        nested_item = raw_entry.get("item")
        prototype = nested_item.get("prototype") if isinstance(nested_item, dict) else None
        prototype_list_index = (
            prototype.get("list_index") if isinstance(prototype, dict) else None
        )
        if not isinstance(quantity, int) or quantity < 0:
            raise MapRenderError(
                f"item object {source_index} inventory {inventory_index} has invalid quantity"
            )
        if not isinstance(prototype_list_index, int) or prototype_list_index < 0:
            raise MapRenderError(
                f"item object {source_index} inventory {inventory_index} has invalid prototype"
            )
        entries.append(
            ItemInventoryEntry(
                prototype_list_index=prototype_list_index,
                quantity=quantity,
            )
        )
    return tuple(entries)


def build_item_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    walls_list: Path | str,
    walls_dir: Path | str,
    scenery_list: Path | str,
    scenery_dir: Path | str,
    items_list: Path | str,
    items_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
) -> ItemRenderPlan:
    """Plan top-level MAP items and the complete pre-roof static object layer."""
    (
        output_json,
        output_item_png,
        output_composite_png,
        output_highlight_png,
        output_hash,
    ) = item_render_output_paths(workspace, output)
    scenery_output = output_json.with_name(f"elevation-{elevation}-floor-walls-doors-scenery.json")
    scenery = build_scenery_render_plan(
        map_json,
        tiles_list,
        tiles_dir,
        walls_list,
        walls_dir,
        scenery_list,
        scenery_dir,
        palette_path,
        elevation,
        workspace,
        scenery_output,
    )
    source, source_data, payload = _stable_json(map_json)
    if (
        source != scenery.door.wall.floor.map_json_path
        or hashlib.sha256(source_data).hexdigest().upper()
        != scenery.door.wall.floor.map_json_sha256
    ):
        raise MapRenderError(f"map JSON changed while building render plan: {source}")
    objects = payload.get("objects")
    entries = objects.get("entries") if isinstance(objects, dict) else None
    if not isinstance(entries, list):
        raise MapRenderError("map JSON objects.entries must be an array")
    summary = payload.get("summary")
    contained_item_objects = summary.get("inventory_objects") if isinstance(summary, dict) else None
    if not isinstance(contained_item_objects, int) or contained_item_objects < 0:
        raise MapRenderError("map JSON summary has invalid inventory_objects count")

    item_list = load_lst(items_list)
    item_root = Path(items_dir).resolve()
    files = _casefold_file_index(item_root)
    selected: list[tuple[int, dict[str, Any], int, str]] = []
    for source_index, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("elevation_group") != elevation:
            continue
        prototype = item.get("prototype")
        if not isinstance(prototype, dict) or prototype.get("type") != "item":
            continue
        subtype = prototype.get("subtype")
        subtype_name = prototype.get("subtype_name")
        if not isinstance(subtype, int) or not isinstance(subtype_name, str):
            raise MapRenderError(f"item object {source_index} has invalid prototype subtype")
        selected.append((source_index, item, subtype, subtype_name))
    if not selected:
        raise MapRenderError("map elevation contains no top-level item objects")

    documents: dict[int, tuple[str, FrmDocument]] = {}
    for source_index, item, _, _ in selected:
        fid = item.get("fid")
        if not isinstance(fid, int) or fid < 0:
            raise MapRenderError(f"item object {source_index} has invalid FID")
        if (fid >> 24) & 0x0F != ITEM_FID_TYPE:
            raise MapRenderError(f"item object {source_index} FID is not item art: 0x{fid:08X}")
        art_id = fid & 0x0FFF
        if art_id not in documents:
            documents[art_id] = _item_document(art_id, item_list, files)

    placements: list[ItemPlacement] = []
    hidden = 0
    transparent = 0
    flat = 0
    subtype_counts: dict[str, int] = {}
    for source_index, item, subtype, subtype_name in selected:
        prototype = item["prototype"]
        prototype_list_index = prototype.get("list_index")
        if not isinstance(prototype_list_index, int) or prototype_list_index < 0:
            prototype_list_index = None
        tile = item.get("tile")
        object_id = item.get("object_id")
        rotation = item.get("rotation")
        frame_index = item.get("frame")
        object_x = item.get("x")
        object_y = item.get("y")
        flags = item.get("flags")
        inventory = _item_inventory_entries(item, source_index)
        if not isinstance(tile, int) or tile < 0 or tile >= HEX_GRID_WIDTH * HEX_GRID_HEIGHT:
            raise MapRenderError(f"item object {source_index} has invalid tile")
        if not isinstance(object_id, int):
            raise MapRenderError(f"item object {source_index} has invalid object id")
        if not isinstance(rotation, int) or rotation < 0 or rotation >= 6:
            raise MapRenderError(f"item object {source_index} has invalid rotation")
        if not isinstance(frame_index, int):
            raise MapRenderError(f"item object {source_index} has invalid frame")
        if not isinstance(object_x, int) or not isinstance(object_y, int):
            raise MapRenderError(f"item object {source_index} has invalid pixel offset")
        if not isinstance(flags, int):
            raise MapRenderError(f"item object {source_index} has invalid flags")
        subtype_counts[subtype_name] = subtype_counts.get(subtype_name, 0) + 1
        flat += bool(flags & OBJECT_FLAT)
        art_id = item["fid"] & 0x0FFF
        filename, document = documents[art_id]
        direction, frame = _item_frame(document, rotation, frame_index)
        if flags & OBJECT_HIDDEN:
            hidden += 1
            continue
        if not any(frame.pixels):
            transparent += 1
            continue
        hex_x, hex_y = hex_tile_screen_position(tile)
        anchor_x = hex_x + 16 + direction.x_offset + object_x
        anchor_y = hex_y + 8 + direction.y_offset + object_y
        placements.append(
            ItemPlacement(
                source_index=source_index,
                object_id=object_id,
                tile=tile,
                art_id=art_id,
                filename=filename,
                subtype=subtype,
                subtype_name=subtype_name,
                prototype_list_index=prototype_list_index,
                inventory=inventory,
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
        raise MapRenderError("map elevation contains no visible non-transparent item pixels")
    placements.sort(key=_object_placement_sort_key)

    left = min(scenery.bounds_left, *(item.screen_x for item in placements))
    top = min(scenery.bounds_top, *(item.screen_y for item in placements))
    right = max(scenery.bounds_right, *(item.screen_x + item.frame.width for item in placements))
    bottom = max(scenery.bounds_bottom, *(item.screen_y + item.frame.height for item in placements))
    sources = {source, item_list.source_path, *files.values()}
    collision = sources.intersection(
        (output_json, output_item_png, output_composite_png, output_highlight_png, output_hash)
    )
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return ItemRenderPlan(
        scenery=scenery,
        item_list=item_list,
        item_root=item_root,
        placements=tuple(placements),
        used_item_ids=tuple(sorted({item.art_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        flat_placements=flat,
        subtype_counts=tuple(sorted(subtype_counts.items())),
        contained_item_objects=contained_item_objects,
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_item_png=output_item_png,
        output_composite_png=output_composite_png,
        output_highlight_png=output_highlight_png,
        output_hash=output_hash,
    )


def item_render_summary(plan: ItemRenderPlan) -> dict[str, Any]:
    return {
        "map": plan.scenery.door.wall.floor.map_name,
        "elevation": plan.scenery.door.wall.floor.elevation,
        "visible_floor_placements": len(plan.scenery.door.wall.floor.placements),
        "visible_wall_placements": len(plan.scenery.door.wall.placements),
        "visible_door_placements": len(plan.scenery.door.placements),
        "visible_scenery_placements": len(plan.scenery.placements),
        "validated_item_objects": (
            len(plan.placements) + plan.hidden_placements + plan.transparent_placements
        ),
        "visible_item_placements": len(plan.placements),
        "hidden_item_placements": plan.hidden_placements,
        "transparent_item_placements": plan.transparent_placements,
        "flat_item_objects": plan.flat_placements,
        "item_subtypes": dict(plan.subtype_counts),
        "contained_item_objects_not_rendered": plan.contained_item_objects,
        "item_placements_extending_previous_bounds": sum(
            item.screen_x < plan.scenery.bounds_left
            or item.screen_y < plan.scenery.bounds_top
            or item.screen_x + item.frame.width > plan.scenery.bounds_right
            or item.screen_y + item.frame.height > plan.scenery.bounds_bottom
            for item in plan.placements
        ),
        "unique_visible_item_ids": len(plan.used_item_ids),
        "canvas_width": plan.canvas_width,
        "canvas_height": plan.canvas_height,
        "origin_x": plan.bounds_left,
        "origin_y": plan.bounds_top,
    }


_CRITTER_ALIAS_ANIMATIONS = frozenset({27, 29, 30, 33, 55, 57, 58, 61, 64})


def _critter_list_entry(art_id: int, critter_list: ListDocument) -> tuple[str, int | None]:
    if art_id >= len(critter_list.entries):
        raise MapRenderError(
            f"critter art id {art_id} is outside CRITTERS.LST range "
            f"0..{len(critter_list.entries) - 1}"
        )
    raw = critter_list.entries[art_id].filename
    base_name, separator, alias_text = raw.partition(",")
    if (
        not base_name
        or Path(base_name).name != base_name
        or not base_name.isascii()
        or not base_name.isalnum()
    ):
        raise MapRenderError(f"unsafe or unsupported CRITTERS.LST entry {art_id}: {raw!r}")
    alias: int | None = None
    if separator:
        try:
            alias = int(alias_text)
        except ValueError as exc:
            raise MapRenderError(
                f"invalid CRITTERS.LST alias for art id {art_id}: {raw!r}"
            ) from exc
        if alias < 0 or alias >= len(critter_list.entries):
            raise MapRenderError(
                f"CRITTERS.LST alias {alias} for art id {art_id} is outside list range"
            )
    return base_name, alias


def _critter_art_codes(animation: int, weapon_animation: int) -> tuple[str, str]:
    """Return Fallout's two critter filename code letters for one FID."""
    if animation < 0 or animation > 64:
        raise MapRenderError(f"unsupported critter animation code: {animation}")
    if weapon_animation < 0 or weapon_animation >= 11:
        raise MapRenderError(f"unsupported critter weapon animation code: {weapon_animation}")
    if 38 <= animation <= 47:
        if weapon_animation == 0:
            raise MapRenderError(
                f"critter weapon animation {animation} requires a weapon animation code"
            )
        return chr(ord("d") + weapon_animation - 1), chr(ord("c") + animation - 38)
    if animation == 36:
        return "c", "h"
    if animation == 37:
        return "c", "j"
    if animation == 64:
        return "n", "a"
    if animation >= 48:
        return "r", chr(ord("a") + animation - 48)
    if animation >= 20:
        return "b", chr(ord("a") + animation - 20)
    if animation == 18:
        if weapon_animation == 1:
            return "d", "m"
        if weapon_animation == 4:
            return "g", "m"
        return "a", "s"
    if animation == 13:
        if weapon_animation == 0:
            return "a", "n"
        return chr(ord("d") + weapon_animation - 1), "e"
    code1 = chr(ord("d") + weapon_animation - 1) if animation <= 1 and weapon_animation > 0 else "a"
    return code1, chr(ord("a") + animation)


def _critter_art_file(
    fid: int,
    critter_list: ListDocument,
    files: dict[str, Path],
) -> tuple[int, int, str, str, Path | None]:
    art_id = fid & 0x0FFF
    animation = (fid >> 16) & 0xFF
    _, alias = _critter_list_entry(art_id, critter_list)
    resolved_art_id = (
        alias if animation in _CRITTER_ALIAS_ANIMATIONS and alias is not None else art_id
    )
    base_name, _ = _critter_list_entry(resolved_art_id, critter_list)
    weapon_animation = (fid >> 12) & 0x0F
    code1, code2 = _critter_art_codes(animation, weapon_animation)
    split_code = (fid >> 28) & 0x07
    if split_code > 6:
        raise MapRenderError(f"unsupported critter split-direction code: {split_code}")
    extension = ".frm" if split_code == 0 else f".fr{split_code - 1}"
    filename = f"{base_name}{code1}{code2}{extension}"
    return art_id, resolved_art_id, base_name, filename, files.get(filename.casefold())


def _critter_frame(
    document: FrmDocument, rotation: int, frame_index: int
) -> tuple[FrmDirection, FrmFrame]:
    direction_index = document.split_direction if document.split_direction is not None else rotation
    direction = next((item for item in document.directions if item.index == direction_index), None)
    if direction is None:
        raise MapRenderError(
            f"critter FRM has no direction {direction_index}: {document.source_path}"
        )
    sequence = document.sequences[direction.sequence_index]
    if frame_index < 0 or frame_index >= len(sequence.frames):
        raise MapRenderError(
            f"critter frame {frame_index} is outside range 0..{len(sequence.frames) - 1}: "
            f"{document.source_path}"
        )
    return direction, sequence.frames[frame_index]


def _stable_file(path: Path | str, label: str) -> tuple[Path, bytes]:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MapRenderError(f"{label} changed while reading: {source}")
    return source, data


def _critter_name_labels(
    placements: tuple[CritterPlacement, ...],
    missing_art: tuple[MissingCritterArt, ...],
    names_message_path: Path | str,
    translations_path: Path | str,
    font_path: Path | str,
    font_pixels: int,
) -> tuple[tuple[CritterNameLabel, ...], CritterLabelResources]:
    if font_pixels < 8 or font_pixels > 96:
        raise MapRenderError("critter label font size must be between 8 and 96 pixels")
    names_message = load_msg(names_message_path, encoding="ascii")
    translation_source, translation_data = _stable_file(
        translations_path, "critter name translations"
    )
    try:
        payload = json.loads(translation_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MapRenderError(f"invalid critter name translations JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MapRenderError("unsupported critter name translations schema")
    locale = payload.get("locale")
    prototype_names = payload.get("prototype_names")
    script_names = payload.get("script_names")
    bilingual_names = payload.get("bilingual_names", {})
    if (
        not isinstance(locale, str)
        or not locale
        or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in locale)
    ):
        raise MapRenderError("critter name translations has an invalid locale")
    if not isinstance(prototype_names, dict) or not isinstance(script_names, dict):
        raise MapRenderError(
            "critter name translations requires prototype_names and script_names objects"
        )
    if not isinstance(bilingual_names, dict) or any(
        not isinstance(source_name, str)
        or not source_name
        or not isinstance(english_name, str)
        or not english_name
        for source_name, english_name in bilingual_names.items()
    ):
        raise MapRenderError("critter bilingual names must be non-empty strings")
    if any(
        not isinstance(source_name, str)
        or not source_name
        or not isinstance(chinese_name, str)
        or not chinese_name
        for source_name, chinese_name in prototype_names.items()
    ):
        raise MapRenderError("critter prototype name translations must be non-empty strings")
    if any(
        not isinstance(script_name, str)
        or not script_name
        or not isinstance(chinese_name, str)
        or not chinese_name
        for script_name, chinese_name in script_names.items()
    ):
        raise MapRenderError("critter script name translations must be non-empty strings")
    script_lookup = {name.casefold(): value for name, value in script_names.items()}
    bilingual_lookup = {name.casefold(): value for name, value in bilingual_names.items()}
    message_names = {
        entry.number: entry.text
        for entry in names_message.entries
        if entry.effective and entry.text
    }
    labels: list[CritterNameLabel] = []
    targets: tuple[
        tuple[
            int,
            int,
            int,
            str | None,
            int,
            int,
            bool,
        ],
        ...,
    ] = tuple(
        (
            item.object_id,
            item.tile,
            item.prototype_list_index,
            item.script_filename,
            item.screen_x + item.frame.width // 2,
            item.screen_y,
            False,
        )
        for item in placements
    ) + tuple(
        (
            item.object_id,
            item.tile,
            item.prototype_list_index,
            item.script_filename,
            item.anchor_x,
            item.anchor_y - font_pixels,
            True,
        )
        for item in missing_art
    )
    for object_id, tile, prototype_index, script_filename, target_x, target_y, missing in targets:
        prototype_name = message_names.get(prototype_index * 100)
        if not prototype_name:
            raise MapRenderError(
                f"PRO_CRIT.MSG has no display name for critter prototype {prototype_index}"
            )
        translated_name = None
        source_name = prototype_name
        name_source = f"PRO_CRIT.MSG:{prototype_index * 100}"
        if script_filename is not None:
            translated_name = script_lookup.get(script_filename.casefold())
            if translated_name is not None:
                source_name = Path(script_filename).stem
                name_source = "script_filename"
        if translated_name is None:
            translated_name = prototype_names.get(prototype_name)
        if not isinstance(translated_name, str) or not translated_name:
            raise MapRenderError(
                f"missing Chinese translation for extracted critter name {source_name!r}"
            )
        labels.append(
            CritterNameLabel(
                object_id=object_id,
                tile=tile,
                prototype_list_index=prototype_index,
                source_name=source_name,
                chinese_name=translated_name,
                english_name=bilingual_lookup.get(source_name.casefold()),
                name_source=name_source,
                script_filename=script_filename,
                target_x=target_x,
                target_y=target_y,
                missing_art=missing,
            )
        )
    font_source, font_data = _stable_file(font_path, "critter label font")
    return (
        tuple(labels),
        CritterLabelResources(
            names_message=names_message,
            translations_path=translation_source,
            translations_size=len(translation_data),
            translations_sha256=hashlib.sha256(translation_data).hexdigest().upper(),
            locale=locale,
            font_path=font_source,
            font_size_bytes=len(font_data),
            font_sha256=hashlib.sha256(font_data).hexdigest().upper(),
            font_pixels=font_pixels,
        ),
    )


def _item_name_labels(
    placements: tuple[ItemPlacement, ...],
    names_message_path: Path | str,
    translations_path: Path | str,
) -> tuple[tuple[ItemNameLabel, ...], ItemLabelResources]:
    names_message = load_msg(names_message_path, encoding="ascii")
    translation_source, translation_data = _stable_file(
        translations_path, "item name translations"
    )
    try:
        payload = json.loads(translation_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MapRenderError(f"invalid item name translations JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MapRenderError("unsupported item name translations schema")
    locale = payload.get("locale")
    prototype_names = payload.get("prototype_names")
    if (
        not isinstance(locale, str)
        or not locale
        or any(not (char.isascii() and (char.isalnum() or char == "-")) for char in locale)
    ):
        raise MapRenderError("item name translations has an invalid locale")
    if not isinstance(prototype_names, dict) or any(
        not isinstance(source_name, str)
        or not source_name
        or not isinstance(chinese_name, str)
        or not chinese_name
        for source_name, chinese_name in prototype_names.items()
    ):
        raise MapRenderError(
            "item name translations requires non-empty prototype_names strings"
        )
    message_names = {
        entry.number: entry.text
        for entry in names_message.entries
        if entry.effective and entry.text
    }

    def translated(prototype_list_index: int) -> tuple[str, str]:
        source_name = message_names.get(prototype_list_index * 100)
        if not source_name:
            raise MapRenderError(
                f"PRO_ITEM.MSG has no display name for item prototype {prototype_list_index}"
            )
        chinese_name = prototype_names.get(source_name)
        if not isinstance(chinese_name, str) or not chinese_name:
            raise MapRenderError(
                f"missing Chinese translation for extracted item name {source_name!r}"
            )
        return source_name, chinese_name

    labels: list[ItemNameLabel] = []
    for item in placements:
        if item.prototype_list_index is None:
            raise MapRenderError(
                f"item object {item.source_index} has no prototype list index for labels"
            )
        source_name, chinese_name = translated(item.prototype_list_index)
        contents = tuple(
            ItemLabelContent(
                prototype_list_index=entry.prototype_list_index,
                source_name=translated(entry.prototype_list_index)[0],
                chinese_name=translated(entry.prototype_list_index)[1],
                quantity=entry.quantity,
            )
            for entry in item.inventory
        )
        labels.append(
            ItemNameLabel(
                object_id=item.object_id,
                tile=item.tile,
                prototype_list_index=item.prototype_list_index,
                subtype_name=item.subtype_name,
                source_name=source_name,
                chinese_name=chinese_name,
                contents=contents,
                target_x=item.screen_x + item.frame.width // 2,
                target_y=item.screen_y,
            )
        )
    return (
        tuple(labels),
        ItemLabelResources(
            names_message=names_message,
            translations_path=translation_source,
            translations_size=len(translation_data),
            translations_sha256=hashlib.sha256(translation_data).hexdigest().upper(),
            locale=locale,
        ),
    )


def build_critter_render_plan(
    map_json: Path | str,
    tiles_list: Path | str,
    tiles_dir: Path | str,
    walls_list: Path | str,
    walls_dir: Path | str,
    scenery_list: Path | str,
    scenery_dir: Path | str,
    items_list: Path | str,
    items_dir: Path | str,
    critters_list: Path | str,
    critters_dir: Path | str,
    palette_path: Path | str,
    elevation: int,
    workspace: Path | str,
    output: Path | str,
    *,
    names_message_path: Path | str | None = None,
    name_translations_path: Path | str | None = None,
    item_names_message_path: Path | str | None = None,
    item_name_translations_path: Path | str | None = None,
    label_font_path: Path | str | None = None,
    label_font_pixels: int = 28,
) -> CritterRenderPlan:
    """Plan saved MAP critters and the complete static pre-roof layer."""
    (
        output_json,
        output_critter_png,
        output_composite_png,
        output_highlight_png,
        output_hash,
    ) = critter_render_output_paths(workspace, output)
    item_output = output_json.with_name(
        f"elevation-{elevation}-floor-walls-doors-scenery-items.json"
    )
    item_plan = build_item_render_plan(
        map_json,
        tiles_list,
        tiles_dir,
        walls_list,
        walls_dir,
        scenery_list,
        scenery_dir,
        items_list,
        items_dir,
        palette_path,
        elevation,
        workspace,
        item_output,
    )
    source, source_data, payload = _stable_json(map_json)
    floor = item_plan.scenery.door.wall.floor
    if (
        source != floor.map_json_path
        or hashlib.sha256(source_data).hexdigest().upper() != floor.map_json_sha256
    ):
        raise MapRenderError(f"map JSON changed while building render plan: {source}")
    objects = payload.get("objects")
    entries = objects.get("entries") if isinstance(objects, dict) else None
    if not isinstance(entries, list):
        raise MapRenderError("map JSON objects.entries must be an array")

    critter_list = load_lst(critters_list)
    critter_root = Path(critters_dir).resolve()
    files = _casefold_file_index(critter_root)
    selected: list[tuple[int, dict[str, Any]]] = []
    for source_index, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("elevation_group") != elevation:
            continue
        prototype = item.get("prototype")
        if isinstance(prototype, dict) and prototype.get("type") == "critter":
            selected.append((source_index, item))
    if not selected:
        raise MapRenderError("map elevation contains no critter objects")

    placements: list[CritterPlacement] = []
    missing_art: list[MissingCritterArt] = []
    documents: dict[str, FrmDocument] = {}
    hidden = 0
    transparent = 0
    flat = 0
    for source_index, item in selected:
        prototype = item.get("prototype")
        prototype_list_index = prototype.get("list_index") if isinstance(prototype, dict) else None
        tile = item.get("tile")
        object_id = item.get("object_id")
        rotation = item.get("rotation")
        frame_index = item.get("frame")
        object_x = item.get("x")
        object_y = item.get("y")
        flags = item.get("flags")
        fid = item.get("fid")
        if not isinstance(tile, int) or tile < 0 or tile >= HEX_GRID_WIDTH * HEX_GRID_HEIGHT:
            raise MapRenderError(f"critter object {source_index} has invalid tile")
        if not isinstance(object_id, int):
            raise MapRenderError(f"critter object {source_index} has invalid object id")
        if not isinstance(rotation, int) or rotation < 0 or rotation >= 6:
            raise MapRenderError(f"critter object {source_index} has invalid rotation")
        if not isinstance(frame_index, int):
            raise MapRenderError(f"critter object {source_index} has invalid frame")
        if not isinstance(object_x, int) or not isinstance(object_y, int):
            raise MapRenderError(f"critter object {source_index} has invalid pixel offset")
        if not isinstance(flags, int):
            raise MapRenderError(f"critter object {source_index} has invalid flags")
        if not isinstance(fid, int) or fid < 0:
            raise MapRenderError(f"critter object {source_index} has invalid FID")
        if not isinstance(prototype_list_index, int) or prototype_list_index < 0:
            if names_message_path is not None:
                raise MapRenderError(
                    f"critter object {source_index} has invalid prototype list index"
                )
            prototype_list_index = 0
        if (fid >> 24) & 0x0F != CRITTER_FID_TYPE:
            raise MapRenderError(
                f"critter object {source_index} FID is not critter art: 0x{fid:08X}"
            )
        script_filename = item.get("script_filename")
        if not isinstance(script_filename, str) or not script_filename:
            script_filename = None
        flat += bool(flags & OBJECT_FLAT)
        if flags & OBJECT_HIDDEN:
            hidden += 1
            continue
        art_id, resolved_art_id, base_name, filename, art_source = _critter_art_file(
            fid, critter_list, files
        )
        hex_x, hex_y = hex_tile_screen_position(tile)
        fallback_anchor_x = hex_x + 16 + object_x
        fallback_anchor_y = hex_y + 8 + object_y
        if art_source is None:
            missing_art.append(
                MissingCritterArt(
                    source_index=source_index,
                    object_id=object_id,
                    tile=tile,
                    fid=fid,
                    art_id=art_id,
                    resolved_art_id=resolved_art_id,
                    base_name=base_name,
                    filename=filename,
                    prototype_list_index=prototype_list_index,
                    script_filename=script_filename,
                    anchor_x=fallback_anchor_x,
                    anchor_y=fallback_anchor_y,
                )
            )
            continue
        document = documents.get(filename.casefold())
        if document is None:
            document = load_frm(art_source)
            documents[filename.casefold()] = document
        direction, frame = _critter_frame(document, rotation, frame_index)
        if not any(frame.pixels):
            transparent += 1
            continue
        anchor_x = hex_x + 16 + direction.x_offset + object_x
        anchor_y = hex_y + 8 + direction.y_offset + object_y
        placements.append(
            CritterPlacement(
                source_index=source_index,
                object_id=object_id,
                tile=tile,
                fid=fid,
                art_id=art_id,
                resolved_art_id=resolved_art_id,
                base_name=base_name,
                filename=filename,
                weapon_animation=(fid >> 12) & 0x0F,
                animation=(fid >> 16) & 0xFF,
                prototype_list_index=prototype_list_index,
                script_filename=script_filename,
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
    placements.sort(key=_object_placement_sort_key)
    if placements:
        left = min(item_plan.bounds_left, *(item.screen_x for item in placements))
        top = min(item_plan.bounds_top, *(item.screen_y for item in placements))
        right = max(
            item_plan.bounds_right, *(item.screen_x + item.frame.width for item in placements)
        )
        bottom = max(
            item_plan.bounds_bottom,
            *(item.screen_y + item.frame.height for item in placements),
        )
    else:
        left = item_plan.bounds_left
        top = item_plan.bounds_top
        right = item_plan.bounds_right
        bottom = item_plan.bounds_bottom
    label_arguments = (
        names_message_path,
        name_translations_path,
        label_font_path,
    )
    if any(value is not None for value in label_arguments) and not all(
        value is not None for value in label_arguments
    ):
        raise MapRenderError(
            "critter labels require names message, translations, and font together"
        )
    name_labels: tuple[CritterNameLabel, ...] = ()
    label_resources: CritterLabelResources | None = None
    output_label_png: Path | None = None
    if all(value is not None for value in label_arguments):
        name_labels, label_resources = _critter_name_labels(
            tuple(placements),
            tuple(missing_art),
            names_message_path,
            name_translations_path,
            label_font_path,
            label_font_pixels,
        )
        output_label_png = ensure_within_workspace(
            workspace,
            output_json.with_name(f"{output_json.stem}-labeled-{label_resources.locale}.png"),
        )
    item_label_arguments = (item_names_message_path, item_name_translations_path)
    if any(value is not None for value in item_label_arguments) and not all(
        value is not None for value in item_label_arguments
    ):
        raise MapRenderError("item labels require names message and translations together")
    if all(value is not None for value in item_label_arguments) and label_resources is None:
        raise MapRenderError(
            "combined item labels require critter labels and a shared font"
        )
    item_name_labels: tuple[ItemNameLabel, ...] = ()
    item_label_resources: ItemLabelResources | None = None
    if all(value is not None for value in item_label_arguments):
        item_name_labels, item_label_resources = _item_name_labels(
            item_plan.placements,
            item_names_message_path,
            item_name_translations_path,
        )
        if item_label_resources.locale != label_resources.locale:
            raise MapRenderError("item and critter label locales must match")
    sources = {source, critter_list.source_path, *files.values()}
    if label_resources is not None:
        sources.update(
            {
                label_resources.names_message.source_path,
                label_resources.translations_path,
                label_resources.font_path,
            }
        )
    if item_label_resources is not None:
        sources.update(
            {
                item_label_resources.names_message.source_path,
                item_label_resources.translations_path,
            }
        )
    collision = sources.intersection(
        (
            output_json,
            output_critter_png,
            output_composite_png,
            output_highlight_png,
            output_hash,
            *(() if output_label_png is None else (output_label_png,)),
        )
    )
    if collision:
        raise MapRenderError(f"render output would replace an input: {next(iter(collision))}")
    return CritterRenderPlan(
        item=item_plan,
        critter_list=critter_list,
        critter_root=critter_root,
        placements=tuple(placements),
        missing_art=tuple(missing_art),
        name_labels=name_labels,
        label_resources=label_resources,
        item_name_labels=item_name_labels,
        item_label_resources=item_label_resources,
        used_critter_ids=tuple(sorted({item.art_id for item in placements})),
        hidden_placements=hidden,
        transparent_placements=transparent,
        flat_placements=flat,
        bounds_left=left,
        bounds_top=top,
        bounds_right=right,
        bounds_bottom=bottom,
        output_json=output_json,
        output_critter_png=output_critter_png,
        output_composite_png=output_composite_png,
        output_highlight_png=output_highlight_png,
        output_label_png=output_label_png,
        output_hash=output_hash,
    )


def critter_render_summary(plan: CritterRenderPlan) -> dict[str, Any]:
    floor = plan.item.scenery.door.wall.floor
    return {
        "map": floor.map_name,
        "elevation": floor.elevation,
        "visible_floor_placements": len(floor.placements),
        "visible_wall_placements": len(plan.item.scenery.door.wall.placements),
        "visible_door_placements": len(plan.item.scenery.door.placements),
        "visible_scenery_placements": len(plan.item.scenery.placements),
        "visible_item_placements": len(plan.item.placements),
        "validated_critter_objects": (
            len(plan.placements)
            + len(plan.missing_art)
            + plan.hidden_placements
            + plan.transparent_placements
        ),
        "visible_critter_placements": len(plan.placements),
        "hidden_critter_placements": plan.hidden_placements,
        "transparent_critter_placements": plan.transparent_placements,
        "missing_critter_art_placements": len(plan.missing_art),
        "critter_name_labels": len(plan.name_labels),
        "missing_art_name_labels": sum(item.missing_art for item in plan.name_labels),
        "item_name_labels": len(plan.item_name_labels),
        "container_content_labels": sum(
            item.subtype_name == "container" for item in plan.item_name_labels
        ),
        "flat_critter_objects": plan.flat_placements,
        "critter_placements_extending_previous_bounds": sum(
            item.screen_x < plan.item.bounds_left
            or item.screen_y < plan.item.bounds_top
            or item.screen_x + item.frame.width > plan.item.bounds_right
            or item.screen_y + item.frame.height > plan.item.bounds_bottom
            for item in plan.placements
        ),
        "unique_visible_critter_ids": len(plan.used_critter_ids),
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
    placements: (
        tuple[TilePlacement, ...]
        | tuple[WallPlacement, ...]
        | tuple[DoorPlacement, ...]
        | tuple[SceneryPlacement, ...]
        | tuple[ItemPlacement, ...]
        | tuple[CritterPlacement, ...]
        | tuple[
            WallPlacement | DoorPlacement | SceneryPlacement | ItemPlacement | CritterPlacement,
            ...,
        ]
    ),
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


def _door_pngs(plan: DoorRenderPlan) -> tuple[bytes, bytes]:
    door_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        door_pixels,
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
        plan.wall.floor.placements,
    )
    objects: tuple[WallPlacement | DoorPlacement, ...] = tuple(
        sorted(
            (*plan.wall.placements, *plan.placements),
            key=_object_placement_sort_key,
        )
    )
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        objects,
    )
    door_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(door_pixels),
        plan.wall.floor.palette,
        transparent_index_zero=True,
    )
    composite_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(composite_pixels),
        plan.wall.floor.palette,
        transparent_index_zero=True,
    )
    return door_png, composite_png


def write_door_render(
    plan: DoorRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path, Path]:
    """Write door-only and game-ordered floor-wall-door render outputs."""
    targets = (
        plan.output_json,
        plan.output_door_png,
        plan.output_composite_png,
        plan.output_hash,
    )
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    door_png, composite_png = _door_pngs(plan)
    door_sha256 = hashlib.sha256(door_png).hexdigest().upper()
    composite_sha256 = hashlib.sha256(composite_png).hexdigest().upper()
    floor = plan.wall.floor
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP floor, wall, and door render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(floor.map_json_path),
                "size": floor.map_json_size,
                "sha256": floor.map_json_sha256,
            },
            "tiles_list": {
                "path": str(floor.tile_list.source_path),
                "size": floor.tile_list.source_size,
                "sha256": floor.tile_list.source_sha256,
            },
            "tiles_directory": str(floor.tile_root),
            "walls_list": {
                "path": str(plan.wall.wall_list.source_path),
                "size": plan.wall.wall_list.source_size,
                "sha256": plan.wall.wall_list.source_sha256,
            },
            "walls_directory": str(plan.wall.wall_root),
            "scenery_list": {
                "path": str(plan.scenery_list.source_path),
                "size": plan.scenery_list.source_size,
                "sha256": plan.scenery_list.source_sha256,
            },
            "scenery_directory": str(plan.scenery_root),
            "palette": {
                "path": str(floor.palette.source_path),
                "size": floor.palette.source_size,
                "sha256": floor.palette.source_sha256,
            },
        },
        "summary": door_render_summary(plan),
        "coordinates": {
            "hex_column": "199 - (tile % 200)",
            "hex_row": "tile // 200",
            "anchor_x": "hex_x + 16 + direction_x_offset + object_x",
            "anchor_y": "hex_y + 8 + direction_y_offset + object_y",
            "frame_left": "anchor_x - frame_width // 2",
            "frame_top": "anchor_y - (frame_height - 1)",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": (
                "walls and doors combined: OBJECT_FLAT first, then non-flat; "
                "tile and MAP source order ascending"
            ),
        },
        "door_state": {
            "closed": "stored frame == 0",
            "open_or_transition": "stored frame != 0",
            "target_open_mask": f"0x{DOOR_OPEN:08X}",
            "locked_mask": f"0x{DOOR_LOCKED:08X}",
            "jammed_mask": f"0x{DOOR_JAMMED:08X}",
        },
        "used_doors": [
            {
                "id": art_id,
                "filename": plan.scenery_list.entries[art_id].filename,
                "placements": sum(item.art_id == art_id for item in plan.placements),
            }
            for art_id in plan.used_door_ids
        ],
        "doors": [
            {
                "object_id": item.object_id,
                "tile": item.tile,
                "art_id": item.art_id,
                "filename": item.filename,
                "rotation": item.rotation,
                "frame": item.frame_index,
                "state": "closed" if item.frame_index == 0 else "open_or_transition",
                "open_flags": item.open_flags,
                "open_flags_hex": f"0x{item.open_flags & 0xFFFFFFFF:08X}",
            }
            for item in plan.placements
        ],
        "derived": {
            "door_png": {
                "path": plan.output_door_png.name,
                "size": len(door_png),
                "sha256": door_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_png": {
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
    write_file_atomic(plan.output_door_png, door_png, overwrite=overwrite)
    write_file_atomic(plan.output_composite_png, composite_png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return (
        plan.output_json,
        plan.output_door_png,
        plan.output_composite_png,
        plan.output_hash,
    )


def _scenery_pngs(plan: SceneryRenderPlan) -> tuple[bytes, bytes]:
    scenery_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        scenery_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
    composite_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    floor = plan.door.wall.floor
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        floor.placements,
    )
    objects: tuple[WallPlacement | DoorPlacement | SceneryPlacement, ...] = tuple(
        sorted(
            (*plan.door.wall.placements, *plan.door.placements, *plan.placements),
            key=_object_placement_sort_key,
        )
    )
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        objects,
    )
    scenery_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(scenery_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    composite_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(composite_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    return scenery_png, composite_png


def write_scenery_render(
    plan: SceneryRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path, Path]:
    """Write non-door scenery and the complete pre-roof static map layer."""
    targets = (
        plan.output_json,
        plan.output_scenery_png,
        plan.output_composite_png,
        plan.output_hash,
    )
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    scenery_png, composite_png = _scenery_pngs(plan)
    scenery_sha256 = hashlib.sha256(scenery_png).hexdigest().upper()
    composite_sha256 = hashlib.sha256(composite_png).hexdigest().upper()
    floor = plan.door.wall.floor
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP pre-roof static scenery render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(floor.map_json_path),
                "size": floor.map_json_size,
                "sha256": floor.map_json_sha256,
            },
            "tiles_list": {
                "path": str(floor.tile_list.source_path),
                "size": floor.tile_list.source_size,
                "sha256": floor.tile_list.source_sha256,
            },
            "tiles_directory": str(floor.tile_root),
            "walls_list": {
                "path": str(plan.door.wall.wall_list.source_path),
                "size": plan.door.wall.wall_list.source_size,
                "sha256": plan.door.wall.wall_list.source_sha256,
            },
            "walls_directory": str(plan.door.wall.wall_root),
            "scenery_list": {
                "path": str(plan.door.scenery_list.source_path),
                "size": plan.door.scenery_list.source_size,
                "sha256": plan.door.scenery_list.source_sha256,
            },
            "scenery_directory": str(plan.door.scenery_root),
            "palette": {
                "path": str(floor.palette.source_path),
                "size": floor.palette.source_size,
                "sha256": floor.palette.source_sha256,
            },
        },
        "summary": scenery_render_summary(plan),
        "coordinates": {
            "hex_column": "199 - (tile % 200)",
            "hex_row": "tile // 200",
            "anchor_x": "hex_x + 16 + direction_x_offset + object_x",
            "anchor_y": "hex_y + 8 + direction_y_offset + object_y",
            "frame_left": "anchor_x - frame_width // 2",
            "frame_top": "anchor_y - (frame_height - 1)",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": (
                "walls, doors, and non-door scenery combined: OBJECT_FLAT first, then "
                "non-flat; tile and MAP source order ascending"
            ),
        },
        "used_scenery": [
            {
                "id": art_id,
                "filename": plan.door.scenery_list.entries[art_id].filename,
                "placements": sum(item.art_id == art_id for item in plan.placements),
            }
            for art_id in plan.used_scenery_ids
        ],
        "scenery": [
            {
                "object_id": item.object_id,
                "tile": item.tile,
                "art_id": item.art_id,
                "filename": item.filename,
                "subtype": item.subtype_name,
                "rotation": item.rotation,
                "frame": item.frame_index,
            }
            for item in plan.placements
        ],
        "derived": {
            "scenery_png": {
                "path": plan.output_scenery_png.name,
                "size": len(scenery_png),
                "sha256": scenery_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_scenery_png": {
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
    write_file_atomic(plan.output_scenery_png, scenery_png, overwrite=overwrite)
    write_file_atomic(plan.output_composite_png, composite_png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return (
        plan.output_json,
        plan.output_scenery_png,
        plan.output_composite_png,
        plan.output_hash,
    )


def _nearest_palette_index(palette: FalloutPalette, target: tuple[int, int, int]) -> int:
    red, green, blue = target
    return min(
        range(1, len(palette.colors)),
        key=lambda index: (
            (palette.colors[index].red - red) ** 2
            + (palette.colors[index].green - green) ** 2
            + (palette.colors[index].blue - blue) ** 2,
            index,
        ),
    )


def _outline_placements(
    pixels: bytearray,
    protected_pixels: bytearray,
    canvas_width: int,
    canvas_height: int,
    bounds_left: int,
    bounds_top: int,
    placements: tuple[ItemPlacement, ...] | tuple[CritterPlacement, ...],
    color_index: int,
    radius: int,
) -> None:
    if radius <= 0:
        raise ValueError("object outline radius must be positive")
    for placement in placements:
        destination_x = placement.screen_x - bounds_left
        destination_y = placement.screen_y - bounds_top
        frame = placement.frame
        for row in range(frame.height):
            for column, value in enumerate(
                frame.pixels[row * frame.width : (row + 1) * frame.width]
            ):
                if not value:
                    continue
                pixel_x = destination_x + column
                pixel_y = destination_y + row
                for outline_y in range(
                    max(0, pixel_y - radius), min(canvas_height, pixel_y + radius + 1)
                ):
                    outline_start = outline_y * canvas_width
                    for outline_x in range(
                        max(0, pixel_x - radius), min(canvas_width, pixel_x + radius + 1)
                    ):
                        outline_index = outline_start + outline_x
                        if not protected_pixels[outline_index]:
                            pixels[outline_index] = color_index


def _item_pngs(plan: ItemRenderPlan) -> tuple[bytes, bytes, bytes, int]:
    item_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        item_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
    composite_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    floor = plan.scenery.door.wall.floor
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        floor.placements,
    )
    objects: tuple[WallPlacement | DoorPlacement | SceneryPlacement | ItemPlacement, ...] = tuple(
        sorted(
            (
                *plan.scenery.door.wall.placements,
                *plan.scenery.door.placements,
                *plan.scenery.placements,
                *plan.placements,
            ),
            key=_object_placement_sort_key,
        )
    )
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        objects,
    )
    outline_index = _nearest_palette_index(
        floor.palette,
        ITEM_OUTLINE_TARGET_RGB,
    )
    highlighted_pixels = bytearray(composite_pixels)
    _outline_placements(
        highlighted_pixels,
        item_pixels,
        plan.canvas_width,
        plan.canvas_height,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
        outline_index,
        ITEM_OUTLINE_RADIUS,
    )
    item_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(item_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    composite_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(composite_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    highlight_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(highlighted_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    return item_png, composite_png, highlight_png, outline_index


def write_item_render(
    plan: ItemRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path, Path, Path]:
    """Write top-level items and the complete pre-roof static object layer."""
    targets = (
        plan.output_json,
        plan.output_item_png,
        plan.output_composite_png,
        plan.output_highlight_png,
        plan.output_hash,
    )
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    item_png, composite_png, highlight_png, outline_index = _item_pngs(plan)
    item_sha256 = hashlib.sha256(item_png).hexdigest().upper()
    composite_sha256 = hashlib.sha256(composite_png).hexdigest().upper()
    highlight_sha256 = hashlib.sha256(highlight_png).hexdigest().upper()
    scenery = plan.scenery
    door = scenery.door
    wall = door.wall
    floor = wall.floor
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP pre-roof static item render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(floor.map_json_path),
                "size": floor.map_json_size,
                "sha256": floor.map_json_sha256,
            },
            "tiles_list": {
                "path": str(floor.tile_list.source_path),
                "size": floor.tile_list.source_size,
                "sha256": floor.tile_list.source_sha256,
            },
            "tiles_directory": str(floor.tile_root),
            "walls_list": {
                "path": str(wall.wall_list.source_path),
                "size": wall.wall_list.source_size,
                "sha256": wall.wall_list.source_sha256,
            },
            "walls_directory": str(wall.wall_root),
            "scenery_list": {
                "path": str(door.scenery_list.source_path),
                "size": door.scenery_list.source_size,
                "sha256": door.scenery_list.source_sha256,
            },
            "scenery_directory": str(door.scenery_root),
            "items_list": {
                "path": str(plan.item_list.source_path),
                "size": plan.item_list.source_size,
                "sha256": plan.item_list.source_sha256,
            },
            "items_directory": str(plan.item_root),
            "palette": {
                "path": str(floor.palette.source_path),
                "size": floor.palette.source_size,
                "sha256": floor.palette.source_sha256,
            },
        },
        "summary": item_render_summary(plan),
        "coordinates": {
            "hex_column": "199 - (tile % 200)",
            "hex_row": "tile // 200",
            "anchor_x": "hex_x + 16 + direction_x_offset + object_x",
            "anchor_y": "hex_y + 8 + direction_y_offset + object_y",
            "frame_left": "anchor_x - frame_width // 2",
            "frame_top": "anchor_y - (frame_height - 1)",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": (
                "walls, doors, scenery, and top-level items combined: OBJECT_FLAT first, "
                "then non-flat; tile and MAP source order ascending"
            ),
        },
        "inventory_policy": (
            "Only top-level MAP item objects are rendered; objects contained in inventories "
            "are recorded but not drawn as ground placements."
        ),
        "item_outline": {
            "radius_pixels": ITEM_OUTLINE_RADIUS,
            "target_rgb": list(ITEM_OUTLINE_TARGET_RGB),
            "palette_index": outline_index,
            "actual_rgb": [
                floor.palette.colors[outline_index].red,
                floor.palette.colors[outline_index].green,
                floor.palette.colors[outline_index].blue,
            ],
            "scope": "non-transparent pixels of every visible top-level item placement",
        },
        "used_items": [
            {
                "id": art_id,
                "filename": plan.item_list.entries[art_id].filename,
                "placements": sum(item.art_id == art_id for item in plan.placements),
            }
            for art_id in plan.used_item_ids
        ],
        "items": [
            {
                "object_id": item.object_id,
                "tile": item.tile,
                "art_id": item.art_id,
                "filename": item.filename,
                "subtype": item.subtype_name,
                "rotation": item.rotation,
                "frame": item.frame_index,
            }
            for item in plan.placements
        ],
        "derived": {
            "item_png": {
                "path": plan.output_item_png.name,
                "size": len(item_png),
                "sha256": item_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_scenery_items_png": {
                "path": plan.output_composite_png.name,
                "size": len(composite_png),
                "sha256": composite_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_scenery_items_highlighted_png": {
                "path": plan.output_highlight_png.name,
                "size": len(highlight_png),
                "sha256": highlight_sha256,
                "transparency": "palette index 0",
            },
        },
    }
    json_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = (
        f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {plan.output_json.name}\n"
    ).encode("ascii")
    write_file_atomic(plan.output_item_png, item_png, overwrite=overwrite)
    write_file_atomic(plan.output_composite_png, composite_png, overwrite=overwrite)
    write_file_atomic(plan.output_highlight_png, highlight_png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return (
        plan.output_json,
        plan.output_item_png,
        plan.output_composite_png,
        plan.output_highlight_png,
        plan.output_hash,
    )


def _critter_pngs(plan: CritterRenderPlan) -> tuple[bytes, bytes, bytes, int, int]:
    critter_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        critter_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
    )
    item_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    _blit_placements(
        item_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        plan.item.placements,
    )
    composite_pixels = bytearray(plan.canvas_width * plan.canvas_height)
    floor = plan.item.scenery.door.wall.floor
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        floor.placements,
    )
    objects: tuple[
        WallPlacement | DoorPlacement | SceneryPlacement | ItemPlacement | CritterPlacement,
        ...,
    ] = tuple(
        sorted(
            (
                *plan.item.scenery.door.wall.placements,
                *plan.item.scenery.door.placements,
                *plan.item.scenery.placements,
                *plan.item.placements,
                *plan.placements,
            ),
            key=_object_placement_sort_key,
        )
    )
    _blit_placements(
        composite_pixels,
        plan.canvas_width,
        plan.bounds_left,
        plan.bounds_top,
        objects,
    )
    item_outline_index = _nearest_palette_index(floor.palette, ITEM_OUTLINE_TARGET_RGB)
    critter_outline_index = _nearest_palette_index(floor.palette, CRITTER_OUTLINE_TARGET_RGB)
    highlighted_pixels = bytearray(composite_pixels)
    protected_pixels = bytearray(
        item_pixel or critter_pixel
        for item_pixel, critter_pixel in zip(item_pixels, critter_pixels, strict=True)
    )
    _outline_placements(
        highlighted_pixels,
        protected_pixels,
        plan.canvas_width,
        plan.canvas_height,
        plan.bounds_left,
        plan.bounds_top,
        plan.item.placements,
        item_outline_index,
        ITEM_OUTLINE_RADIUS,
    )
    _outline_placements(
        highlighted_pixels,
        protected_pixels,
        plan.canvas_width,
        plan.canvas_height,
        plan.bounds_left,
        plan.bounds_top,
        plan.placements,
        critter_outline_index,
        CRITTER_OUTLINE_RADIUS,
    )
    critter_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(critter_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    composite_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(composite_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    highlight_png = encode_indexed_png(
        plan.canvas_width,
        plan.canvas_height,
        bytes(highlighted_pixels),
        floor.palette,
        transparent_index_zero=True,
    )
    return (
        critter_png,
        composite_png,
        highlight_png,
        item_outline_index,
        critter_outline_index,
    )


def _critter_label_text(label: CritterNameLabel) -> str:
    if label.english_name is None:
        return label.chinese_name
    return f"{label.chinese_name} / {label.english_name}"


def _item_label_text(label: ItemNameLabel) -> str:
    if label.subtype_name != "container":
        return label.chinese_name
    if not label.contents:
        return f"{label.chinese_name}\n　　（空）"
    content_lines = tuple(
        f"　　{item.chinese_name} ×{item.quantity}" for item in label.contents
    )
    return "\n".join((label.chinese_name, *content_lines))


def _labelled_object_png(
    plan: CritterRenderPlan, highlight_png: bytes
) -> tuple[
    bytes,
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    str,
]:
    if plan.label_resources is None or plan.output_label_png is None:
        raise MapRenderError("critter label resources are not configured")
    try:
        from PIL import Image, ImageDraw, ImageFont
        from PIL import __version__ as pillow_version
    except ImportError as exc:
        raise MapRenderError("Pillow is required to render translated critter name labels") from exc
    with Image.open(io.BytesIO(highlight_png)) as source_image:
        canvas = source_image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(
            str(plan.label_resources.font_path), plan.label_resources.font_pixels
        )
    except OSError as exc:
        raise MapRenderError(
            f"cannot load critter label font: {plan.label_resources.font_path}: {exc}"
        ) from exc

    placed_boxes: list[tuple[int, int, int, int]] = []
    critter_layout: list[dict[str, Any]] = []
    item_layout: list[dict[str, Any]] = []

    def place_label(
        text: str,
        target_x_global: int,
        target_y_global: int,
        connector_color: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        text_box = draw.multiline_textbbox(
            (0, 0), text, font=font, spacing=3, stroke_width=1
        )
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        box_width = text_width + 12
        box_height = text_height + 8
        target_x = target_x_global - plan.bounds_left
        target_y = target_y_global - plan.bounds_top
        horizontal_offsets = (0, -box_width - 8, box_width + 8, -2 * box_width, 2 * box_width)
        candidates: list[tuple[int, int, int, int]] = []
        for level in range(14):
            above_y = target_y - 10 - box_height - level * (box_height + 4)
            below_y = target_y + 10 + level * (box_height + 4)
            for candidate_y in (above_y, below_y):
                for horizontal_offset in horizontal_offsets:
                    candidate_x = target_x - box_width // 2 + horizontal_offset
                    candidate_x = max(0, min(plan.canvas_width - box_width, candidate_x))
                    candidate_y_clamped = max(
                        0, min(plan.canvas_height - box_height, candidate_y)
                    )
                    candidates.append(
                        (
                            candidate_x,
                            candidate_y_clamped,
                            candidate_x + box_width,
                            candidate_y_clamped + box_height,
                        )
                    )
        selected_box = next(
            (
                candidate
                for candidate in candidates
                if all(
                    candidate[2] + 3 <= placed[0]
                    or candidate[0] >= placed[2] + 3
                    or candidate[3] + 3 <= placed[1]
                    or candidate[1] >= placed[3] + 3
                    for placed in placed_boxes
                )
            ),
            candidates[0],
        )
        placed_boxes.append(selected_box)
        left, top, right, bottom = selected_box
        connector_y = bottom if bottom <= target_y else top
        draw.line(
            (target_x, target_y, (left + right) // 2, connector_y),
            fill=connector_color,
            width=1,
        )
        draw.rectangle(
            selected_box,
            fill=(0, 0, 0, 218),
            outline=connector_color,
            width=1,
        )
        draw.multiline_text(
            (left + 6 - text_box[0], top + 4 - text_box[1]),
            text,
            font=font,
            fill=(255, 255, 255, 255),
            spacing=3,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )
        return selected_box

    ordered_labels = sorted(
        plan.name_labels,
        key=lambda item: (item.target_y, item.target_x, item.object_id),
    )
    for label in ordered_labels:
        target_x = label.target_x - plan.bounds_left
        target_y = label.target_y - plan.bounds_top
        display_name = _critter_label_text(label)
        selected_box = place_label(
            display_name,
            label.target_x,
            label.target_y,
            (101, 231, 101, 255),
        )
        critter_layout.append(
            {
                "object_id": label.object_id,
                "tile": label.tile,
                "prototype_list_index": label.prototype_list_index,
                "source_name": label.source_name,
                "chinese_name": label.chinese_name,
                "english_name": label.english_name,
                "display_name": display_name,
                "name_source": label.name_source,
                "script_filename": label.script_filename,
                "missing_art": label.missing_art,
                "target_global": [label.target_x, label.target_y],
                "target_canvas": [target_x, target_y],
                "label_box_canvas": list(selected_box),
            }
        )

    ordered_item_labels = sorted(
        plan.item_name_labels,
        key=lambda item: (item.target_y, item.target_x, item.object_id),
    )
    for label in ordered_item_labels:
        target_x = label.target_x - plan.bounds_left
        target_y = label.target_y - plan.bounds_top
        text = _item_label_text(label)
        selected_box = place_label(
            text,
            label.target_x,
            label.target_y,
            (255, 215, 0, 255),
        )
        item_layout.append(
            {
                "object_id": label.object_id,
                "tile": label.tile,
                "prototype_list_index": label.prototype_list_index,
                "subtype_name": label.subtype_name,
                "source_name": label.source_name,
                "chinese_name": label.chinese_name,
                "contents": [
                    {
                        "prototype_list_index": item.prototype_list_index,
                        "source_name": item.source_name,
                        "chinese_name": item.chinese_name,
                        "quantity": item.quantity,
                    }
                    for item in label.contents
                ],
                "target_global": [label.target_x, label.target_y],
                "target_canvas": [target_x, target_y],
                "label_box_canvas": list(selected_box),
                "display_lines": text.splitlines(),
            }
        )
    output = io.BytesIO()
    canvas.save(output, format="PNG", compress_level=9, optimize=False)
    return (
        output.getvalue(),
        tuple(critter_layout),
        tuple(item_layout),
        pillow_version,
    )


def write_critter_render(
    plan: CritterRenderPlan, *, overwrite: bool = False
) -> tuple[Path, Path, Path, Path, Path]:
    """Write saved critters and the complete static pre-roof object layer."""
    targets = (
        plan.output_json,
        plan.output_critter_png,
        plan.output_composite_png,
        plan.output_highlight_png,
        plan.output_hash,
        *(() if plan.output_label_png is None else (plan.output_label_png,)),
    )
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(
                f"render output already exists; refusing to overwrite: {existing[0]}"
            )
    (
        critter_png,
        composite_png,
        highlight_png,
        item_outline_index,
        critter_outline_index,
    ) = _critter_pngs(plan)
    critter_sha256 = hashlib.sha256(critter_png).hexdigest().upper()
    composite_sha256 = hashlib.sha256(composite_png).hexdigest().upper()
    highlight_sha256 = hashlib.sha256(highlight_png).hexdigest().upper()
    label_png: bytes | None = None
    critter_label_layout: tuple[dict[str, Any], ...] = ()
    item_label_layout: tuple[dict[str, Any], ...] = ()
    pillow_version: str | None = None
    if plan.label_resources is not None:
        (
            label_png,
            critter_label_layout,
            item_label_layout,
            pillow_version,
        ) = _labelled_object_png(plan, highlight_png)
    item = plan.item
    scenery = item.scenery
    door = scenery.door
    wall = door.wall
    floor = wall.floor
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout MAP static critter render",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "map_render",
            "component_version": MAP_RENDERER_VERSION,
        },
        "source": {
            "map_json": {
                "path": str(floor.map_json_path),
                "size": floor.map_json_size,
                "sha256": floor.map_json_sha256,
            },
            "tiles_list": {
                "path": str(floor.tile_list.source_path),
                "size": floor.tile_list.source_size,
                "sha256": floor.tile_list.source_sha256,
            },
            "tiles_directory": str(floor.tile_root),
            "walls_list": {
                "path": str(wall.wall_list.source_path),
                "size": wall.wall_list.source_size,
                "sha256": wall.wall_list.source_sha256,
            },
            "walls_directory": str(wall.wall_root),
            "scenery_list": {
                "path": str(door.scenery_list.source_path),
                "size": door.scenery_list.source_size,
                "sha256": door.scenery_list.source_sha256,
            },
            "scenery_directory": str(door.scenery_root),
            "items_list": {
                "path": str(item.item_list.source_path),
                "size": item.item_list.source_size,
                "sha256": item.item_list.source_sha256,
            },
            "items_directory": str(item.item_root),
            "critters_list": {
                "path": str(plan.critter_list.source_path),
                "size": plan.critter_list.source_size,
                "sha256": plan.critter_list.source_sha256,
            },
            "critters_directory": str(plan.critter_root),
            "palette": {
                "path": str(floor.palette.source_path),
                "size": floor.palette.source_size,
                "sha256": floor.palette.source_sha256,
            },
        },
        "summary": critter_render_summary(plan),
        "coordinates": {
            "hex_column": "199 - (tile % 200)",
            "hex_row": "tile // 200",
            "anchor_x": "hex_x + 16 + direction_x_offset + object_x",
            "anchor_y": "hex_y + 8 + direction_y_offset + object_y",
            "frame_left": "anchor_x - frame_width // 2",
            "frame_top": "anchor_y - (frame_height - 1)",
            "canvas_translation": [-plan.bounds_left, -plan.bounds_top],
            "draw_order": (
                "walls, doors, scenery, top-level items, and critters combined: "
                "OBJECT_FLAT first, then non-flat; tile and MAP source order ascending"
            ),
        },
        "static_snapshot_policy": (
            "Critters are rendered from the FID, rotation, and saved frame stored in the MAP. "
            "Runtime movement, animation, scripts, lighting, and the player character are not "
            "simulated. Missing critter artwork is recorded and not substituted."
        ),
        "critter_outline": {
            "radius_pixels": CRITTER_OUTLINE_RADIUS,
            "target_rgb": list(CRITTER_OUTLINE_TARGET_RGB),
            "palette_index": critter_outline_index,
            "actual_rgb": [
                floor.palette.colors[critter_outline_index].red,
                floor.palette.colors[critter_outline_index].green,
                floor.palette.colors[critter_outline_index].blue,
            ],
            "scope": "non-transparent pixels of every visible critter placement",
        },
        "item_outline": {
            "radius_pixels": ITEM_OUTLINE_RADIUS,
            "target_rgb": list(ITEM_OUTLINE_TARGET_RGB),
            "palette_index": item_outline_index,
            "actual_rgb": [
                floor.palette.colors[item_outline_index].red,
                floor.palette.colors[item_outline_index].green,
                floor.palette.colors[item_outline_index].blue,
            ],
            "scope": "non-transparent pixels of every visible top-level item placement",
        },
        "used_critters": [
            {
                "id": art_id,
                "base_name": _critter_list_entry(art_id, plan.critter_list)[0],
                "placements": sum(item.art_id == art_id for item in plan.placements),
            }
            for art_id in plan.used_critter_ids
        ],
        "critters": [
            {
                "object_id": item.object_id,
                "tile": item.tile,
                "fid": item.fid,
                "fid_hex": f"0x{item.fid:08X}",
                "art_id": item.art_id,
                "resolved_art_id": item.resolved_art_id,
                "base_name": item.base_name,
                "filename": item.filename,
                "weapon_animation": item.weapon_animation,
                "animation": item.animation,
                "prototype_list_index": item.prototype_list_index,
                "script_filename": item.script_filename,
                "rotation": item.rotation,
                "frame": item.frame_index,
            }
            for item in plan.placements
        ],
        "missing_critter_art": [
            {
                "object_id": item.object_id,
                "tile": item.tile,
                "fid": item.fid,
                "fid_hex": f"0x{item.fid:08X}",
                "art_id": item.art_id,
                "resolved_art_id": item.resolved_art_id,
                "base_name": item.base_name,
                "filename": item.filename,
                "prototype_list_index": item.prototype_list_index,
                "script_filename": item.script_filename,
            }
            for item in plan.missing_art
        ],
        "derived": {
            "critter_png": {
                "path": plan.output_critter_png.name,
                "size": len(critter_png),
                "sha256": critter_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_scenery_items_critters_png": {
                "path": plan.output_composite_png.name,
                "size": len(composite_png),
                "sha256": composite_sha256,
                "transparency": "palette index 0",
            },
            "floor_walls_doors_scenery_items_critters_highlighted_png": {
                "path": plan.output_highlight_png.name,
                "size": len(highlight_png),
                "sha256": highlight_sha256,
                "transparency": "palette index 0",
            },
        },
    }
    if plan.label_resources is not None:
        if label_png is None or plan.output_label_png is None or pillow_version is None:
            raise MapRenderError("critter label render did not produce its required output")
        resources = plan.label_resources
        metadata["source"]["critter_names_message"] = {
            "path": str(resources.names_message.source_path),
            "size": resources.names_message.source_size,
            "sha256": resources.names_message.source_sha256,
            "encoding": resources.names_message.decoded.encoding,
        }
        metadata["source"]["critter_name_translations"] = {
            "path": str(resources.translations_path),
            "size": resources.translations_size,
            "sha256": resources.translations_sha256,
            "locale": resources.locale,
        }
        metadata["source"]["critter_label_font"] = {
            "path": str(resources.font_path),
            "size": resources.font_size_bytes,
            "sha256": resources.font_sha256,
            "font_pixels": resources.font_pixels,
        }
        metadata["critter_name_labels"] = {
            "locale": resources.locale,
            "font_pixels": resources.font_pixels,
            "renderer": "Pillow",
            "renderer_version": pillow_version,
            "name_policy": (
                "Use a translated script filename override when configured; otherwise use "
                "the translated PRO_CRIT.MSG prototype display name. Explicitly configured "
                "named characters display Chinese and English; generic roles display Chinese only."
            ),
            "labels": list(critter_label_layout),
        }
        if plan.item_label_resources is not None:
            item_resources = plan.item_label_resources
            metadata["source"]["item_names_message"] = {
                "path": str(item_resources.names_message.source_path),
                "size": item_resources.names_message.source_size,
                "sha256": item_resources.names_message.source_sha256,
                "encoding": item_resources.names_message.decoded.encoding,
            }
            metadata["source"]["item_name_translations"] = {
                "path": str(item_resources.translations_path),
                "size": item_resources.translations_size,
                "sha256": item_resources.translations_sha256,
                "locale": item_resources.locale,
            }
            metadata["item_name_labels"] = {
                "locale": item_resources.locale,
                "font_pixels": resources.font_pixels,
                "renderer": "Pillow",
                "renderer_version": pillow_version,
                "name_policy": (
                    "Use PRO_ITEM.MSG prototype display names and explicit Chinese "
                    "translations. Containers list every direct MAP inventory entry and "
                    "quantity; empty containers are marked as empty."
                ),
                "labels": list(item_label_layout),
            }
        metadata["derived"]["floor_walls_doors_scenery_items_critters_labeled_png"] = {
            "path": plan.output_label_png.name,
            "size": len(label_png),
            "sha256": hashlib.sha256(label_png).hexdigest().upper(),
            "base": plan.output_highlight_png.name,
        }
    json_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = (
        f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {plan.output_json.name}\n"
    ).encode("ascii")
    write_file_atomic(plan.output_critter_png, critter_png, overwrite=overwrite)
    write_file_atomic(plan.output_composite_png, composite_png, overwrite=overwrite)
    write_file_atomic(plan.output_highlight_png, highlight_png, overwrite=overwrite)
    if label_png is not None and plan.output_label_png is not None:
        write_file_atomic(plan.output_label_png, label_png, overwrite=overwrite)
    write_file_atomic(plan.output_json, json_bytes, overwrite=overwrite)
    write_file_atomic(plan.output_hash, hash_bytes, overwrite=overwrite)
    return (
        plan.output_json,
        plan.output_critter_png,
        plan.output_composite_png,
        plan.output_highlight_png,
        plan.output_hash,
    )
