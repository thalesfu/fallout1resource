from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import wave
from io import BytesIO
from pathlib import Path

from fallout1resource.acm import (
    ACM_FILE_ID,
    AcmFormatError,
    acm_output_paths,
    encode_wav,
    parse_acm,
    write_acm_export,
)


def _pack_bits(fields: list[tuple[int, int]]) -> bytes:
    result = bytearray()
    pending = 0
    count = 0
    for value, width in fields:
        pending |= (value & ((1 << width) - 1)) << count
        count += width
        while count >= 8:
            result.append(pending & 0xFF)
            pending >>= 8
            count -= 8
    if count:
        result.append(pending & 0xFF)
    return bytes(result)


def _acm_bytes(
    *,
    sample_count: int = 4,
    channels: int = 1,
    rows: int = 4,
    levels: int = 0,
    band_format: int = 3,
    raw_samples: tuple[int, ...] = (4, 5, 3, 6),
) -> bytes:
    packed = (rows << 4) | levels
    header = b"\x97\x28\x03" + struct.pack("<BIHHH", 1, sample_count, channels, 22050, packed)
    fields = [(2, 4), (16, 16), (band_format, 5)]
    fields.extend((value, band_format) for value in raw_samples)
    return header + _pack_bits(fields)


class AcmParsingTests(unittest.TestCase):
    def test_decodes_direct_band_to_signed_pcm(self) -> None:
        audio = parse_acm(_acm_bytes())

        self.assertEqual(ACM_FILE_ID, int.from_bytes(_acm_bytes()[:3], "little"))
        self.assertEqual((0, 16, -16, 32), struct.unpack("<4h", audio.pcm_s16le))
        self.assertEqual(22050, audio.sample_rate)
        self.assertEqual(1, audio.channels)
        self.assertEqual(1, audio.decoded_blocks)
        self.assertEqual((3,), audio.band_formats)

    def test_decodes_zero_band(self) -> None:
        audio = parse_acm(_acm_bytes(sample_count=3, rows=3, band_format=0, raw_samples=()))
        self.assertEqual(bytes(6), audio.pcm_s16le)

    def test_decodes_every_direct_quantization_format(self) -> None:
        for band_format in range(3, 17):
            with self.subTest(band_format=band_format):
                audio = parse_acm(
                    _acm_bytes(
                        sample_count=1,
                        rows=1,
                        band_format=band_format,
                        raw_samples=(1 << (band_format - 1),),
                    )
                )
                self.assertEqual(bytes(2), audio.pcm_s16le)

    def test_rejects_truncated_header(self) -> None:
        with self.assertRaisesRegex(AcmFormatError, "header is truncated"):
            parse_acm(bytes(13))

    def test_rejects_wrong_magic_and_version(self) -> None:
        bad_magic = bytearray(_acm_bytes())
        bad_magic[0] = 0
        with self.assertRaisesRegex(AcmFormatError, "invalid ACM file id"):
            parse_acm(bytes(bad_magic))
        bad_version = bytearray(_acm_bytes())
        bad_version[3] = 2
        with self.assertRaisesRegex(AcmFormatError, "unsupported ACM version"):
            parse_acm(bytes(bad_version))

    def test_rejects_truncation_before_final_logical_block(self) -> None:
        with self.assertRaisesRegex(AcmFormatError, "bitstream is truncated"):
            parse_acm(_acm_bytes(sample_count=12))

    def test_zero_pads_physical_eof_in_final_logical_block(self) -> None:
        audio = parse_acm(_acm_bytes()[:-1])
        self.assertEqual(1, audio.bitstream_zero_pad_bytes)
        self.assertEqual(8, len(audio.pcm_s16le))

    def test_rejects_more_than_one_zero_pad_byte(self) -> None:
        with self.assertRaisesRegex(AcmFormatError, "bitstream is truncated"):
            parse_acm(_acm_bytes()[:-2])

    def test_rejects_reserved_band_format(self) -> None:
        with self.assertRaisesRegex(AcmFormatError, "unsupported ACM band format 1"):
            parse_acm(_acm_bytes(band_format=1, raw_samples=()))


class WavTests(unittest.TestCase):
    def test_pads_partial_stereo_frame_without_changing_decoded_pcm(self) -> None:
        audio = parse_acm(
            _acm_bytes(sample_count=3, channels=2, rows=3, band_format=0, raw_samples=())
        )
        wav_bytes = encode_wav(audio)
        with wave.open(BytesIO(wav_bytes), "rb") as stream:
            self.assertEqual(2, stream.getnchannels())
            self.assertEqual(2, stream.getnframes())
            self.assertEqual(22050, stream.getframerate())
            self.assertEqual(bytes(8), stream.readframes(2))
        self.assertEqual(bytes(6), audio.pcm_s16le)


class AcmExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "sample.acm"
        self.source.write_bytes(_acm_bytes())
        self.audio = parse_acm(self.source.read_bytes(), self.source)
        self.output = Path("output/audio/sample/sample.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_writes_wav_metadata_and_checksum(self) -> None:
        json_path, wav_path, hash_path = write_acm_export(self.audio, self.workspace, self.output)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual("Interplay ACM", payload["format"])
        self.assertEqual(
            hashlib.sha256(wav_path.read_bytes()).hexdigest().upper(),
            payload["derived"]["wav"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )

    def test_refuses_overwrite_before_writing(self) -> None:
        write_acm_export(self.audio, self.workspace, self.output)
        with self.assertRaises(FileExistsError):
            write_acm_export(self.audio, self.workspace, self.output)

    def test_explicit_overwrite_replaces_outputs(self) -> None:
        json_path, _, _ = write_acm_export(self.audio, self.workspace, self.output)
        json_path.write_text("broken", encoding="utf-8")
        write_acm_export(self.audio, self.workspace, self.output, overwrite=True)
        self.assertEqual(1, json.loads(json_path.read_text(encoding="utf-8"))["schema_version"])

    def test_rejects_absolute_and_parent_escape(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            acm_output_paths(self.workspace, self.root / "outside.json")
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            acm_output_paths(self.workspace, Path("../escape.json"))

    def test_refuses_to_replace_source(self) -> None:
        source_in_workspace = self.workspace / "output" / "sample.json"
        source_in_workspace.parent.mkdir(parents=True)
        source_in_workspace.write_bytes(_acm_bytes())
        audio = parse_acm(source_in_workspace.read_bytes(), source_in_workspace)
        with self.assertRaisesRegex(ValueError, "replace a source"):
            write_acm_export(audio, self.workspace, source_in_workspace, overwrite=True)

    def test_rejects_symlink_escape_when_supported(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        link = self.workspace / "output"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            acm_output_paths(self.workspace, Path("output/escape.json"))


if __name__ == "__main__":
    unittest.main()
