"""Inspect Interplay MVE containers and export auditable previews with FFmpeg."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
import subprocess
import tempfile
import wave
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, TypeVar

from . import __version__
from .inventory import ensure_within_workspace
from .safe_io import write_file_atomic

MVE_SIGNATURE = b"Interplay MVE File\x1a\x00"
MVE_CONVERTER_VERSION = 4
MVE_HEADER_SIZE = 26
MVE_HEADER_CONSTANTS = (26, 256, 0x1133)
MAX_CHUNK_SIZE = 0xFFFF
MAX_SEGMENTS = 2_000_000
T = TypeVar("T")

CHUNK_NAMES = {
    0: "init_audio",
    1: "audio_only",
    2: "init_video",
    3: "video",
    4: "shutdown",
    5: "end",
}

OPCODE_NAMES = {
    0x00: "end_of_stream",
    0x01: "end_of_chunk",
    0x02: "create_timer",
    0x03: "init_audio_buffers",
    0x04: "start_stop_audio",
    0x05: "init_video_buffers",
    0x06: "video_data_06",
    0x07: "send_buffer",
    0x08: "audio_frame",
    0x09: "silence_frame",
    0x0A: "init_video_mode",
    0x0B: "create_gradient",
    0x0C: "set_palette",
    0x0D: "set_palette_compressed",
    0x0E: "set_skip_map",
    0x0F: "set_decoding_map",
    0x10: "video_data_10",
    0x11: "video_data_11",
    0x12: "documented_unknown_12",
    0x13: "documented_unknown_13",
    0x14: "documented_unknown_14",
    0x15: "documented_unknown_15",
}


class MveFormatError(ValueError):
    """Raised when an MVE source or conversion result is invalid."""


@dataclass(frozen=True, slots=True)
class MveTiming:
    rate: int
    subdivision: int
    frame_duration_microseconds: int

    @property
    def frames_per_second(self) -> Fraction:
        return Fraction(1_000_000, self.frame_duration_microseconds)


@dataclass(frozen=True, slots=True)
class MveVideo:
    width: int
    height: int
    bits_per_pixel: int
    init_version: int


@dataclass(frozen=True, slots=True)
class MveAudio:
    channels: int
    bits_per_sample: int
    sample_rate: int
    compressed: bool
    codec: str
    init_version: int


@dataclass(frozen=True, slots=True)
class MveSegment:
    index: int
    chunk_index: int
    file_offset: int
    payload_offset: int
    payload_size: int
    opcode: int
    opcode_name: str
    version: int


@dataclass(frozen=True, slots=True)
class MveChunk:
    index: int
    file_offset: int
    payload_size: int
    chunk_type: int
    chunk_name: str
    first_segment_index: int
    segment_count: int


@dataclass(frozen=True, slots=True)
class MveDocument:
    source_path: Path
    source_size: int
    source_sha256: str
    chunks: tuple[MveChunk, ...]
    segments: tuple[MveSegment, ...]
    timing: MveTiming
    video: MveVideo
    audio: MveAudio | None
    frame_count: int
    display_count: int
    frame_display_indices: tuple[int, ...]
    video_data_count: int
    audio_frame_count: int
    silence_frame_count: int
    palette_update_count: int
    video_data_formats: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ExternalTool:
    ffmpeg_path: Path
    ffprobe_path: Path
    ffmpeg_sha256: str
    ffprobe_sha256: str
    version_line: str
    runtime_files: tuple[dict[str, Any], ...]
    runtime_manifest_sha256: str


def _stable_read(path: Path | str) -> tuple[Path, bytes]:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MveFormatError(f"MVE source changed while reading: {source}")
    return source, data


def _same_or_set(current: T | None, value: T, label: str) -> T:
    if current is not None and current != value:
        raise MveFormatError(f"conflicting {label} records")
    return value


def _parse_timing(payload: bytes, version: int) -> MveTiming:
    if version != 0 or len(payload) != 6:
        raise MveFormatError("invalid create-timer segment")
    rate, subdivision = struct.unpack("<IH", payload)
    duration = rate * subdivision
    if rate == 0 or subdivision == 0 or duration > 10_000_000:
        raise MveFormatError(f"unsafe MVE frame duration: {duration} microseconds")
    return MveTiming(rate, subdivision, duration)


def _parse_video(payload: bytes, version: int) -> MveVideo:
    if version > 2 or len(payload) < 4 or len(payload) > 8:
        raise MveFormatError("invalid init-video-buffers segment")
    if version == 2 and len(payload) < 8:
        raise MveFormatError("version 2 init-video-buffers segment is truncated")
    width_blocks, height_blocks = struct.unpack_from("<HH", payload)
    width = width_blocks * 8
    height = height_blocks * 8
    if width == 0 or height == 0 or width > 8192 or height > 8192:
        raise MveFormatError(f"unsafe MVE video dimensions: {width}x{height}")
    bits_per_pixel = 16 if version >= 2 and struct.unpack_from("<H", payload, 6)[0] else 8
    return MveVideo(width, height, bits_per_pixel, version)


def _parse_audio(payload: bytes, version: int) -> MveAudio:
    if version > 1 or len(payload) < 6 or len(payload) > 10:
        raise MveFormatError("invalid init-audio-buffers segment")
    flags, sample_rate = struct.unpack_from("<HH", payload, 2)
    channels = (flags & 1) + 1
    bits = (((flags >> 1) & 1) + 1) * 8
    compressed = version == 1 and bool(flags & 4)
    if sample_rate == 0 or sample_rate > 384_000:
        raise MveFormatError(f"unsafe MVE audio sample rate: {sample_rate}")
    codec = "interplay_dpcm" if compressed else ("pcm_s16le" if bits == 16 else "pcm_u8")
    return MveAudio(channels, bits, sample_rate, compressed, codec, version)


def _validate_palette(payload: bytes) -> None:
    if len(payload) < 4 or len(payload) > 0x304:
        raise MveFormatError("invalid MVE palette segment size")
    first, count = struct.unpack_from("<HH", payload)
    if count == 0 or first > 255 or first + count > 256 or 4 + count * 3 > len(payload):
        raise MveFormatError("MVE palette indexes or payload size are invalid")


def parse_mve(data: bytes, source_path: Path | str = Path("<memory>.MVE")) -> MveDocument:
    """Strictly parse an Interplay MVE container without decoding its pixels."""
    if len(data) < MVE_HEADER_SIZE:
        raise MveFormatError(
            f"MVE header is truncated: expected {MVE_HEADER_SIZE} bytes, found {len(data)}"
        )
    if data[:20] != MVE_SIGNATURE:
        raise MveFormatError("invalid Interplay MVE signature")
    constants = struct.unpack_from("<3H", data, 20)
    if constants != MVE_HEADER_CONSTANTS:
        raise MveFormatError(
            f"invalid MVE header constants {constants}; expected {MVE_HEADER_CONSTANTS}"
        )

    chunks: list[MveChunk] = []
    segments: list[MveSegment] = []
    timing: MveTiming | None = None
    video: MveVideo | None = None
    audio: MveAudio | None = None
    cursor = MVE_HEADER_SIZE
    while cursor < len(data):
        chunk_offset = cursor
        if cursor + 4 > len(data):
            raise MveFormatError(f"MVE chunk header is truncated at offset {cursor}")
        payload_size, chunk_type = struct.unpack_from("<HH", data, cursor)
        cursor += 4
        if payload_size > MAX_CHUNK_SIZE or chunk_type not in CHUNK_NAMES:
            raise MveFormatError(f"invalid MVE chunk type or size at offset {chunk_offset}")
        chunk_end = cursor + payload_size
        if chunk_end > len(data):
            raise MveFormatError(f"MVE chunk at offset {chunk_offset} extends beyond the source")
        first_segment = len(segments)
        chunk_index = len(chunks)
        while cursor < chunk_end:
            segment_offset = cursor
            if cursor + 4 > chunk_end:
                raise MveFormatError(f"MVE segment header is truncated at offset {cursor}")
            segment_size, opcode, version = struct.unpack_from("<HBB", data, cursor)
            cursor += 4
            payload_offset = cursor
            segment_end = cursor + segment_size
            if segment_end > chunk_end:
                raise MveFormatError(f"MVE segment at offset {segment_offset} exceeds its chunk")
            if len(segments) >= MAX_SEGMENTS:
                raise MveFormatError("MVE contains an unsafe number of segments")
            payload = data[payload_offset:segment_end]
            if opcode == 0x02:
                timing = _same_or_set(timing, _parse_timing(payload, version), "timer")
            elif opcode == 0x03:
                audio = _same_or_set(audio, _parse_audio(payload, version), "audio initialization")
            elif opcode == 0x05:
                video = _same_or_set(video, _parse_video(payload, version), "video initialization")
            elif opcode == 0x0C:
                _validate_palette(payload)
            segments.append(
                MveSegment(
                    index=len(segments),
                    chunk_index=chunk_index,
                    file_offset=segment_offset,
                    payload_offset=payload_offset,
                    payload_size=segment_size,
                    opcode=opcode,
                    opcode_name=OPCODE_NAMES.get(opcode, f"unknown_{opcode:02X}"),
                    version=version,
                )
            )
            cursor = segment_end
        chunks.append(
            MveChunk(
                index=chunk_index,
                file_offset=chunk_offset,
                payload_size=payload_size,
                chunk_type=chunk_type,
                chunk_name=CHUNK_NAMES[chunk_type],
                first_segment_index=first_segment,
                segment_count=len(segments) - first_segment,
            )
        )

    if not chunks or chunks[0].chunk_type != 2:
        raise MveFormatError("MVE must begin with an init-video chunk")
    if chunks[-1].chunk_type != 5:
        raise MveFormatError("MVE must end with an end chunk")
    if timing is None or video is None:
        raise MveFormatError("MVE is missing timer or video initialization")

    opcode_counts = Counter(segment.opcode for segment in segments)
    video_formats = tuple(sorted(opcode for opcode in (0x06, 0x10, 0x11) if opcode_counts[opcode]))
    display_count = opcode_counts[0x07]
    video_data_count = sum(opcode_counts[opcode] for opcode in video_formats)
    if display_count == 0 or video_data_count == 0:
        raise MveFormatError("MVE contains no displayable video frames")
    frame_display_indices: list[int] = []
    pending_video = False
    display_index = 0
    for segment in segments:
        if segment.opcode in (0x06, 0x10, 0x11):
            if pending_video:
                raise MveFormatError("multiple MVE video data segments precede one display event")
            pending_video = True
        elif segment.opcode == 0x07:
            if pending_video:
                frame_display_indices.append(display_index)
                pending_video = False
            display_index += 1
    if pending_video or len(frame_display_indices) != video_data_count:
        raise MveFormatError("MVE video data cannot be mapped to display events")
    return MveDocument(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        chunks=tuple(chunks),
        segments=tuple(segments),
        timing=timing,
        video=video,
        audio=audio,
        frame_count=video_data_count,
        display_count=display_count,
        frame_display_indices=tuple(frame_display_indices),
        video_data_count=video_data_count,
        audio_frame_count=opcode_counts[0x08],
        silence_frame_count=opcode_counts[0x09],
        palette_update_count=opcode_counts[0x0C] + opcode_counts[0x0D],
        video_data_formats=video_formats,
    )


def load_mve(path: Path | str) -> MveDocument:
    source, data = _stable_read(path)
    return parse_mve(data, source)


def mve_summary(document: MveDocument) -> dict[str, Any]:
    fps = document.timing.frames_per_second
    audio = document.audio
    return {
        "chunks": len(document.chunks),
        "segments": len(document.segments),
        "width": document.video.width,
        "height": document.video.height,
        "bits_per_pixel": document.video.bits_per_pixel,
        "frame_count": document.frame_count,
        "display_count": document.display_count,
        "repeated_display_count": document.display_count - document.frame_count,
        "trailing_repeated_display_count": (
            document.display_count - 1 - document.frame_display_indices[-1]
        ),
        "video_data_count": document.video_data_count,
        "video_data_formats": [f"0x{value:02X}" for value in document.video_data_formats],
        "frame_duration_microseconds": document.timing.frame_duration_microseconds,
        "frames_per_second": float(fps),
        "frames_per_second_fraction": f"{fps.numerator}/{fps.denominator}",
        "duration_seconds": document.frame_count
        * document.timing.frame_duration_microseconds
        / 1_000_000,
        "display_duration_seconds": document.display_count
        * document.timing.frame_duration_microseconds
        / 1_000_000,
        "has_audio": audio is not None,
        "audio_codec": audio.codec if audio else None,
        "audio_channels": audio.channels if audio else None,
        "audio_bits_per_sample": audio.bits_per_sample if audio else None,
        "audio_sample_rate": audio.sample_rate if audio else None,
        "audio_frame_segments": document.audio_frame_count,
        "silence_frame_segments": document.silence_frame_count,
        "palette_updates": document.palette_update_count,
    }


def mve_output_paths(
    workspace: Path | str,
    output: Path | str,
    document: MveDocument,
) -> tuple[Path, Path, Path, Path | None, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("MVE output must use a .json filename")
    csv_path = ensure_within_workspace(workspace, json_path.with_suffix(".segments.csv"))
    poster_path = ensure_within_workspace(workspace, json_path.with_suffix(".poster.png"))
    audio_path = (
        ensure_within_workspace(workspace, json_path.with_suffix(".audio.wav"))
        if document.audio
        else None
    )
    preview_path = ensure_within_workspace(workspace, json_path.with_suffix(".preview.mp4"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    return json_path, csv_path, poster_path, audio_path, preview_path, hash_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _run(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MveFormatError(f"external media tool timed out after {timeout} seconds") from exc
    if result.returncode != 0:
        detail = result.stderr.strip()[-2000:] or result.stdout.strip()[-2000:]
        raise MveFormatError(f"external media tool failed with code {result.returncode}: {detail}")
    return result


def inspect_ffmpeg(path: Path | str) -> ExternalTool:
    ffmpeg = Path(path).resolve()
    if not ffmpeg.is_file():
        raise MveFormatError(f"FFmpeg executable not found: {ffmpeg}")
    ffprobe = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.casefold() == ".exe" else "ffprobe")
    if not ffprobe.is_file():
        raise MveFormatError(f"matching ffprobe executable not found: {ffprobe}")
    version = _run([str(ffmpeg), "-version"], timeout=30).stdout.splitlines()
    if not version or not version[0].startswith("ffmpeg version "):
        raise MveFormatError("selected executable did not report an FFmpeg version")
    probe_version = _run([str(ffprobe), "-version"], timeout=30).stdout.splitlines()
    if not probe_version or not probe_version[0].startswith("ffprobe version "):
        raise MveFormatError("matching executable did not report an ffprobe version")

    runtime_files = []
    for runtime in sorted(ffmpeg.parent.glob("*.dll"), key=lambda item: item.name.casefold()):
        runtime_files.append(
            {"name": runtime.name, "size": runtime.stat().st_size, "sha256": _sha256_file(runtime)}
        )
    manifest_bytes = "".join(
        f"{item['sha256']}  {item['size']}  {item['name']}\n" for item in runtime_files
    ).encode("utf-8")
    return ExternalTool(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        ffmpeg_sha256=_sha256_file(ffmpeg),
        ffprobe_sha256=_sha256_file(ffprobe),
        version_line=version[0],
        runtime_files=tuple(runtime_files),
        runtime_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest().upper(),
    )


def _probe(tool: ExternalTool, path: Path) -> dict[str, Any]:
    result = _run(
        [
            str(tool.ffprobe_path),
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MveFormatError("ffprobe returned invalid JSON") from exc


def _stream(probe: dict[str, Any], stream_type: str) -> dict[str, Any] | None:
    return next(
        (item for item in probe.get("streams", []) if item.get("codec_type") == stream_type), None
    )


def _validate_source_probe(document: MveDocument, probe: dict[str, Any]) -> None:
    video = _stream(probe, "video")
    if video is None or video.get("codec_name") != "interplayvideo":
        raise MveFormatError("ffprobe did not identify an Interplay MVE video stream")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (
        document.video.width,
        document.video.height,
    ):
        raise MveFormatError("ffprobe video dimensions disagree with the native MVE parser")
    if int(video.get("nb_read_frames", -1)) != document.frame_count:
        raise MveFormatError("ffprobe frame count disagrees with the native MVE parser")
    audio = _stream(probe, "audio")
    if document.audio is None:
        if audio is not None:
            raise MveFormatError("ffprobe found unexpected MVE audio")
    elif audio is None or (int(audio.get("channels", 0)), int(audio.get("sample_rate", 0))) != (
        document.audio.channels,
        document.audio.sample_rate,
    ):
        raise MveFormatError("ffprobe audio metadata disagrees with the native MVE parser")


def _validate_png(path: Path, document: MveDocument) -> None:
    data = path.read_bytes()
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MveFormatError("FFmpeg poster output is not a PNG")
    width, height = struct.unpack_from(">II", data, 16)
    if (width, height) != (document.video.width, document.video.height):
        raise MveFormatError("poster dimensions disagree with the MVE source")


def _validate_wav(path: Path, audio: MveAudio) -> dict[str, int]:
    try:
        with wave.open(str(path), "rb") as stream:
            result = {
                "channels": stream.getnchannels(),
                "sample_rate": stream.getframerate(),
                "sample_width": stream.getsampwidth(),
                "frame_count": stream.getnframes(),
            }
    except (wave.Error, EOFError) as exc:
        raise MveFormatError("FFmpeg audio output is not a valid PCM WAV") from exc
    if (result["channels"], result["sample_rate"], result["sample_width"]) != (
        audio.channels,
        audio.sample_rate,
        2,
    ):
        raise MveFormatError("WAV metadata disagrees with the MVE source")
    return result


def _segments_csv(document: MveDocument) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        (
            "index",
            "chunk_index",
            "file_offset",
            "payload_offset",
            "payload_size",
            "opcode",
            "opcode_name",
            "version",
        )
    )
    for segment in document.segments:
        writer.writerow(
            (
                segment.index,
                segment.chunk_index,
                segment.file_offset,
                segment.payload_offset,
                segment.payload_size,
                f"0x{segment.opcode:02X}",
                segment.opcode_name,
                segment.version,
            )
        )
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


def _preview_timing_filter(document: MveDocument) -> tuple[str, int]:
    """Map decoded frames back to native display-event timestamps."""
    targets = list(document.frame_display_indices)
    trailing = document.display_count - 1 - targets[-1]
    filters: list[str] = []
    if trailing:
        filters.append("tpad=stop_mode=clone:stop=1")
        targets.append(document.display_count - 1)

    previous_delta = 0
    terms: list[str] = ["N"]
    for frame_index, display_index in enumerate(targets):
        delta = display_index - frame_index
        increase = delta - previous_delta
        if increase:
            terms.append(f"if(gte(N\\,{frame_index})\\,{increase}\\,0)")
            previous_delta = delta
    duration = document.timing.frame_duration_microseconds
    filters.append(f"setpts=({'+'.join(terms)})*{duration}/1000000/TB")
    return ",".join(filters), len(targets)


def write_mve_export(
    document: MveDocument,
    workspace: Path | str,
    output: Path | str,
    ffmpeg_path: Path | str,
    *,
    overwrite: bool = False,
    inspected_tool: ExternalTool | None = None,
) -> tuple[Path, Path, Path, Path | None, Path, Path]:
    paths = mve_output_paths(workspace, output, document)
    json_path, csv_path, poster_path, audio_path, preview_path, hash_path = paths
    targets = tuple(path for path in paths if path is not None)
    if document.source_path in targets:
        raise ValueError(f"output would replace a source file: {document.source_path}")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")

    requested_ffmpeg = Path(ffmpeg_path).resolve()
    tool = inspected_tool or inspect_ffmpeg(requested_ffmpeg)
    if tool.ffmpeg_path != requested_ffmpeg:
        raise MveFormatError("inspected FFmpeg does not match the requested executable")
    source_probe = _probe(tool, document.source_path)
    _validate_source_probe(document, source_probe)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=json_path.parent, prefix=f".{json_path.stem}.mve."
    ) as temporary:
        temporary_root = Path(temporary)
        poster_temp = temporary_root / "poster.png"
        preview_temp = temporary_root / "preview.mp4"
        audio_temp = temporary_root / "audio.wav"
        common = [
            str(tool.ffmpeg_path),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(document.source_path),
        ]
        _run(common + ["-map", "0:v:0", "-frames:v", "1", "-map_metadata", "-1", str(poster_temp)])
        if document.audio is not None:
            _run(
                common
                + ["-map", "0:a:0", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(audio_temp)]
            )
        timing_filter, preview_frame_count = _preview_timing_filter(document)
        _run(
            common
            + [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                timing_filter,
                "-c:v",
                "mpeg4",
                "-q:v",
                "3",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-fps_mode",
                "vfr",
                "-map_metadata",
                "-1",
                str(preview_temp),
            ]
        )

        _validate_png(poster_temp, document)
        wav_info = _validate_wav(audio_temp, document.audio) if document.audio else None
        preview_probe = _probe(tool, preview_temp)
        preview_video = _stream(preview_probe, "video")
        if preview_video is None or (
            int(preview_video.get("width", 0)),
            int(preview_video.get("height", 0)),
            int(preview_video.get("nb_read_frames", -1)),
        ) != (document.video.width, document.video.height, preview_frame_count):
            raise MveFormatError(
                "preview MP4 does not match the source video geometry or frame count"
            )
        preview_duration = float(preview_video.get("duration", 0))
        expected_duration = (
            document.display_count * document.timing.frame_duration_microseconds / 1_000_000
        )
        if abs(preview_duration - expected_duration) > (
            2 * document.timing.frame_duration_microseconds / 1_000_000
        ):
            raise MveFormatError("preview MP4 duration disagrees with MVE display timing")

        generated: list[tuple[Path, bytes, str]] = [
            (poster_path, poster_temp.read_bytes(), "poster_png"),
            (preview_path, preview_temp.read_bytes(), "preview_mp4"),
        ]
        if audio_path is not None:
            generated.append((audio_path, audio_temp.read_bytes(), "audio_wav"))

    csv_bytes = _segments_csv(document)
    opcode_counts = Counter(segment.opcode for segment in document.segments)
    workspace_path = Path(workspace).resolve()
    derived = {
        label: {
            "path": path.relative_to(workspace_path).as_posix(),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }
        for path, data, label in generated
    }
    derived["segments_csv"] = {
        "path": csv_path.relative_to(workspace_path).as_posix(),
        "size": len(csv_bytes),
        "sha256": hashlib.sha256(csv_bytes).hexdigest().upper(),
    }
    if wav_info is not None:
        derived["audio_wav"]["pcm"] = wav_info
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Interplay MVE",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "mve",
            "component_version": MVE_CONVERTER_VERSION,
        },
        "source": {
            "path": str(document.source_path),
            "size": document.source_size,
            "sha256": document.source_sha256,
        },
        "summary": mve_summary(document),
        "frame_display_indices": list(document.frame_display_indices),
        "header": {
            "signature": MVE_SIGNATURE.decode("ascii", errors="backslashreplace"),
            "constants": list(MVE_HEADER_CONSTANTS),
        },
        "opcode_counts": {
            f"0x{opcode:02X}": count for opcode, count in sorted(opcode_counts.items())
        },
        "chunks": [
            {
                "index": chunk.index,
                "file_offset": chunk.file_offset,
                "payload_size": chunk.payload_size,
                "type": chunk.chunk_type,
                "name": chunk.chunk_name,
                "first_segment_index": chunk.first_segment_index,
                "segment_count": chunk.segment_count,
            }
            for chunk in document.chunks
        ],
        "external_tool": {
            "version": tool.version_line,
            "ffmpeg_path": str(tool.ffmpeg_path),
            "ffmpeg_sha256": tool.ffmpeg_sha256,
            "ffprobe_path": str(tool.ffprobe_path),
            "ffprobe_sha256": tool.ffprobe_sha256,
            "runtime_files": list(tool.runtime_files),
            "runtime_manifest_sha256": tool.runtime_manifest_sha256,
        },
        "probe": {"source": source_probe, "preview": preview_probe},
        "derived": derived,
        "preview_policy": "MPEG-4 Part 2 video and AAC audio are convenience previews; PNG and PCM WAV are separate decoded inspection artifacts.",
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {json_path.name}\n".encode(
        "ascii"
    )
    for path, data, _ in generated:
        write_file_atomic(path, data, overwrite=overwrite)
    write_file_atomic(csv_path, csv_bytes, overwrite=overwrite)
    write_file_atomic(json_path, json_bytes, overwrite=overwrite)
    write_file_atomic(hash_path, hash_bytes, overwrite=overwrite)
    return paths
