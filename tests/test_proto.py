from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.proto import (
    PID_DIRECTORIES,
    ProtoFormatError,
    PrototypeCatalog,
    parse_lst,
    parse_pro,
)


def build_pro(pid_type: int, *, subtype: int | None = None, list_index: int = 1) -> bytes:
    pid = (pid_type << 24) | list_index
    parts = [struct.pack(">3i", pid, 100 + list_index, 200 + list_index)]
    if pid_type == 0:
        actual_subtype = 5 if subtype is None else subtype
        parts.append(struct.pack(">6i", 0, 0, 1, 2, -1, actual_subtype))
        parts.append(struct.pack(">5iB", 3, 4, 5, 6, 7, 8))
        if actual_subtype == 5:
            parts.append(struct.pack(">3i", -1, 9, 10))
        elif actual_subtype == 6:
            parts.append(struct.pack(">i", 11))
        else:
            raise ValueError("synthetic helper only supports misc and key items")
    elif pid_type == 1:
        parts.append(struct.pack(">8i", 0, 0, 1, 2, 3, 4, 5, 6))
        parts.append(struct.pack(">i", 7))
        parts.append(struct.pack(">35i", *range(35)))
        parts.append(struct.pack(">35i", *range(35)))
        parts.append(struct.pack(">18i", *range(18)))
        parts.append(struct.pack(">3i", 0, 100, 1))
    elif pid_type == 2:
        actual_subtype = 5 if subtype is None else subtype
        parts.append(struct.pack(">6i", 0, 0, 1, 2, -1, actual_subtype))
        parts.append(struct.pack(">iB", 3, 4))
        parts.append(struct.pack(">i", 5))
    elif pid_type == 3:
        parts.append(struct.pack(">6i", 0, 0, 1, 2, -1, 3))
    elif pid_type == 4:
        parts.append(struct.pack(">4i", 1, 2, -1, 3))
    elif pid_type == 5:
        parts.append(struct.pack(">4i", 0, 0, 1, 2))
    else:
        raise ValueError(pid_type)
    return b"".join(parts)


def build_catalog(root: Path) -> PrototypeCatalog:
    for pid_type, directory_name in PID_DIRECTORIES.items():
        directory = root / directory_name
        directory.mkdir(parents=True)
        (directory / f"{directory_name}.LST").write_bytes(b"00000001.pro\r\n")
        (directory / "00000001.PRO").write_bytes(build_pro(pid_type))
    return PrototypeCatalog(root)


class ListTests(unittest.TestCase):
    def test_preserves_one_based_lines_filenames_and_annotations(self) -> None:
        document = parse_lst(b"ONE.PRO note\r\n\r\nTHREE.PRO\r\n")

        self.assertEqual("CRLF", document.newline_style)
        self.assertEqual([1, 2, 3], [entry.index for entry in document.entries])
        self.assertEqual("ONE.PRO", document.entries[0].filename)
        self.assertEqual("note", document.entries[0].annotation)
        self.assertEqual("", document.entries[1].filename)


class PrototypeTests(unittest.TestCase):
    def test_parses_all_six_pid_types(self) -> None:
        prototypes = [parse_pro(build_pro(pid_type)) for pid_type in range(6)]

        self.assertEqual(
            ["item", "critter", "scenery", "wall", "tile", "misc"],
            [p.type_name for p in prototypes],
        )
        self.assertEqual("misc", prototypes[0].subtype_name)
        self.assertEqual(10, prototypes[0].fields["data"]["charges"])
        self.assertEqual(35, len(prototypes[1].fields["base_stats"]))
        self.assertEqual("generic", prototypes[2].subtype_name)

    def test_rejects_truncated_and_trailing_data(self) -> None:
        data = build_pro(3)
        with self.assertRaisesRegex(ProtoFormatError, "truncated"):
            parse_pro(data[:-1])
        with self.assertRaisesRegex(ProtoFormatError, "trailing"):
            parse_pro(data + b"x")

    def test_catalog_resolves_pid_through_one_based_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = build_catalog(Path(temporary))
            prototype, entry = catalog.resolve(0x01000001)

            self.assertEqual("critter", prototype.type_name)
            self.assertEqual("00000001.pro", entry.filename)

    def test_catalog_rejects_missing_list_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = build_catalog(Path(temporary))
            with self.assertRaisesRegex(ProtoFormatError, "missing LST line"):
                catalog.resolve(0x01000002)


if __name__ == "__main__":
    unittest.main()
