"""Decode Interplay ACM audio and export standard PCM WAV files safely.

The transform follows adecode v1.0.0 by Alexander Batalov (MIT); see
``docs/third-party-notices.md`` for attribution and the license text.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace
from .safe_io import write_file_atomic

ACM_FILE_ID = 0x032897
ACM_FILE_VERSION = 1
ACM_CONVERTER_VERSION = 3
ACM_HEADER_SIZE = 14
MAX_BLOCK_SAMPLES = 4_194_304
MAX_FILE_SAMPLES = 100_000_000


class AcmFormatError(ValueError):
    """Raised when an ACM file is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class AcmAudio:
    source_path: Path
    source_size: int
    source_sha256: str
    version: int
    channels: int
    sample_rate: int
    sample_count: int
    levels: int
    subbands: int
    samples_per_subband: int
    decoded_blocks: int
    bitstream_zero_pad_bytes: int
    band_formats: tuple[int, ...]
    pcm_s16le: bytes


class _BitReader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self._data = data
        self._offset = offset
        self._bits = 0
        self._bit_count = 0
        self._zero_pad_limit = 0
        self.zero_pad_bytes = 0

    def allow_bounded_zero_padding(self, byte_limit: int) -> None:
        """Match adecode's EOF fill, but only within a caller-defined bound."""
        self._zero_pad_limit = byte_limit

    def disallow_zero_padding(self) -> None:
        self._zero_pad_limit = self.zero_pad_bytes

    def take(self, count: int) -> int:
        while self._bit_count < count:
            if self._offset >= len(self._data):
                if self.zero_pad_bytes >= self._zero_pad_limit:
                    raise AcmFormatError("ACM compressed bitstream is truncated")
                byte = 0
                self.zero_pad_bytes += 1
            else:
                byte = self._data[self._offset]
                self._offset += 1
            self._bits |= byte << self._bit_count
            self._bit_count += 8
        value = self._bits & ((1 << count) - 1)
        self._bits >>= count
        self._bit_count -= count
        return value


def _signed_16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def _build_pack_tables() -> tuple[list[int], list[int], list[int]]:
    pack3 = [0] * 32
    pack5 = [0] * 128
    pack11 = [0] * 128
    for i in range(3):
        for j in range(3):
            for m in range(3):
                pack3[i + j * 3 + m * 9] = i + j * 4 + m * 16
    for i in range(5):
        for j in range(5):
            for m in range(5):
                pack5[i + j * 5 + m * 25] = i + j * 8 + m * 64
    for i in range(11):
        for j in range(11):
            pack11[i + j * 11] = i + j * 16
    return pack3, pack5, pack11


_PACK3_3, _PACK5_3, _PACK11_2 = _build_pack_tables()


class _Decoder:
    def __init__(self, data: bytes) -> None:
        if len(data) < ACM_HEADER_SIZE:
            raise AcmFormatError(
                f"ACM header is truncated: expected {ACM_HEADER_SIZE} bytes, found {len(data)}"
            )
        magic = int.from_bytes(data[0:3], "little")
        self.version = data[3]
        self.file_samples, self.channels, self.rate, packed = struct.unpack_from("<IHHH", data, 4)
        self.levels = packed & 0x0F
        self.samples_per_subband = packed >> 4
        self.subbands = 1 << self.levels
        self.total_samples = self.samples_per_subband * self.subbands

        if magic != ACM_FILE_ID:
            raise AcmFormatError(f"invalid ACM file id 0x{magic:06X}; expected 0x{ACM_FILE_ID:06X}")
        if self.version != ACM_FILE_VERSION:
            raise AcmFormatError(
                f"unsupported ACM version {self.version}; expected {ACM_FILE_VERSION}"
            )
        if self.channels not in (1, 2):
            raise AcmFormatError(f"unsupported ACM channel count: {self.channels}")
        if self.rate == 0:
            raise AcmFormatError("ACM sample rate must be non-zero")
        if self.file_samples == 0 or self.file_samples > MAX_FILE_SAMPLES:
            raise AcmFormatError(f"unsafe ACM sample count: {self.file_samples}")
        if self.samples_per_subband == 0:
            raise AcmFormatError("ACM samples-per-subband must be non-zero")
        if self.total_samples > MAX_BLOCK_SAMPLES:
            raise AcmFormatError(f"unsafe ACM decoded block size: {self.total_samples} samples")

        self.bits = _BitReader(data, ACM_HEADER_SIZE)
        self.samples = [0] * self.total_samples
        self.block_samples_per_subband = max(2048 // self.subbands - 2, 1)
        self.block_total_samples = self.block_samples_per_subband * self.subbands
        self.prev16 = [0] * self.subbands if self.levels else []
        self.prev32 = [0] * (self.subbands - 2) if self.levels else []
        self.decoded_blocks = 0
        self.band_formats: set[int] = set()

    def _scale_table(self) -> dict[int, int]:
        exponent = self.bits.take(4)
        count = 1 << exponent
        step = _signed_16(self.bits.take(16))
        return {index: _signed_16(index * step) for index in range(-count, count)}

    def _put(self, subband: int, values: list[int]) -> None:
        if len(values) != self.samples_per_subband:
            raise AssertionError("internal ACM band length mismatch")
        index = subband
        for value in values:
            self.samples[index] = value
            index += self.subbands

    def _read_band(self, subband: int, fmt: int, scale: dict[int, int]) -> None:
        count = self.samples_per_subband
        values: list[int] = []
        if fmt == 0:
            values = [0] * count
        elif 3 <= fmt <= 16:
            bias = -(1 << (fmt - 1))
            values = [scale[bias + self.bits.take(fmt)] for _ in range(count)]
        elif fmt == 17:
            while len(values) < count:
                code = self.bits.take(1)
                if code == 0:
                    values.extend((0, 0))
                else:
                    code |= self.bits.take(1) << 1
                    if code == 1:
                        values.append(0)
                    else:
                        code |= self.bits.take(1) << 2
                        values.append(scale[1] if code & 4 else scale[-1])
        elif fmt == 18:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.append(0)
                else:
                    values.append(scale[1] if self.bits.take(1) else scale[-1])
        elif fmt == 19:
            while len(values) < count:
                code = _PACK3_3[self.bits.take(5)]
                values.extend(
                    (scale[(code & 3) - 1], scale[((code >> 2) & 3) - 1], scale[(code >> 4) - 1])
                )
        elif fmt == 20:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.extend((0, 0))
                elif self.bits.take(1) == 0:
                    values.append(0)
                else:
                    code = self.bits.take(2)
                    values.append(scale[((code & 1) + 1) if code & 2 else -(2 - (code & 1))])
        elif fmt == 21:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.append(0)
                else:
                    code = self.bits.take(2)
                    values.append(scale[((code & 1) + 1) if code & 2 else -(2 - (code & 1))])
        elif fmt == 22:
            while len(values) < count:
                code = _PACK5_3[self.bits.take(7)]
                values.extend(
                    (scale[(code & 7) - 2], scale[((code >> 3) & 7) - 2], scale[(code >> 6) - 2])
                )
        elif fmt == 23:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.extend((0, 0))
                elif self.bits.take(1) == 0:
                    values.append(0)
                elif self.bits.take(1) == 0:
                    values.append(scale[1] if self.bits.take(1) else scale[-1])
                else:
                    code = self.bits.take(2)
                    if code > 1:
                        code += 3
                    values.append(scale[code - 3])
        elif fmt == 24:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.append(0)
                elif self.bits.take(1) == 0:
                    values.append(scale[1] if self.bits.take(1) else scale[-1])
                else:
                    code = self.bits.take(2)
                    if code > 1:
                        code += 3
                    values.append(scale[code - 3])
        elif fmt == 26:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.extend((0, 0))
                elif self.bits.take(1) == 0:
                    values.append(0)
                else:
                    code = self.bits.take(3)
                    if code > 3:
                        code += 1
                    values.append(scale[code - 4])
        elif fmt == 27:
            while len(values) < count:
                if self.bits.take(1) == 0:
                    values.append(0)
                else:
                    code = self.bits.take(3)
                    if code > 3:
                        code += 1
                    values.append(scale[code - 4])
        elif fmt == 29:
            while len(values) < count:
                code = _PACK11_2[self.bits.take(7)]
                values.extend((scale[(code & 15) - 5], scale[(code >> 4) - 5]))
        else:
            raise AcmFormatError(f"unsupported ACM band format {fmt} in subband {subband}")
        self._put(subband, values[:count])

    def _read_bands(self) -> None:
        scale = self._scale_table()
        for subband in range(self.subbands):
            try:
                band_format = self.bits.take(5)
                self.band_formats.add(band_format)
                self._read_band(subband, band_format, scale)
            except KeyError as exc:
                raise AcmFormatError(f"ACM scale table is too small for subband {subband}") from exc

    def _untransform_subband0(self, base: int, step: int, count: int) -> None:
        for lane in range(step):
            p = lane * 2
            b = base + lane
            if count == 2:
                l2, h2 = self.prev16[p], self.prev16[p + 1]
                l1 = self.samples[b]
                self.samples[b] = 2 * h2 + l2 + l1
                h1 = self.samples[b + step]
                self.samples[b + step] = 2 * l1 - h2 - h1
            elif count == 4:
                l1, h1 = self.prev16[p], self.prev16[p + 1]
                l2 = self.samples[b]
                self.samples[b] = 2 * h1 + l1 + l2
                h2 = self.samples[b + step]
                self.samples[b + step] = 2 * l2 - h1 - h2
                l1 = self.samples[b + step * 2]
                self.samples[b + step * 2] = 2 * h2 + l2 + l1
                h1 = self.samples[b + step * 3]
                self.samples[b + step * 3] = 2 * l1 - h2 - h1
            else:
                chunks = count >> 2
                if count & 2:
                    l2, h2 = self.prev16[p], self.prev16[p + 1]
                    l1 = self.samples[b]
                    self.samples[b] = 2 * h2 + l2 + l1
                    h1 = self.samples[b + step]
                    self.samples[b + step] = 2 * l2 - h2 - h1
                else:
                    l1, h1 = self.prev16[p], self.prev16[p + 1]
                cursor = b
                for _ in range(chunks):
                    l2 = self.samples[cursor]
                    self.samples[cursor] = 2 * h1 + l1 + l2
                    h2 = self.samples[cursor + step]
                    self.samples[cursor + step] = 2 * l2 - h1 - h2
                    l1 = self.samples[cursor + step * 2]
                    self.samples[cursor + step * 2] = 2 * h2 + l2 + l1
                    h1 = self.samples[cursor + step * 3]
                    self.samples[cursor + step * 3] = 2 * l1 - h2 - h1
                    cursor += step * 4
            self.prev16[p] = _signed_16(l1)
            self.prev16[p + 1] = _signed_16(h1)

    def _untransform_subband(self, previous: int, base: int, step: int, count: int) -> None:
        for lane in range(step):
            p = previous + lane * 2
            b = base + lane
            l1, h1 = self.prev32[p], self.prev32[p + 1]
            cursor = b
            for _ in range(1 if count == 4 else count >> 2):
                l2 = self.samples[cursor]
                self.samples[cursor] = 2 * h1 + l1 + l2
                h2 = self.samples[cursor + step]
                self.samples[cursor + step] = 2 * l2 - h1 - h2
                l1 = self.samples[cursor + step * 2]
                self.samples[cursor + step * 2] = 2 * h2 + l2 + l1
                h1 = self.samples[cursor + step * 3]
                self.samples[cursor + step * 3] = 2 * l1 - h2 - h1
                cursor += step * 4
            self.prev32[p], self.prev32[p + 1] = l1, h1

    def _untransform_all(self) -> None:
        if self.levels == 0:
            return
        remaining = self.samples_per_subband
        base = 0
        while remaining > 0:
            step = self.subbands >> 1
            rows = min(self.block_samples_per_subband, remaining)
            count = rows * 2
            self._untransform_subband0(base, step, count)
            for index in range(count):
                self.samples[base + index * step] += 1
            step >>= 1
            count *= 2
            previous = 0
            while step:
                self._untransform_subband(previous, base, step, count)
                previous += step * 2
                count *= 2
                step >>= 1
            base += self.block_total_samples
            remaining -= self.block_samples_per_subband

    def decode(self) -> bytes:
        output = bytearray()
        remaining = self.file_samples
        while remaining:
            if remaining <= self.total_samples:
                # adecode supplies zero bytes after physical EOF. Fallout 1's
                # shipped ACM corpus needs at most one such byte, so restrict
                # compatibility to that audited final-block allowance.
                self.bits.allow_bounded_zero_padding(1)
            self._read_bands()
            self._untransform_all()
            self.decoded_blocks += 1
            take = min(remaining, self.total_samples)
            for value in self.samples[:take]:
                output.extend(((value >> self.levels) & 0xFFFF).to_bytes(2, "little"))
            remaining -= take
        self.bits.disallow_zero_padding()
        return bytes(output)


def parse_acm(data: bytes, source_path: Path | str = Path("<memory>.ACM")) -> AcmAudio:
    """Decode one Interplay ACM file into interleaved signed 16-bit PCM."""
    decoder = _Decoder(data)
    pcm = decoder.decode()
    return AcmAudio(
        source_path=Path(source_path).resolve(),
        source_size=len(data),
        source_sha256=hashlib.sha256(data).hexdigest().upper(),
        version=decoder.version,
        channels=decoder.channels,
        sample_rate=decoder.rate,
        sample_count=decoder.file_samples,
        levels=decoder.levels,
        subbands=decoder.subbands,
        samples_per_subband=decoder.samples_per_subband,
        decoded_blocks=decoder.decoded_blocks,
        bitstream_zero_pad_bytes=decoder.bits.zero_pad_bytes,
        band_formats=tuple(sorted(decoder.band_formats)),
        pcm_s16le=pcm,
    )


def load_acm(path: Path | str) -> AcmAudio:
    source = Path(path).resolve()
    before = source.stat()
    data = source.read_bytes()
    after = source.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise AcmFormatError(f"ACM source changed while reading: {source}")
    return parse_acm(data, source)


def encode_wav(audio: AcmAudio) -> bytes:
    """Wrap decoded interleaved PCM in a canonical RIFF/WAVE container."""
    pcm = audio.pcm_s16le
    padding_samples = (-audio.sample_count) % audio.channels
    if padding_samples:
        pcm += bytes(padding_samples * 2)
    data_size = len(pcm)
    byte_rate = audio.sample_rate * audio.channels * 2
    block_align = audio.channels * 2
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + data_size),
            b"WAVEfmt ",
            struct.pack(
                "<IHHIIHH", 16, 1, audio.channels, audio.sample_rate, byte_rate, block_align, 16
            ),
            b"data",
            struct.pack("<I", data_size),
            pcm,
        )
    )


def acm_summary(audio: AcmAudio) -> dict[str, Any]:
    return {
        "version": audio.version,
        "channels": audio.channels,
        "sample_rate": audio.sample_rate,
        "sample_count": audio.sample_count,
        "frame_count": (audio.sample_count + audio.channels - 1) // audio.channels,
        "partial_frame_samples": audio.sample_count % audio.channels,
        "wav_padding_samples": (-audio.sample_count) % audio.channels,
        "duration_seconds": audio.sample_count / (audio.sample_rate * audio.channels),
        "levels": audio.levels,
        "subbands": audio.subbands,
        "samples_per_subband": audio.samples_per_subband,
        "decoded_blocks": audio.decoded_blocks,
        "bitstream_zero_pad_bytes": audio.bitstream_zero_pad_bytes,
        "band_formats": list(audio.band_formats),
        "pcm_encoding": "signed 16-bit little-endian",
    }


def acm_output_paths(workspace: Path | str, output: Path | str) -> tuple[Path, Path, Path]:
    json_path = ensure_within_workspace(workspace, output)
    if json_path.suffix.casefold() != ".json":
        raise ValueError("ACM output must use a .json filename")
    wav_path = ensure_within_workspace(workspace, json_path.with_suffix(".wav"))
    hash_path = ensure_within_workspace(workspace, json_path.with_suffix(".json.sha256"))
    return json_path, wav_path, hash_path


def write_acm_export(
    audio: AcmAudio,
    workspace: Path | str,
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path, Path]:
    json_path, wav_path, hash_path = acm_output_paths(workspace, output)
    targets = (json_path, wav_path, hash_path)
    if audio.source_path in targets:
        raise ValueError(f"output would replace a source file: {audio.source_path}")
    if not overwrite:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"output already exists; refusing to overwrite: {existing[0]}")

    wav = encode_wav(audio)
    workspace_path = Path(workspace).resolve()
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "format": "Interplay ACM",
        "generator": {
            "name": "fallout1resource",
            "version": __version__,
            "component": "acm",
            "component_version": ACM_CONVERTER_VERSION,
        },
        "source": {
            "path": str(audio.source_path),
            "size": audio.source_size,
            "sha256": audio.source_sha256,
        },
        "summary": acm_summary(audio),
        "derived": {
            "wav": {
                "path": wav_path.relative_to(workspace_path).as_posix(),
                "size": len(wav),
                "sha256": hashlib.sha256(wav).hexdigest().upper(),
            }
        },
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    hash_bytes = f"{hashlib.sha256(json_bytes).hexdigest().upper()}  {json_path.name}\n".encode(
        "ascii"
    )
    write_file_atomic(wav_path, wav, overwrite=overwrite)
    write_file_atomic(json_path, json_bytes, overwrite=overwrite)
    write_file_atomic(hash_path, hash_bytes, overwrite=overwrite)
    return json_path, wav_path, hash_path
