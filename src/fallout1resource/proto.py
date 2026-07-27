"""Parse Fallout prototype lists and PRO records without modifying sources."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PID_TYPE_NAMES = {
    0: "item",
    1: "critter",
    2: "scenery",
    3: "wall",
    4: "tile",
    5: "misc",
}
PID_DIRECTORIES = {
    0: "ITEMS",
    1: "CRITTERS",
    2: "SCENERY",
    3: "WALLS",
    4: "TILES",
    5: "MISC",
}
ITEM_TYPE_NAMES = {
    0: "armor",
    1: "container",
    2: "drug",
    3: "weapon",
    4: "ammo",
    5: "misc",
    6: "key",
}
SCENERY_TYPE_NAMES = {
    0: "door",
    1: "stairs",
    2: "elevator",
    3: "ladder_up",
    4: "ladder_down",
    5: "generic",
}


class ProtoFormatError(ValueError):
    """Raised when an LST or PRO file is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class ListEntry:
    index: int
    raw: str
    filename: str
    annotation: str


@dataclass(frozen=True, slots=True)
class ListDocument:
    source_path: Path
    source_size: int
    source_sha256: str
    encoding: str
    newline_style: str
    entries: tuple[ListEntry, ...]


@dataclass(frozen=True, slots=True)
class Prototype:
    source_path: Path
    source_size: int
    source_sha256: str
    pid: int
    pid_type: int
    type_name: str
    list_index: int
    message_id: int
    fid: int
    subtype: int | None
    subtype_name: str | None
    fields: dict[str, Any]


class _Reader:
    def __init__(self, data: bytes, label: str) -> None:
        self.data = data
        self.label = label
        self.offset = 0

    def _take(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ProtoFormatError(
                f"{self.label} is truncated while reading {field} at byte {self.offset}"
            )
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk

    def i32(self, field: str) -> int:
        return struct.unpack(">i", self._take(4, field))[0]

    def i32s(self, count: int, field: str) -> list[int]:
        return [self.i32(f"{field}[{index}]") for index in range(count)]

    def u8(self, field: str) -> int:
        return self._take(1, field)[0]


def _newline_style(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    kinds = [name for name, count in (("CRLF", crlf), ("LF", lf), ("CR", cr)) if count]
    return kinds[0] if len(kinds) == 1 else "mixed" if kinds else "none"


def parse_lst(data: bytes, source_path: Path | str = Path("<memory>.LST")) -> ListDocument:
    """Parse physical LST lines while preserving their one-based positions."""
    try:
        text = data.decode("ascii")
        encoding = "ascii"
    except UnicodeDecodeError:
        text = data.decode("cp1252")
        encoding = "cp1252"

    entries: list[ListEntry] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        filename, separator, annotation = raw.partition(" ")
        entries.append(
            ListEntry(
                index=index,
                raw=raw,
                filename=filename.rstrip("\r"),
                annotation=annotation.lstrip() if separator else "",
            )
        )
    return ListDocument(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        encoding=encoding,
        newline_style=_newline_style(data),
        entries=tuple(entries),
    )


def load_lst(path: Path | str) -> ListDocument:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ProtoFormatError(f"LST source changed while reading: {source}")
    return parse_lst(data, source)


def _read_item_data(reader: _Reader, subtype: int) -> dict[str, Any]:
    if subtype == 0:
        return {
            "armor_class": reader.i32("armor_class"),
            "damage_resistance": reader.i32s(7, "damage_resistance"),
            "damage_threshold": reader.i32s(7, "damage_threshold"),
            "perk": reader.i32("perk"),
            "male_fid": reader.i32("male_fid"),
            "female_fid": reader.i32("female_fid"),
        }
    if subtype == 1:
        return {"max_size": reader.i32("max_size"), "open_flags": reader.i32("open_flags")}
    if subtype == 2:
        return {
            "stats": reader.i32s(3, "stats"),
            "amount": reader.i32s(3, "amount"),
            "duration_1": reader.i32("duration_1"),
            "amount_1": reader.i32s(3, "amount_1"),
            "duration_2": reader.i32("duration_2"),
            "amount_2": reader.i32s(3, "amount_2"),
            "addiction_chance": reader.i32("addiction_chance"),
            "withdrawal_effect": reader.i32("withdrawal_effect"),
            "withdrawal_onset": reader.i32("withdrawal_onset"),
        }
    if subtype == 3:
        names = (
            "animation_code",
            "min_damage",
            "max_damage",
            "damage_type",
            "max_range_1",
            "max_range_2",
            "projectile_pid",
            "min_strength",
            "action_point_cost_1",
            "action_point_cost_2",
            "critical_failure_type",
            "perk",
            "rounds",
            "caliber",
            "ammo_type_pid",
            "ammo_capacity",
        )
        result = {name: reader.i32(name) for name in names}
        result["sound_code"] = reader.u8("sound_code")
        return result
    if subtype == 4:
        names = (
            "caliber",
            "quantity",
            "armor_class_modifier",
            "damage_resistance_modifier",
            "damage_multiplier",
            "damage_divisor",
        )
        return {name: reader.i32(name) for name in names}
    if subtype == 5:
        return {
            "power_type_pid": reader.i32("power_type_pid"),
            "power_type": reader.i32("power_type"),
            "charges": reader.i32("charges"),
        }
    if subtype == 6:
        return {"key_code": reader.i32("key_code")}
    raise ProtoFormatError(f"unsupported item subtype {subtype}")


def _read_scenery_data(reader: _Reader, subtype: int) -> dict[str, Any]:
    if subtype == 0:
        return {"open_flags": reader.i32("open_flags"), "key_code": reader.i32("key_code")}
    if subtype == 1:
        return {"lower_tile": reader.i32("lower_tile"), "upper_tile": reader.i32("upper_tile")}
    if subtype == 2:
        return {"elevator_type": reader.i32("elevator_type"), "level": reader.i32("level")}
    if subtype in (3, 4):
        return {"destination_built_tile": reader.i32("destination_built_tile")}
    if subtype == 5:
        return {"generic_data": reader.i32("generic_data")}
    raise ProtoFormatError(f"unsupported scenery subtype {subtype}")


def parse_pro(data: bytes, source_path: Path | str = Path("<memory>.PRO")) -> Prototype:
    reader = _Reader(data, "PRO")
    pid = reader.i32("pid")
    message_id = reader.i32("message_id")
    fid = reader.i32("fid")
    pid_unsigned = pid & 0xFFFFFFFF
    pid_type = pid_unsigned >> 24
    list_index = pid_unsigned & 0xFFFFFF
    if pid_type not in PID_TYPE_NAMES:
        raise ProtoFormatError(f"unsupported PID type {pid_type} in 0x{pid_unsigned:08X}")
    if list_index == 0:
        raise ProtoFormatError(f"prototype PID has zero LST index: 0x{pid_unsigned:08X}")

    subtype: int | None = None
    subtype_name: str | None = None
    fields: dict[str, Any] = {}
    if pid_type == 0:
        common_names = (
            "light_distance",
            "light_intensity",
            "flags",
            "extended_flags",
            "script_id",
        )
        fields.update({name: reader.i32(name) for name in common_names})
        subtype = reader.i32("item_type")
        subtype_name = ITEM_TYPE_NAMES.get(subtype)
        if subtype_name is None:
            raise ProtoFormatError(f"unsupported item subtype {subtype}")
        for name in ("material", "size", "weight", "cost", "inventory_fid"):
            fields[name] = reader.i32(name)
        fields["field_80"] = reader.u8("field_80")
        fields["data"] = _read_item_data(reader, subtype)
    elif pid_type == 1:
        names = (
            "light_distance",
            "light_intensity",
            "flags",
            "extended_flags",
            "script_id",
            "head_fid",
            "ai_packet",
            "team",
        )
        fields.update({name: reader.i32(name) for name in names})
        fields["critter_flags"] = reader.i32("critter_flags")
        fields["base_stats"] = reader.i32s(35, "base_stats")
        fields["bonus_stats"] = reader.i32s(35, "bonus_stats")
        fields["skills"] = reader.i32s(18, "skills")
        fields["body_type"] = reader.i32("body_type")
        fields["experience"] = reader.i32("experience")
        fields["kill_type"] = reader.i32("kill_type")
    elif pid_type == 2:
        common_names = (
            "light_distance",
            "light_intensity",
            "flags",
            "extended_flags",
            "script_id",
        )
        fields.update({name: reader.i32(name) for name in common_names})
        subtype = reader.i32("scenery_type")
        subtype_name = SCENERY_TYPE_NAMES.get(subtype)
        if subtype_name is None:
            raise ProtoFormatError(f"unsupported scenery subtype {subtype}")
        fields["material"] = reader.i32("material")
        fields["field_34"] = reader.u8("field_34")
        fields["data"] = _read_scenery_data(reader, subtype)
    elif pid_type == 3:
        for name in ("light_distance", "light_intensity", "flags", "extended_flags", "script_id", "material"):
            fields[name] = reader.i32(name)
    elif pid_type == 4:
        for name in ("flags", "extended_flags", "script_id", "material"):
            fields[name] = reader.i32(name)
    else:
        for name in ("light_distance", "light_intensity", "flags", "extended_flags"):
            fields[name] = reader.i32(name)

    if reader.offset != len(data):
        raise ProtoFormatError(f"PRO has {len(data) - reader.offset} trailing byte(s)")
    return Prototype(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        pid=pid,
        pid_type=pid_type,
        type_name=PID_TYPE_NAMES[pid_type],
        list_index=list_index,
        message_id=message_id,
        fid=fid,
        subtype=subtype,
        subtype_name=subtype_name,
        fields=fields,
    )


def load_pro(path: Path | str) -> Prototype:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ProtoFormatError(f"PRO source changed while reading: {source}")
    return parse_pro(data, source)


def _find_case_insensitive(directory: Path, filename: str) -> Path:
    direct = directory / filename
    if direct.is_file():
        return direct
    matches = [path for path in directory.iterdir() if path.is_file() and path.name.casefold() == filename.casefold()]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one case-insensitive match for {filename} in {directory}, found {len(matches)}"
        )
    return matches[0]


class PrototypeCatalog:
    """Resolve map PIDs through the six prototype LST files."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.lists: dict[int, ListDocument] = {}
        self._cache: dict[int, Prototype] = {}
        for pid_type, directory_name in PID_DIRECTORIES.items():
            list_path = self.root / directory_name / f"{directory_name}.LST"
            if not list_path.is_file():
                raise FileNotFoundError(f"missing prototype list: {list_path}")
            self.lists[pid_type] = load_lst(list_path)

    def resolve(self, pid: int) -> tuple[Prototype, ListEntry]:
        pid_unsigned = pid & 0xFFFFFFFF
        pid_type = pid_unsigned >> 24
        list_index = pid_unsigned & 0xFFFFFF
        if pid_type not in self.lists:
            raise ProtoFormatError(f"unsupported object PID type {pid_type}: 0x{pid_unsigned:08X}")
        entries = self.lists[pid_type].entries
        if list_index <= 0 or list_index > len(entries):
            raise ProtoFormatError(
                f"PID 0x{pid_unsigned:08X} references missing LST line {list_index}"
            )
        entry = entries[list_index - 1]
        if not entry.filename:
            raise ProtoFormatError(f"PID 0x{pid_unsigned:08X} references a blank LST entry")
        if pid_unsigned not in self._cache:
            directory = self.root / PID_DIRECTORIES[pid_type]
            prototype = load_pro(_find_case_insensitive(directory, entry.filename))
            if (prototype.pid & 0xFFFFFFFF) != pid_unsigned:
                raise ProtoFormatError(
                    f"PID/LST mismatch: requested 0x{pid_unsigned:08X}, {entry.filename} stores "
                    f"0x{prototype.pid & 0xFFFFFFFF:08X}"
                )
            self._cache[pid_unsigned] = prototype
        return self._cache[pid_unsigned], entry

    @property
    def loaded_prototypes(self) -> tuple[Prototype, ...]:
        return tuple(self._cache[key] for key in sorted(self._cache))
