"""Minimal, read-only Fallout 1 DAT1 directory parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, Path
from typing import BinaryIO


COMPRESSION_NAMES = {
    0x10: "lzss-single-legacy",
    0x20: "none",
    0x40: "lzss",
}
MAX_DIRECTORIES = 10_000
MAX_FILES_PER_DIRECTORY = 1_000_000


class Dat1FormatError(ValueError):
    """Raised when a file cannot be validated as a DAT1 archive."""


@dataclass(frozen=True, slots=True)
class Dat1Entry:
    directory: str
    name: str
    internal_path: str
    compression_mode: int
    offset: int
    size: int
    packed_size: int
    stored_size: int
    path_is_safe: bool
    path_issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Dat1Archive:
    path: Path
    directory_count: int
    root_header: tuple[int, int, int]
    metadata_size: int
    entries: tuple[Dat1Entry, ...]


def _read_exact(stream: BinaryIO, size: int, label: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise Dat1FormatError(f"truncated DAT1 while reading {label}")
    return data


def _read_u32_be(stream: BinaryIO, label: str) -> int:
    return int.from_bytes(_read_exact(stream, 4, label), "big", signed=False)


def _read_string(stream: BinaryIO, label: str) -> str:
    length = _read_exact(stream, 1, f"{label} length")[0]
    raw = _read_exact(stream, length, label)
    return raw.decode("latin-1")


def inspect_internal_path(directory: str, name: str) -> tuple[str, tuple[str, ...]]:
    normalized_directory = directory.replace("\\", "/")
    normalized_name = name.replace("\\", "/")
    if normalized_directory in ("", "."):
        raw = normalized_name
    else:
        raw = f"{normalized_directory}/{normalized_name}"
    issues: list[str] = []
    if raw.startswith("/"):
        issues.append("absolute path")
    if ":" in raw:
        issues.append("drive or URI separator")
    if "/" in normalized_name:
        issues.append("separator in file name")
    parts = PurePosixPath(raw).parts
    if any(part == ".." for part in parts):
        issues.append("parent traversal")
    if not raw or any(part in ("", ".") for part in raw.split("/")):
        issues.append("empty or current-directory segment")
    reserved_names = {"CON", "PRN", "AUX", "NUL"}
    reserved_names.update(f"COM{index}" for index in range(1, 10))
    reserved_names.update(f"LPT{index}" for index in range(1, 10))
    for part in parts:
        if any(ord(character) < 32 for character in part):
            issues.append("control character")
        if part.rstrip(" .") != part:
            issues.append("trailing dot or space")
        if part.split(".", 1)[0].upper() in reserved_names:
            issues.append("reserved Windows name")
    normalized = "/".join(part for part in parts if part not in ("/", "", "."))
    return normalized, tuple(dict.fromkeys(issues))


def parse_dat1(path: Path | str) -> Dat1Archive:
    archive_path = Path(path)
    file_size = archive_path.stat().st_size
    with archive_path.open("rb") as stream:
        directory_count = _read_u32_be(stream, "directory count")
        if not 1 <= directory_count <= MAX_DIRECTORIES:
            raise Dat1FormatError(f"invalid DAT1 directory count: {directory_count}")

        root_header = tuple(_read_u32_be(stream, f"root header {index}") for index in range(3))
        if root_header[0] < directory_count:
            raise Dat1FormatError("DAT1 root capacity is smaller than its directory count")
        if root_header[1] != 0:
            raise Dat1FormatError("DAT1 root entry size must be zero")

        directories = [_read_string(stream, f"directory {index}") for index in range(directory_count)]
        entries: list[Dat1Entry] = []

        for directory_index, directory in enumerate(directories):
            file_count = _read_u32_be(stream, f"file count for directory {directory_index}")
            if file_count > MAX_FILES_PER_DIRECTORY:
                raise Dat1FormatError(f"unreasonable file count in directory {directory!r}: {file_count}")
            directory_header = tuple(
                _read_u32_be(stream, f"directory header {directory_index}:{field}")
                for field in range(3)
            )
            if directory_header[0] < file_count:
                raise Dat1FormatError(f"capacity is smaller than file count in directory {directory!r}")
            if directory_header[1] != 16:
                raise Dat1FormatError(f"unexpected DAT1 file entry size in directory {directory!r}")

            for file_index in range(file_count):
                name = _read_string(stream, f"file name {directory_index}:{file_index}")
                compression_mode = _read_u32_be(stream, "compression mode")
                if compression_mode not in COMPRESSION_NAMES:
                    raise Dat1FormatError(f"unknown DAT1 compression mode: 0x{compression_mode:08X}")
                offset = _read_u32_be(stream, "file offset")
                size = _read_u32_be(stream, "file size")
                packed_size = _read_u32_be(stream, "packed file size")
                stored_size = size if compression_mode == 0x20 and packed_size == 0 else packed_size
                if offset > file_size or stored_size > file_size - offset:
                    raise Dat1FormatError(f"file data is outside archive bounds: {directory}/{name}")
                internal_path, path_issues = inspect_internal_path(directory, name)
                entries.append(
                    Dat1Entry(
                        directory=directory,
                        name=name,
                        internal_path=internal_path,
                        compression_mode=compression_mode,
                        offset=offset,
                        size=size,
                        packed_size=packed_size,
                        stored_size=stored_size,
                        path_is_safe=not path_issues,
                        path_issues=path_issues,
                    )
                )

        metadata_size = stream.tell()

    return Dat1Archive(
        path=archive_path,
        directory_count=directory_count,
        root_header=root_header,
        metadata_size=metadata_size,
        entries=tuple(entries),
    )
