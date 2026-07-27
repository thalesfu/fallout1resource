"""Parse Fallout 1 MAP files and link objects to LST/PRO metadata."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace
from .proto import ListDocument, Prototype, PrototypeCatalog, load_lst
from .safe_io import write_file_atomic


MAP_VERSION = 19
MAP_HEADER_SIZE = 236
ELEVATION_COUNT = 3
SQUARE_GRID_SIZE = 100 * 100
SCRIPT_TYPE_NAMES = ("system", "spatial", "timed", "item", "critter")
ELEVATION_EMPTY_FLAGS = (0x02, 0x04, 0x08)


class MapFormatError(ValueError):
    """Raised when MAP structures or linked prototype metadata are invalid."""


@dataclass(frozen=True, slots=True)
class MapHeader:
    version: int
    name: str
    entering_tile: int
    entering_elevation: int
    entering_rotation: int
    local_variables_count: int
    script_index: int
    flags: int
    darkness: int
    global_variables_count: int
    map_number: int
    last_visit_time: int
    reserved: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MapScript:
    script_type: int
    script_type_name: str
    script_id: int
    next_script_id: int
    script_flags: int
    script_index: int
    script_filename: str | None
    object_id: int
    local_variable_offset: int
    local_variable_count: int
    payload: dict[str, int]


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    quantity: int
    item: "MapObject"


@dataclass(frozen=True, slots=True)
class MapObject:
    file_offset: int
    elevation_group: int
    object_id: int
    tile: int
    x: int
    y: int
    screen_x: int
    screen_y: int
    frame: int
    rotation: int
    fid: int
    flags: int
    stored_elevation: int
    pid: int
    cid: int
    light_distance: int
    light_intensity: int
    field_74: int
    script_id: int
    field_80: int
    inventory_length: int
    inventory_capacity: int
    inventory_pointer: int
    update_data: dict[str, Any]
    prototype: Prototype
    prototype_filename: str
    script_filename: str | None
    inventory: tuple[InventoryEntry, ...]


@dataclass(frozen=True, slots=True)
class MapDocument:
    source_path: Path
    source_size: int
    source_sha256: str
    header: MapHeader
    global_variables: tuple[int, ...]
    local_variables: tuple[int, ...]
    tiles: dict[int, tuple[int, ...]]
    scripts: tuple[MapScript, ...]
    declared_object_count: int
    elevation_object_counts: tuple[int, int, int]
    objects: tuple[MapObject, ...]
    referenced_prototypes: tuple[Prototype, ...]
    prototype_root: Path
    prototype_lists: dict[int, ListDocument]
    scripts_list: ListDocument | None


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise MapFormatError(f"MAP is truncated while reading {field} at byte {self.offset}")
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk

    def i32(self, field: str) -> int:
        return struct.unpack(">i", self.take(4, field))[0]

    def i32s(self, count: int, field: str) -> tuple[int, ...]:
        return tuple(self.i32(f"{field}[{index}]") for index in range(count))


def _script_filename(script_index: int, scripts_list: ListDocument | None) -> str | None:
    if script_index < 0 or scripts_list is None or script_index >= len(scripts_list.entries):
        return None
    filename = scripts_list.entries[script_index].filename
    return filename or None


def _read_script_record(
    reader: _Reader,
    script_type: int,
    scripts_list: ListDocument | None,
    label: str,
) -> MapScript:
    script_id = reader.i32(f"{label}.script_id")
    next_script_id = reader.i32(f"{label}.next_script_id")
    payload: dict[str, int] = {}
    serialized_type = (script_id & 0xFFFFFFFF) >> 24
    if serialized_type == 1:
        payload["built_tile"] = reader.i32(f"{label}.built_tile")
        payload["radius"] = reader.i32(f"{label}.radius")
    elif serialized_type == 2:
        payload["time"] = reader.i32(f"{label}.time")
    script_flags = reader.i32(f"{label}.flags")
    script_index = reader.i32(f"{label}.script_index")
    payload["program_pointer"] = reader.i32(f"{label}.program_pointer")
    object_id = reader.i32(f"{label}.object_id")
    local_offset = reader.i32(f"{label}.local_variable_offset")
    local_count = reader.i32(f"{label}.local_variable_count")
    for name in (
        "field_28",
        "action",
        "fixed_parameter",
        "action_being_used",
        "script_overrides",
        "field_48",
        "how_much",
        "run_info_flags",
    ):
        payload[name] = reader.i32(f"{label}.{name}")
    return MapScript(
        script_type=script_type,
        script_type_name=SCRIPT_TYPE_NAMES[script_type],
        script_id=script_id,
        next_script_id=next_script_id,
        script_flags=script_flags,
        script_index=script_index,
        script_filename=_script_filename(script_index, scripts_list),
        object_id=object_id,
        local_variable_offset=local_offset,
        local_variable_count=local_count,
        payload=payload,
    )


def _read_scripts(reader: _Reader, scripts_list: ListDocument | None) -> tuple[MapScript, ...]:
    scripts: list[MapScript] = []
    for script_type in range(len(SCRIPT_TYPE_NAMES)):
        declared_count = reader.i32(f"scripts.{SCRIPT_TYPE_NAMES[script_type]}.count")
        if declared_count < 0 or declared_count > 1_000_000:
            raise MapFormatError(f"invalid {SCRIPT_TYPE_NAMES[script_type]} script count: {declared_count}")
        extent_count = (declared_count + 15) // 16
        active_count = 0
        for extent_index in range(extent_count):
            extent_records = [
                _read_script_record(
                    reader,
                    script_type,
                    scripts_list,
                    f"scripts.{SCRIPT_TYPE_NAMES[script_type]}.extent[{extent_index}].record[{record_index}]",
                )
                for record_index in range(16)
            ]
            extent_length = reader.i32("script extent length")
            reader.i32("script extent next pointer")
            if extent_length < 0 or extent_length > 16:
                raise MapFormatError(f"invalid script extent length: {extent_length}")
            if extent_index + 1 < extent_count and extent_length != 16:
                raise MapFormatError("non-final script extent does not contain 16 records")
            active_records = extent_records[:extent_length]
            for record in active_records:
                serialized_type = (record.script_id & 0xFFFFFFFF) >> 24
                if serialized_type != script_type:
                    raise MapFormatError(
                        f"active {SCRIPT_TYPE_NAMES[script_type]} script has SID type {serialized_type}"
                    )
            scripts.extend(active_records)
            active_count += extent_length
        if active_count != declared_count:
            raise MapFormatError(
                f"{SCRIPT_TYPE_NAMES[script_type]} script count mismatch: declared {declared_count}, extents contain {active_count}"
            )
    return tuple(scripts)


def _read_object_update(reader: _Reader, prototype: Prototype, label: str) -> tuple[int, int, int, dict[str, Any]]:
    inventory_length = reader.i32(f"{label}.inventory_length")
    inventory_capacity = reader.i32(f"{label}.inventory_capacity")
    inventory_pointer = reader.i32(f"{label}.inventory_pointer")
    if inventory_length < 0 or inventory_capacity < 0 or inventory_length > inventory_capacity:
        raise MapFormatError(
            f"invalid inventory size at {label}: length={inventory_length}, capacity={inventory_capacity}"
        )
    if inventory_length > 100_000:
        raise MapFormatError(f"unreasonable inventory length at {label}: {inventory_length}")

    update: dict[str, Any] = {}
    if prototype.pid_type == 1:
        update["reaction_to_pc"] = reader.i32(f"{label}.reaction_to_pc")
        combat_names = (
            "damage_last_turn",
            "maneuver",
            "action_points",
            "results",
            "ai_packet",
            "team",
            "who_hit_me_cid",
        )
        update["combat"] = {name: reader.i32(f"{label}.{name}") for name in combat_names}
        update["hit_points"] = reader.i32(f"{label}.hit_points")
        update["radiation"] = reader.i32(f"{label}.radiation")
        update["poison"] = reader.i32(f"{label}.poison")
        return inventory_length, inventory_capacity, inventory_pointer, update

    update["flags"] = reader.i32(f"{label}.update_flags")
    if prototype.pid_type == 0:
        if prototype.subtype == 3:
            update["ammo_quantity"] = reader.i32(f"{label}.ammo_quantity")
            update["ammo_type_pid"] = reader.i32(f"{label}.ammo_type_pid")
        elif prototype.subtype in (4, 5, 6):
            key = {4: "ammo_quantity", 5: "charges", 6: "key_code"}[prototype.subtype]
            update[key] = reader.i32(f"{label}.{key}")
    elif prototype.pid_type == 2:
        if prototype.subtype == 0:
            update["open_flags"] = reader.i32(f"{label}.open_flags")
        elif prototype.subtype == 1:
            update["destination_map"] = reader.i32(f"{label}.destination_map")
            update["destination_built_tile"] = reader.i32(f"{label}.destination_built_tile")
        elif prototype.subtype == 2:
            update["elevator_type"] = reader.i32(f"{label}.elevator_type")
            update["elevator_level"] = reader.i32(f"{label}.elevator_level")
        elif prototype.subtype in (3, 4):
            update["destination_built_tile"] = reader.i32(f"{label}.destination_built_tile")
    elif prototype.pid_type == 5 and 0x05000010 <= (prototype.pid & 0xFFFFFFFF) <= 0x05000017:
        for name in ("destination_map", "destination_tile", "destination_elevation", "destination_rotation"):
            update[name] = reader.i32(f"{label}.{name}")
    return inventory_length, inventory_capacity, inventory_pointer, update


def _read_object(
    reader: _Reader,
    catalog: PrototypeCatalog,
    scripts_by_id: dict[int, MapScript],
    elevation_group: int,
    label: str,
    depth: int = 0,
) -> MapObject:
    if depth > 64:
        raise MapFormatError("object inventory nesting exceeds 64 levels")
    file_offset = reader.offset
    values = reader.i32s(18, f"{label}.base")
    (
        object_id,
        tile,
        x,
        y,
        screen_x,
        screen_y,
        frame,
        rotation,
        fid,
        flags,
        stored_elevation,
        pid,
        cid,
        light_distance,
        light_intensity,
        field_74,
        script_id,
        field_80,
    ) = values
    try:
        prototype, list_entry = catalog.resolve(pid)
    except (FileNotFoundError, ValueError) as exc:
        raise MapFormatError(f"cannot resolve {label} PID 0x{pid & 0xFFFFFFFF:08X}: {exc}") from exc
    inventory_length, inventory_capacity, inventory_pointer, update = _read_object_update(
        reader, prototype, label
    )
    inventory: list[InventoryEntry] = []
    for index in range(inventory_length):
        quantity = reader.i32(f"{label}.inventory[{index}].quantity")
        item = _read_object(
            reader,
            catalog,
            scripts_by_id,
            elevation_group,
            f"{label}.inventory[{index}].item",
            depth + 1,
        )
        inventory.append(InventoryEntry(quantity=quantity, item=item))
    linked_script = scripts_by_id.get(script_id)
    return MapObject(
        file_offset=file_offset,
        elevation_group=elevation_group,
        object_id=object_id,
        tile=tile,
        x=x,
        y=y,
        screen_x=screen_x,
        screen_y=screen_y,
        frame=frame,
        rotation=rotation,
        fid=fid,
        flags=flags,
        stored_elevation=stored_elevation,
        pid=pid,
        cid=cid,
        light_distance=light_distance,
        light_intensity=light_intensity,
        field_74=field_74,
        script_id=script_id,
        field_80=field_80,
        inventory_length=inventory_length,
        inventory_capacity=inventory_capacity,
        inventory_pointer=inventory_pointer,
        update_data=update,
        prototype=prototype,
        prototype_filename=list_entry.filename,
        script_filename=linked_script.script_filename if linked_script else None,
        inventory=tuple(inventory),
    )


def parse_map(
    data: bytes,
    prototype_catalog: PrototypeCatalog,
    *,
    source_path: Path | str = Path("<memory>.MAP"),
    scripts_list: ListDocument | None = None,
) -> MapDocument:
    reader = _Reader(data)
    version = reader.i32("header.version")
    name_bytes = reader.take(16, "header.name")
    name = name_bytes.split(b"\x00", 1)[0].decode("ascii", errors="strict")
    header_values = reader.i32s(10, "header")
    reserved = reader.i32s(44, "header.reserved")
    header = MapHeader(version, name, *header_values, reserved)
    if reader.offset != MAP_HEADER_SIZE:
        raise AssertionError("MAP header parser size mismatch")
    if version != MAP_VERSION:
        raise MapFormatError(f"unsupported MAP version {version}; expected {MAP_VERSION}")
    if not 0 <= header.entering_tile < 40_000:
        raise MapFormatError(f"invalid entering tile: {header.entering_tile}")
    if not 0 <= header.entering_elevation < ELEVATION_COUNT:
        raise MapFormatError(f"invalid entering elevation: {header.entering_elevation}")
    if not 0 <= header.entering_rotation < 6:
        raise MapFormatError(f"invalid entering rotation: {header.entering_rotation}")
    if header.global_variables_count < 0 or header.local_variables_count < 0:
        raise MapFormatError("negative MAP variable count")
    if header.global_variables_count > 1_000_000 or header.local_variables_count > 1_000_000:
        raise MapFormatError("unreasonable MAP variable count")

    global_variables = reader.i32s(header.global_variables_count, "global_variables")
    local_variables = reader.i32s(header.local_variables_count, "local_variables")
    tiles: dict[int, tuple[int, ...]] = {}
    for elevation, empty_flag in enumerate(ELEVATION_EMPTY_FLAGS):
        if header.flags & empty_flag == 0:
            tiles[elevation] = reader.i32s(SQUARE_GRID_SIZE, f"tiles[{elevation}]")

    scripts = _read_scripts(reader, scripts_list)
    scripts_by_id = {script.script_id: script for script in scripts}
    if len(scripts_by_id) != len(scripts):
        raise MapFormatError("duplicate active script ID")

    declared_object_count = reader.i32("objects.count")
    if declared_object_count < 0 or declared_object_count > 1_000_000:
        raise MapFormatError(f"invalid object count: {declared_object_count}")
    objects: list[MapObject] = []
    elevation_counts: list[int] = []
    for elevation in range(ELEVATION_COUNT):
        count = reader.i32(f"objects.elevation[{elevation}].count")
        if count < 0 or count > declared_object_count:
            raise MapFormatError(f"invalid elevation {elevation} object count: {count}")
        elevation_counts.append(count)
        for index in range(count):
            objects.append(
                _read_object(
                    reader,
                    prototype_catalog,
                    scripts_by_id,
                    elevation,
                    f"objects.elevation[{elevation}][{index}]",
                )
            )
    if sum(elevation_counts) != declared_object_count:
        raise MapFormatError(
            f"object count mismatch: declared {declared_object_count}, elevations contain {sum(elevation_counts)}"
        )
    if reader.offset != len(data):
        raise MapFormatError(f"MAP has {len(data) - reader.offset} trailing byte(s)")

    return MapDocument(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        header=header,
        global_variables=global_variables,
        local_variables=local_variables,
        tiles=tiles,
        scripts=scripts,
        declared_object_count=declared_object_count,
        elevation_object_counts=(elevation_counts[0], elevation_counts[1], elevation_counts[2]),
        objects=tuple(objects),
        referenced_prototypes=prototype_catalog.loaded_prototypes,
        prototype_root=prototype_catalog.root,
        prototype_lists=dict(prototype_catalog.lists),
        scripts_list=scripts_list,
    )


def load_map(
    path: Path | str,
    prototype_root: Path | str,
    *,
    scripts_list_path: Path | str | None = None,
) -> MapDocument:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MapFormatError(f"MAP source changed while reading: {source}")
    catalog = PrototypeCatalog(prototype_root)
    scripts_list = load_lst(scripts_list_path) if scripts_list_path is not None else None
    return parse_map(data, catalog, source_path=source, scripts_list=scripts_list)


def _walk_objects(objects: tuple[MapObject, ...], prefix: str = "") -> list[tuple[str, MapObject, int | None]]:
    result: list[tuple[str, MapObject, int | None]] = []

    def visit(obj: MapObject, path: str, quantity: int | None) -> None:
        result.append((path, obj, quantity))
        for inventory_index, entry in enumerate(obj.inventory):
            visit(entry.item, f"{path}/inventory/{inventory_index}", entry.quantity)

    for index, obj in enumerate(objects):
        visit(obj, f"{prefix}{index}", None)
    return result


def map_summary(document: MapDocument) -> dict[str, Any]:
    flattened = _walk_objects(document.objects)
    return {
        "name": document.header.name,
        "version": document.header.version,
        "present_elevations": sorted(document.tiles),
        "global_variables": len(document.global_variables),
        "local_variables": len(document.local_variables),
        "scripts": len(document.scripts),
        "top_level_objects": len(document.objects),
        "inventory_objects": len(flattened) - len(document.objects),
        "referenced_prototypes": len(document.referenced_prototypes),
    }


def _prototype_payload(prototype: Prototype) -> dict[str, Any]:
    return {
        "source": {
            "path": str(prototype.source_path),
            "size": prototype.source_size,
            "sha256": prototype.source_sha256,
        },
        "pid": prototype.pid,
        "pid_hex": f"0x{prototype.pid & 0xFFFFFFFF:08X}",
        "pid_type": prototype.pid_type,
        "type": prototype.type_name,
        "list_index": prototype.list_index,
        "message_id": prototype.message_id,
        "fid": prototype.fid,
        "subtype": prototype.subtype,
        "subtype_name": prototype.subtype_name,
        "fields": prototype.fields,
    }


def _object_payload(obj: MapObject) -> dict[str, Any]:
    return {
        "file_offset": obj.file_offset,
        "elevation_group": obj.elevation_group,
        "object_id": obj.object_id,
        "tile": obj.tile,
        "tile_x": obj.tile % 200 if obj.tile >= 0 else None,
        "tile_y": obj.tile // 200 if obj.tile >= 0 else None,
        "x": obj.x,
        "y": obj.y,
        "screen_x": obj.screen_x,
        "screen_y": obj.screen_y,
        "frame": obj.frame,
        "rotation": obj.rotation,
        "fid": obj.fid,
        "fid_hex": f"0x{obj.fid & 0xFFFFFFFF:08X}",
        "flags": obj.flags,
        "stored_elevation": obj.stored_elevation,
        "pid": obj.pid,
        "pid_hex": f"0x{obj.pid & 0xFFFFFFFF:08X}",
        "cid": obj.cid,
        "light_distance": obj.light_distance,
        "light_intensity": obj.light_intensity,
        "field_74": obj.field_74,
        "script_id": obj.script_id,
        "script_filename": obj.script_filename,
        "field_80": obj.field_80,
        "prototype": {
            "type": obj.prototype.type_name,
            "list_index": obj.prototype.list_index,
            "filename": obj.prototype_filename,
            "subtype": obj.prototype.subtype,
            "subtype_name": obj.prototype.subtype_name,
        },
        "inventory_length": obj.inventory_length,
        "inventory_capacity": obj.inventory_capacity,
        "inventory_pointer": obj.inventory_pointer,
        "update_data": obj.update_data,
        "inventory": [
            {"quantity": entry.quantity, "item": _object_payload(entry.item)} for entry in obj.inventory
        ],
    }


def _json_payload(document: MapDocument) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "Fallout MAP/PRO/LST",
        "generator": {"name": "fallout1resource", "version": __version__},
        "source": {
            "path": str(document.source_path),
            "size": document.source_size,
            "sha256": document.source_sha256,
        },
        "summary": map_summary(document),
        "header": {
            "version": document.header.version,
            "name": document.header.name,
            "entering_tile": document.header.entering_tile,
            "entering_elevation": document.header.entering_elevation,
            "entering_rotation": document.header.entering_rotation,
            "local_variables_count": document.header.local_variables_count,
            "script_index": document.header.script_index,
            "flags": document.header.flags,
            "darkness": document.header.darkness,
            "global_variables_count": document.header.global_variables_count,
            "map_number": document.header.map_number,
            "last_visit_time": document.header.last_visit_time,
            "reserved": list(document.header.reserved),
        },
        "global_variables": list(document.global_variables),
        "local_variables": list(document.local_variables),
        "tiles": [
            {
                "elevation": elevation,
                "width": 100,
                "height": 100,
                "packed": list(values),
                "floor_ids": [value & 0xFFF for value in values],
                "floor_flags": [(value >> 12) & 0xF for value in values],
                "roof_ids": [(value >> 16) & 0xFFF for value in values],
                "roof_flags": [(value >> 28) & 0xF for value in values],
            }
            for elevation, values in sorted(document.tiles.items())
        ],
        "scripts": [
            {
                "type": script.script_type,
                "type_name": script.script_type_name,
                "script_id": script.script_id,
                "next_script_id": script.next_script_id,
                "flags": script.script_flags,
                "script_index": script.script_index,
                "script_filename": script.script_filename,
                "object_id": script.object_id,
                "local_variable_offset": script.local_variable_offset,
                "local_variable_count": script.local_variable_count,
                "payload": script.payload,
            }
            for script in document.scripts
        ],
        "objects": {
            "declared_count": document.declared_object_count,
            "elevation_counts": list(document.elevation_object_counts),
            "entries": [_object_payload(obj) for obj in document.objects],
        },
        "prototype_lists": [
            {
                "pid_type": pid_type,
                "source": str(lst.source_path),
                "sha256": lst.source_sha256,
                "entries": len(lst.entries),
                "index_semantics": "one-based; PID low 24 bits",
                "ordered_entries": [
                    {
                        "index": entry.index,
                        "raw": entry.raw,
                        "filename": entry.filename,
                        "annotation": entry.annotation,
                    }
                    for entry in lst.entries
                ],
            }
            for pid_type, lst in sorted(document.prototype_lists.items())
        ],
        "scripts_list": None
        if document.scripts_list is None
        else {
            "source": str(document.scripts_list.source_path),
            "sha256": document.scripts_list.source_sha256,
            "entries": len(document.scripts_list.entries),
            "index_semantics": "zero-based script_index",
            "ordered_entries": [
                {
                    "index": entry.index,
                    "script_index": entry.index - 1,
                    "raw": entry.raw,
                    "filename": entry.filename,
                    "annotation": entry.annotation,
                }
                for entry in document.scripts_list.entries
            ],
        },
        "referenced_prototypes": [_prototype_payload(proto) for proto in document.referenced_prototypes],
    }


def _objects_csv(document: MapDocument) -> bytes:
    stream = io.StringIO(newline="")
    fields = (
        "path",
        "inventory_quantity",
        "file_offset",
        "elevation_group",
        "object_id",
        "tile",
        "tile_x",
        "tile_y",
        "rotation",
        "pid",
        "pid_hex",
        "prototype_type",
        "prototype_subtype",
        "prototype_filename",
        "script_id",
        "script_filename",
        "inventory_length",
    )
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for path, obj, quantity in _walk_objects(document.objects):
        writer.writerow(
            {
                "path": path,
                "inventory_quantity": quantity,
                "file_offset": obj.file_offset,
                "elevation_group": obj.elevation_group,
                "object_id": obj.object_id,
                "tile": obj.tile,
                "tile_x": obj.tile % 200 if obj.tile >= 0 else None,
                "tile_y": obj.tile // 200 if obj.tile >= 0 else None,
                "rotation": obj.rotation,
                "pid": obj.pid,
                "pid_hex": f"0x{obj.pid & 0xFFFFFFFF:08X}",
                "prototype_type": obj.prototype.type_name,
                "prototype_subtype": obj.prototype.subtype_name,
                "prototype_filename": obj.prototype_filename,
                "script_id": obj.script_id,
                "script_filename": obj.script_filename,
                "inventory_length": obj.inventory_length,
            }
        )
    return codecs.BOM_UTF8 + stream.getvalue().encode("utf-8")


def map_output_paths(workspace: Path | str, output: Path | str) -> tuple[Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("MAP output must use a .json filename")
    return json_path, json_path.with_suffix(".objects.csv"), json_path.with_suffix(".json.sha256")


def write_map_export(
    document: MapDocument,
    workspace: Path | str,
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    json_path, csv_path, hash_path = map_output_paths(workspace, output)
    targets = (json_path, csv_path, hash_path)
    source_paths = {document.source_path}
    source_paths.update(lst.source_path for lst in document.prototype_lists.values())
    if document.scripts_list is not None:
        source_paths.add(document.scripts_list.source_path)
    source_paths.update(proto.source_path for proto in document.referenced_prototypes)
    collisions = source_paths.intersection(targets)
    if collisions:
        raise ValueError(f"output would replace a source file: {next(iter(collisions))}")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")
    json_bytes = (json.dumps(_json_payload(document), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    csv_bytes = _objects_csv(document)
    checksum = hashlib.sha256(json_bytes).hexdigest().upper()
    hash_bytes = f"{checksum}  {json_path.name}\n".encode("ascii")
    for path, content in zip(targets, (json_bytes, csv_bytes, hash_bytes), strict=True):
        write_file_atomic(path, content, overwrite=overwrite)
    return targets
