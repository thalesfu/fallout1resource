from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.dat1 import Dat1FormatError, inspect_internal_path, parse_dat1


def _lp(value: str) -> bytes:
    encoded = value.encode("ascii")
    return bytes([len(encoded)]) + encoded


def build_dat1(path: Path, directory: str = "text\\english\\dialog") -> None:
    names = ["HAROLD.MSG", "README.TXT"]
    header_size = 16 + len(_lp(directory)) + 16
    entries_size = sum(len(_lp(name)) + 16 for name in names)
    first_offset = header_size + entries_size
    payloads = [b"hello", b"\x00\x04\x07xyz"]
    metadata = [struct.pack(">4I", 1, 1, 0, 0), _lp(directory), struct.pack(">4I", 2, 2, 16, 0)]
    metadata.extend(
        [
            _lp(names[0]),
            struct.pack(">4I", 0x20, first_offset, len(payloads[0]), 0),
            _lp(names[1]),
            struct.pack(">4I", 0x40, first_offset + len(payloads[0]), 3, len(payloads[1])),
        ]
    )
    path.write_bytes(b"".join(metadata + payloads))


class Dat1Tests(unittest.TestCase):
    def test_lists_entries_without_reading_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "MASTER.DAT"
            build_dat1(archive_path)
            archive = parse_dat1(archive_path)

        self.assertEqual(archive.directory_count, 1)
        self.assertEqual(len(archive.entries), 2)
        self.assertEqual(archive.entries[0].internal_path, "text/english/dialog/HAROLD.MSG")
        self.assertEqual(archive.entries[0].stored_size, 5)
        self.assertEqual(archive.entries[1].compression_mode, 0x40)
        self.assertEqual(archive.entries[1].stored_size, 6)

    def test_rejects_truncated_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "bad.dat"
            archive_path.write_bytes(b"\x00\x00\x00\x01")
            with self.assertRaises(Dat1FormatError):
                parse_dat1(archive_path)

    def test_rejects_dat2_like_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "fallout2.dat"
            archive_path.write_bytes(b"DAT2" + b"\x00" * 28)
            with self.assertRaises(Dat1FormatError):
                parse_dat1(archive_path)

    def test_marks_parent_traversal_unsafe(self) -> None:
        normalized, issues = inspect_internal_path("..\\outside", "file.msg")
        self.assertEqual(normalized, "../outside/file.msg")
        self.assertIn("parent traversal", issues)

    def test_treats_dot_directory_as_archive_root(self) -> None:
        normalized, issues = inspect_internal_path(".", "COLOR.PAL")
        self.assertEqual(normalized, "COLOR.PAL")
        self.assertEqual(issues, ())

    def test_marks_windows_reserved_name_unsafe(self) -> None:
        _, issues = inspect_internal_path("art", "NUL.frm")
        self.assertIn("reserved Windows name", issues)


if __name__ == "__main__":
    unittest.main()
