from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from fallout1resource.frm import (
    FRM_HEADER_SIZE,
    FrmFormatError,
    encode_indexed_png,
    frm_output_paths,
    parse_frm,
    parse_palette,
    write_frm_export,
)


def _frame(width: int, height: int, pixels: bytes, x: int = 0, y: int = 0) -> bytes:
    return struct.pack(">hhi2h", width, height, len(pixels), x, y) + pixels


def _frm_bytes() -> bytes:
    sequence_0 = _frame(2, 2, bytes((0, 1, 2, 3)), -2, 4) + _frame(1, 2, bytes((4, 5)), 6, -8)
    sequence_1 = _frame(2, 1, bytes((6, 7)), 1, 2) + _frame(1, 1, bytes((8,)), 3, 4)
    data = sequence_0 + sequence_1
    offsets = (0, len(sequence_0), len(sequence_0), len(sequence_0), len(sequence_0), len(sequence_0))
    return b"".join(
        (
            struct.pack(">ihhh", 4, 12, 1, 2),
            struct.pack(">6h", 10, 11, 12, 13, 14, 15),
            struct.pack(">6h", -10, -11, -12, -13, -14, -15),
            struct.pack(">6i", *offsets),
            struct.pack(">i", len(data)),
            data,
        )
    )


def _palette_bytes() -> bytes:
    colors = bytearray()
    for index in range(256):
        value = index % 64
        colors.extend((value, (value + 1) % 64, (value + 2) % 64))
    colors[0:3] = b"\xFF\xFF\xFF"
    return bytes(colors) + b"synthetic lookup table"


def _png_chunks(data: bytes) -> dict[bytes, list[bytes]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("not a PNG")
    chunks: dict[bytes, list[bytes]] = {}
    cursor = 8
    while cursor < len(data):
        length = struct.unpack_from(">I", data, cursor)[0]
        name = data[cursor + 4 : cursor + 8]
        payload = data[cursor + 8 : cursor + 8 + length]
        expected_crc = struct.unpack_from(">I", data, cursor + 8 + length)[0]
        actual_crc = zlib.crc32(name)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise AssertionError(f"bad CRC for {name!r}")
        chunks.setdefault(name, []).append(payload)
        cursor += 12 + length
    return chunks


class PaletteTests(unittest.TestCase):
    def test_parses_six_bit_colors_and_game_invalid_triplet_semantics(self) -> None:
        palette = parse_palette(_palette_bytes())

        self.assertEqual(256, len(palette.colors))
        self.assertEqual(len(b"synthetic lookup table"), palette.trailing_bytes)
        self.assertFalse(palette.colors[0].mapped)
        self.assertEqual((0, 0, 0), (palette.colors[0].red, palette.colors[0].green, palette.colors[0].blue))
        self.assertEqual(4, palette.colors[1].red)

    def test_rejects_truncated_palette(self) -> None:
        with self.assertRaisesRegex(FrmFormatError, "PAL is truncated"):
            parse_palette(bytes(767))


class FrmParsingTests(unittest.TestCase):
    def test_parses_shared_direction_sequences_and_frame_offsets(self) -> None:
        document = parse_frm(_frm_bytes())

        self.assertEqual(FRM_HEADER_SIZE, document.sequences[0].frames[0].file_offset)
        self.assertEqual(2, document.frame_count)
        self.assertEqual(2, len(document.sequences))
        self.assertEqual((0,), document.sequences[0].directions)
        self.assertEqual((1, 2, 3, 4, 5), document.sequences[1].directions)
        self.assertEqual(1, document.directions[5].sequence_index)
        self.assertEqual((-2, 4), (document.sequences[0].frames[0].x_offset, document.sequences[0].frames[0].y_offset))

    def test_rejects_truncated_header(self) -> None:
        with self.assertRaisesRegex(FrmFormatError, "header is truncated"):
            parse_frm(bytes(FRM_HEADER_SIZE - 1))

    def test_rejects_wrong_version(self) -> None:
        data = bytearray(_frm_bytes())
        data[0:4] = struct.pack(">i", 3)
        with self.assertRaisesRegex(FrmFormatError, "unsupported FRM version"):
            parse_frm(bytes(data))

    def test_rejects_action_frame_outside_range(self) -> None:
        data = bytearray(_frm_bytes())
        data[6:8] = struct.pack(">h", 2)
        with self.assertRaisesRegex(FrmFormatError, "action frame"):
            parse_frm(bytes(data))

    def test_rejects_declared_data_size_mismatch(self) -> None:
        with self.assertRaisesRegex(FrmFormatError, "data size mismatch"):
            parse_frm(_frm_bytes()[:-1])

    def test_rejects_pixel_count_mismatch(self) -> None:
        data = bytearray(_frm_bytes())
        data[FRM_HEADER_SIZE + 4 : FRM_HEADER_SIZE + 8] = struct.pack(">i", 3)
        with self.assertRaisesRegex(FrmFormatError, "pixel count mismatch"):
            parse_frm(bytes(data))

    def test_rejects_unordered_direction_offsets(self) -> None:
        data = bytearray(_frm_bytes())
        first_sequence_size = struct.unpack_from(">i", data, 38)[0]
        data[34:58] = struct.pack(">6i", 0, first_sequence_size, 0, first_sequence_size, first_sequence_size, first_sequence_size)
        with self.assertRaisesRegex(FrmFormatError, "not ordered"):
            parse_frm(bytes(data))


class PngTests(unittest.TestCase):
    def test_encodes_indexed_pixels_palette_and_transparency(self) -> None:
        palette = parse_palette(_palette_bytes())
        png = encode_indexed_png(2, 2, bytes((0, 1, 2, 3)), palette, transparent_index_zero=True)
        chunks = _png_chunks(png)

        self.assertEqual(768, len(chunks[b"PLTE"][0]))
        self.assertEqual(b"\x00", chunks[b"tRNS"][0])
        raw_rows = zlib.decompress(b"".join(chunks[b"IDAT"]))
        self.assertEqual(b"\x00\x00\x01\x00\x02\x03", raw_rows)


class FrmExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.frm_source = self.root / "sample.frm"
        self.palette_source = self.root / "color.pal"
        self.frm_source.write_bytes(_frm_bytes())
        self.palette_source.write_bytes(_palette_bytes())
        self.document = parse_frm(self.frm_source.read_bytes(), self.frm_source)
        self.palette = parse_palette(self.palette_source.read_bytes(), self.palette_source)
        self.output = Path("output/images/sample/sample.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_writes_metadata_palette_unique_frames_and_checksum(self) -> None:
        json_path, palette_path, frame_paths, hash_path = write_frm_export(
            self.document,
            self.palette,
            self.workspace,
            self.output,
        )

        self.assertEqual(4, len(frame_paths))
        self.assertTrue(palette_path.read_bytes().startswith(b"\x89PNG"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual([1, 2, 3, 4, 5], payload["sequences"][1]["directions"])
        self.assertEqual(4, payload["summary"]["exported_png_frames"])
        self.assertEqual(4, len(payload["derived"]["frames"]))
        for record, path in zip(payload["derived"]["frames"], frame_paths, strict=True):
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(), record["sha256"])
        expected_json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest().upper()
        self.assertEqual(expected_json_hash, hash_path.read_text(encoding="ascii").split()[0])

    def test_refuses_overwrite_before_writing(self) -> None:
        write_frm_export(self.document, self.palette, self.workspace, self.output)
        with self.assertRaises(FileExistsError):
            write_frm_export(self.document, self.palette, self.workspace, self.output)

    def test_explicit_overwrite_replaces_outputs(self) -> None:
        json_path, _, _, _ = write_frm_export(self.document, self.palette, self.workspace, self.output)
        json_path.write_text("broken", encoding="utf-8")
        write_frm_export(self.document, self.palette, self.workspace, self.output, overwrite=True)
        self.assertEqual(1, json.loads(json_path.read_text(encoding="utf-8"))["schema_version"])

    def test_rejects_outputs_outside_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            frm_output_paths(self.workspace, self.root / "outside.json", self.document)

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            frm_output_paths(self.workspace, Path("../escape.json"), self.document)

    def test_refuses_to_replace_a_source_file(self) -> None:
        source_in_workspace = self.workspace / "output" / "sample.json"
        source_in_workspace.parent.mkdir(parents=True)
        source_in_workspace.write_bytes(_frm_bytes())
        document = parse_frm(source_in_workspace.read_bytes(), source_in_workspace)
        with self.assertRaisesRegex(ValueError, "replace a source"):
            write_frm_export(document, self.palette, self.workspace, source_in_workspace, overwrite=True)

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
            frm_output_paths(self.workspace, Path("output/escape.json"), self.document)


if __name__ == "__main__":
    unittest.main()
