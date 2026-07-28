"""Parse Fallout FRM/PAL files and export indexed PNG frames safely."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace
from .safe_io import write_file_atomic

FRM_VERSION = 4
FRM_VERSIONS = frozenset({3, FRM_VERSION})
FRM_HEADER_SIZE = 62
FRAME_HEADER_SIZE = 12
PALETTE_COLOR_BYTES = 256 * 3
ROTATION_COUNT = 6
FRM_CONVERTER_VERSION = 2


class FrmFormatError(ValueError):
    """Raised when an FRM or PAL file is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class PaletteColor:
    index: int
    raw_red: int
    raw_green: int
    raw_blue: int
    mapped: bool
    red: int
    green: int
    blue: int


@dataclass(frozen=True, slots=True)
class FalloutPalette:
    source_path: Path
    source_size: int
    source_sha256: str
    trailing_bytes: int
    colors: tuple[PaletteColor, ...]


@dataclass(frozen=True, slots=True)
class FrmFrame:
    index: int
    file_offset: int
    width: int
    height: int
    pixel_count: int
    x_offset: int
    y_offset: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class FrmSequence:
    index: int
    data_offset: int
    directions: tuple[int, ...]
    frames: tuple[FrmFrame, ...]


@dataclass(frozen=True, slots=True)
class FrmDirection:
    index: int
    x_offset: int
    y_offset: int
    data_offset: int
    sequence_index: int


@dataclass(frozen=True, slots=True)
class FrmDocument:
    source_path: Path
    source_size: int
    source_sha256: str
    version: int
    frames_per_second: int
    action_frame: int
    frame_count: int
    data_size: int
    stored_data_size: int
    split_direction: int | None
    directions: tuple[FrmDirection, ...]
    sequences: tuple[FrmSequence, ...]


def _stable_read(path: Path | str, label: str) -> tuple[Path, bytes]:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise FrmFormatError(f"{label} source changed while reading: {source}")
    return source, data


def _expand_six_bit(value: int) -> int:
    return (value << 2) | (value >> 4)


def parse_palette(data: bytes, source_path: Path | str = Path("<memory>.PAL")) -> FalloutPalette:
    """Parse the 256 RGB entries at the beginning of a Fallout color table."""
    if len(data) < PALETTE_COLOR_BYTES:
        raise FrmFormatError(
            f"PAL is truncated: expected at least {PALETTE_COLOR_BYTES} bytes, found {len(data)}"
        )

    colors: list[PaletteColor] = []
    for index in range(256):
        red, green, blue = data[index * 3 : index * 3 + 3]
        mapped = red <= 0x3F and green <= 0x3F and blue <= 0x3F
        effective = (red, green, blue) if mapped else (0, 0, 0)
        colors.append(
            PaletteColor(
                index=index,
                raw_red=red,
                raw_green=green,
                raw_blue=blue,
                mapped=mapped,
                red=_expand_six_bit(effective[0]),
                green=_expand_six_bit(effective[1]),
                blue=_expand_six_bit(effective[2]),
            )
        )

    return FalloutPalette(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        trailing_bytes=len(data) - PALETTE_COLOR_BYTES,
        colors=tuple(colors),
    )


def load_palette(path: Path | str) -> FalloutPalette:
    source, data = _stable_read(path, "PAL")
    return parse_palette(data, source)


def _parse_frame(data: bytes, cursor: int, limit: int, index: int) -> tuple[FrmFrame, int]:
    if cursor + FRAME_HEADER_SIZE > limit:
        raise FrmFormatError(f"frame {index} header extends beyond its direction sequence")
    width, height, pixel_count, x_offset, y_offset = struct.unpack_from(">hhi2h", data, cursor)
    if width <= 0 or height <= 0:
        raise FrmFormatError(f"frame {index} has invalid dimensions {width}x{height}")
    expected_pixels = width * height
    if pixel_count != expected_pixels:
        raise FrmFormatError(
            f"frame {index} pixel count mismatch: header says {pixel_count}, dimensions require {expected_pixels}"
        )
    pixel_start = cursor + FRAME_HEADER_SIZE
    pixel_end = pixel_start + pixel_count
    if pixel_end > limit:
        raise FrmFormatError(f"frame {index} pixels extend beyond its direction sequence")
    return (
        FrmFrame(
            index=index,
            file_offset=cursor,
            width=width,
            height=height,
            pixel_count=pixel_count,
            x_offset=x_offset,
            y_offset=y_offset,
            pixels=data[pixel_start:pixel_end],
        ),
        pixel_end,
    )


def parse_frm(data: bytes, source_path: Path | str = Path("<memory>.FRM")) -> FrmDocument:
    """Parse one Fallout 1 FRM without decoding or executing any game data."""
    if len(data) < FRM_HEADER_SIZE:
        raise FrmFormatError(
            f"FRM header is truncated: expected {FRM_HEADER_SIZE} bytes, found {len(data)}"
        )

    version, fps, action_frame, frame_count = struct.unpack_from(">ihhh", data, 0)
    x_offsets = struct.unpack_from(">6h", data, 10)
    y_offsets = struct.unpack_from(">6h", data, 22)
    data_offsets = struct.unpack_from(">6i", data, 34)
    (data_size,) = struct.unpack_from(">i", data, 58)
    suffix = Path(source_path).suffix.casefold()
    split_direction = int(suffix[-1]) if suffix in {f".fr{index}" for index in range(6)} else None
    stored_data_size = len(data) - FRM_HEADER_SIZE

    if version not in FRM_VERSIONS:
        expected = ", ".join(str(item) for item in sorted(FRM_VERSIONS))
        raise FrmFormatError(f"unsupported FRM version {version}; expected one of {expected}")
    if frame_count <= 0:
        raise FrmFormatError(f"invalid FRM frame count: {frame_count}")
    if action_frame < 0 or action_frame >= frame_count:
        raise FrmFormatError(
            f"action frame {action_frame} is outside frame range 0..{frame_count - 1}"
        )
    if data_size < 0:
        raise FrmFormatError(f"invalid FRM data size: {data_size}")
    if split_direction is None and FRM_HEADER_SIZE + data_size != len(data):
        raise FrmFormatError(
            f"FRM data size mismatch: header requires {FRM_HEADER_SIZE + data_size} bytes, found {len(data)}"
        )
    if split_direction is not None and stored_data_size > data_size:
        raise FrmFormatError(
            f"split FRM payload exceeds declared family data size: {stored_data_size} > {data_size}"
        )
    if split_direction is not None and any(data_offsets):
        raise FrmFormatError(
            f"split FRM must store one direction at data offset 0, found {data_offsets}"
        )
    if any(offset < 0 or offset >= data_size for offset in data_offsets):
        raise FrmFormatError(f"FRM direction data offset outside data area: {data_offsets}")
    if data_offsets[0] != 0:
        raise FrmFormatError(
            f"first FRM direction must begin at data offset 0, found {data_offsets[0]}"
        )

    if split_direction is not None:
        cursor = FRM_HEADER_SIZE
        frames: list[FrmFrame] = []
        for frame_index in range(frame_count):
            frame, cursor = _parse_frame(data, cursor, len(data), frame_index)
            frames.append(frame)
        if cursor != len(data):
            raise FrmFormatError(f"split direction has {len(data) - cursor} unclaimed byte(s)")
        sequences = (
            FrmSequence(
                index=0,
                data_offset=0,
                directions=(split_direction,),
                frames=tuple(frames),
            ),
        )
        directions = (
            FrmDirection(
                index=split_direction,
                x_offset=x_offsets[split_direction],
                y_offset=y_offsets[split_direction],
                data_offset=0,
                sequence_index=0,
            ),
        )
        return FrmDocument(
            source_path=Path(source_path).resolve(),
            source_size=len(data),
            source_sha256=hashlib.sha256(data).hexdigest().upper(),
            version=version,
            frames_per_second=fps,
            action_frame=action_frame,
            frame_count=frame_count,
            data_size=data_size,
            stored_data_size=stored_data_size,
            split_direction=split_direction,
            directions=directions,
            sequences=sequences,
        )

    unique_offsets: list[int] = []
    seen_offsets: set[int] = set()
    previous = -1
    for offset in data_offsets:
        if offset < previous:
            raise FrmFormatError(f"FRM direction data offsets are not ordered: {data_offsets}")
        if offset not in seen_offsets:
            unique_offsets.append(offset)
            seen_offsets.add(offset)
        previous = offset

    sequences: list[FrmSequence] = []
    offset_to_sequence: dict[int, int] = {}
    for sequence_index, relative_offset in enumerate(unique_offsets):
        next_offset = (
            unique_offsets[sequence_index + 1]
            if sequence_index + 1 < len(unique_offsets)
            else data_size
        )
        cursor = FRM_HEADER_SIZE + relative_offset
        limit = FRM_HEADER_SIZE + next_offset
        frames: list[FrmFrame] = []
        for frame_index in range(frame_count):
            frame, cursor = _parse_frame(data, cursor, limit, frame_index)
            frames.append(frame)
        if cursor != limit:
            raise FrmFormatError(
                f"direction sequence {sequence_index} has {limit - cursor} unclaimed byte(s)"
            )
        directions = tuple(
            index for index, offset in enumerate(data_offsets) if offset == relative_offset
        )
        sequences.append(
            FrmSequence(
                index=sequence_index,
                data_offset=relative_offset,
                directions=directions,
                frames=tuple(frames),
            )
        )
        offset_to_sequence[relative_offset] = sequence_index

    directions = tuple(
        FrmDirection(
            index=index,
            x_offset=x_offsets[index],
            y_offset=y_offsets[index],
            data_offset=data_offsets[index],
            sequence_index=offset_to_sequence[data_offsets[index]],
        )
        for index in range(ROTATION_COUNT)
    )
    return FrmDocument(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        version=version,
        frames_per_second=fps,
        action_frame=action_frame,
        frame_count=frame_count,
        data_size=data_size,
        stored_data_size=stored_data_size,
        split_direction=None,
        directions=directions,
        sequences=tuple(sequences),
    )


def load_frm(path: Path | str) -> FrmDocument:
    source, data = _stable_read(path, "FRM")
    return parse_frm(data, source)


def frm_summary(document: FrmDocument) -> dict[str, int]:
    return {
        "version": document.version,
        "frames_per_second": document.frames_per_second,
        "effective_frames_per_second": document.frames_per_second or 10,
        "action_frame": document.action_frame,
        "frames_per_direction": document.frame_count,
        "logical_directions": len(document.directions),
        "unique_direction_sequences": len(document.sequences),
        "exported_png_frames": len(document.sequences) * document.frame_count,
    }


def _png_chunk(name: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(name)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)


def encode_indexed_png(
    width: int,
    height: int,
    pixels: bytes,
    palette: FalloutPalette,
    *,
    transparent_index_zero: bool,
) -> bytes:
    """Encode palette indices as a standards-compliant PNG using only stdlib."""
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError("PNG dimensions do not match indexed pixel data")
    palette_bytes = bytes(
        channel for color in palette.colors for channel in (color.red, color.green, color.blue)
    )
    rows = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    chunks = [
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)),
        _png_chunk(b"PLTE", palette_bytes),
    ]
    if transparent_index_zero:
        chunks.append(_png_chunk(b"tRNS", b"\x00"))
    chunks.extend((_png_chunk(b"IDAT", zlib.compress(rows, level=9)), _png_chunk(b"IEND", b"")))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def frm_output_paths(
    workspace: Path | str,
    output: Path | str,
    document: FrmDocument,
) -> tuple[Path, Path, tuple[Path, ...], Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("FRM output must use a .json filename")
    palette_path = ensure_within_workspace(workspace, json_path.with_suffix(".palette.png"))
    frame_root = json_path.parent / f"{json_path.stem}.frames"
    frame_paths = tuple(
        ensure_within_workspace(
            workspace,
            frame_root / f"sequence-{sequence.index:02d}" / f"frame-{frame.index:03d}.png",
        )
        for sequence in document.sequences
        for frame in sequence.frames
    )
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    return json_path, palette_path, frame_paths, hash_path


def _palette_payload(palette: FalloutPalette) -> dict[str, Any]:
    return {
        "source": {
            "path": str(palette.source_path),
            "size": palette.source_size,
            "sha256": palette.source_sha256,
        },
        "color_bytes": PALETTE_COLOR_BYTES,
        "trailing_lookup_table_bytes": palette.trailing_bytes,
        "six_bit_expansion": "(value << 2) | (value >> 4)",
        "invalid_component_semantics": "a triplet containing a value above 63 maps to black, matching the game loader",
        "colors": [
            {
                "index": color.index,
                "raw_6_bit": [color.raw_red, color.raw_green, color.raw_blue],
                "mapped": color.mapped,
                "rgb_8_bit": [color.red, color.green, color.blue],
            }
            for color in palette.colors
        ],
    }


def write_frm_export(
    document: FrmDocument,
    palette: FalloutPalette,
    workspace: Path | str,
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, tuple[Path, ...], Path]:
    json_path, palette_path, frame_paths, hash_path = frm_output_paths(workspace, output, document)
    targets = (json_path, palette_path, *frame_paths, hash_path)
    source_paths = {document.source_path, palette.source_path}
    collisions = source_paths.intersection(targets)
    if collisions:
        raise ValueError(f"output would replace a source file: {next(iter(collisions))}")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")

    palette_pixels = bytes(range(256))
    palette_png = encode_indexed_png(
        16,
        16,
        palette_pixels,
        palette,
        transparent_index_zero=False,
    )
    frame_exports: list[tuple[Path, bytes, FrmSequence, FrmFrame]] = []
    path_index = 0
    for sequence in document.sequences:
        for frame in sequence.frames:
            png = encode_indexed_png(
                frame.width,
                frame.height,
                frame.pixels,
                palette,
                transparent_index_zero=True,
            )
            frame_exports.append((frame_paths[path_index], png, sequence, frame))
            path_index += 1

    workspace_path = Path(workspace).resolve()
    derived_frames = [
        {
            "sequence_index": sequence.index,
            "directions": list(sequence.directions),
            "frame_index": frame.index,
            "path": path.relative_to(workspace_path).as_posix(),
            "size": len(png),
            "sha256": hashlib.sha256(png).hexdigest().upper(),
        }
        for path, png, sequence, frame in frame_exports
    ]
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Fallout FRM with PAL",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "frm",
            "component_version": FRM_CONVERTER_VERSION,
        },
        "source": {
            "path": str(document.source_path),
            "size": document.source_size,
            "sha256": document.source_sha256,
        },
        "summary": frm_summary(document),
        "header": {
            "version": document.version,
            "frames_per_second": document.frames_per_second,
            "effective_frames_per_second": document.frames_per_second or 10,
            "action_frame": document.action_frame,
            "frame_count": document.frame_count,
            "data_size": document.data_size,
            "stored_data_size": document.stored_data_size,
            "storage": "split_direction" if document.split_direction is not None else "combined",
            "split_direction": document.split_direction,
        },
        "directions": [
            {
                "index": direction.index,
                "x_offset": direction.x_offset,
                "y_offset": direction.y_offset,
                "data_offset": direction.data_offset,
                "sequence_index": direction.sequence_index,
            }
            for direction in document.directions
        ],
        "sequences": [
            {
                "index": sequence.index,
                "data_offset": sequence.data_offset,
                "directions": list(sequence.directions),
                "frames": [
                    {
                        "index": frame.index,
                        "file_offset": frame.file_offset,
                        "width": frame.width,
                        "height": frame.height,
                        "pixel_count": frame.pixel_count,
                        "x_offset": frame.x_offset,
                        "y_offset": frame.y_offset,
                    }
                    for frame in sequence.frames
                ],
            }
            for sequence in document.sequences
        ],
        "palette": _palette_payload(palette),
        "derived": {
            "palette_preview": {
                "path": palette_path.relative_to(workspace_path).as_posix(),
                "size": len(palette_png),
                "sha256": hashlib.sha256(palette_png).hexdigest().upper(),
            },
            "frames": derived_frames,
            "transparency": "palette index 0 is transparent in frame PNGs",
            "shared_directions": "one PNG sequence is written per unique FRM data offset",
        },
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {json_path.name}\n".encode(
        "ascii"
    )

    write_file_atomic(palette_path, palette_png, overwrite=overwrite)
    for path, png, _, _ in frame_exports:
        write_file_atomic(path, png, overwrite=overwrite)
    write_file_atomic(json_path, json_bytes, overwrite=overwrite)
    write_file_atomic(hash_path, hash_bytes, overwrite=overwrite)
    return json_path, palette_path, frame_paths, hash_path
