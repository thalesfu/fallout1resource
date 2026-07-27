from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.map_file import (
    MAP_HEADER_SIZE,
    MapFormatError,
    load_map,
    map_output_paths,
    map_summary,
    parse_map,
    write_map_export,
)
from fallout1resource.proto import PrototypeCatalog, parse_lst
from tests.test_proto import build_catalog


def _script_record(script_id: int = 0, script_index: int = 0, object_id: int = 0) -> bytes:
    values = [script_id, -1, 0, script_index, 0, object_id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    return struct.pack(">16i", *values)


def _scripts() -> bytes:
    parts = [struct.pack(">i", 0) for _ in range(4)]
    parts.append(struct.pack(">i", 1))
    parts.append(_script_record(0x04000002, 1, 100))
    parts.extend(_script_record() for _ in range(15))
    parts.append(struct.pack(">2i", 1, 0))
    return b"".join(parts)


def _base_object(
    *,
    object_id: int,
    tile: int,
    fid: int,
    pid: int,
    script_id: int,
) -> bytes:
    values = (
        object_id,
        tile,
        0,
        0,
        0,
        0,
        0,
        1,
        fid,
        0,
        0,
        pid,
        7,
        0,
        0,
        0,
        script_id,
        0,
    )
    return struct.pack(">18i", *values)


def _objects() -> bytes:
    critter = _base_object(
        object_id=100,
        tile=22942,
        fid=0x0100001C,
        pid=0x01000001,
        script_id=0x04000002,
    )
    critter += struct.pack(">14i", 1, 1, 0, 0, *([0] * 7), 20, 0, 0)
    item = _base_object(object_id=101, tile=-1, fid=1, pid=0x00000001, script_id=-1)
    item += struct.pack(">5i", 0, 0, 0, 0, 9)
    return struct.pack(">2i", 1, 1) + critter + struct.pack(">i", 2) + item + struct.pack(">2i", 0, 0)


def build_map() -> bytes:
    name = b"HUBOLDTN.MAP".ljust(16, b"\x00")
    header_values = (201, 0, 2, 1, 0, 0x0C, 0, 1, 5, 6)
    header = struct.pack(">i", 19) + name + struct.pack(">10i", *header_values) + struct.pack(">44i", *([0] * 44))
    variables = struct.pack(">2i", 11, 22)
    tiles = struct.pack(">10000i", *([0x00010002] * 10000))
    return header + variables + tiles + _scripts() + _objects()


class MapParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog = build_catalog(self.root / "PROTO")
        self.scripts_list = parse_lst(b"OTHER.INT\r\nHAROLD.INT\r\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parses_header_tiles_scripts_objects_inventory_and_links(self) -> None:
        document = parse_map(build_map(), self.catalog, scripts_list=self.scripts_list)

        self.assertEqual(MAP_HEADER_SIZE, 236)
        self.assertEqual("HUBOLDTN.MAP", document.header.name)
        self.assertEqual([0], sorted(document.tiles))
        self.assertEqual((11,), document.global_variables)
        self.assertEqual((22,), document.local_variables)
        self.assertEqual("HAROLD.INT", document.scripts[0].script_filename)
        self.assertEqual("HAROLD.INT", document.objects[0].script_filename)
        self.assertEqual("critter", document.objects[0].prototype.type_name)
        self.assertEqual(1, len(document.objects[0].inventory))
        self.assertEqual(2, document.objects[0].inventory[0].quantity)
        self.assertEqual("item", document.objects[0].inventory[0].item.prototype.type_name)
        self.assertEqual(2, map_summary(document)["referenced_prototypes"])

    def test_rejects_wrong_version_and_truncation(self) -> None:
        data = bytearray(build_map())
        data[0:4] = struct.pack(">i", 18)
        with self.assertRaisesRegex(MapFormatError, "unsupported MAP version"):
            parse_map(bytes(data), self.catalog)
        with self.assertRaisesRegex(MapFormatError, "truncated"):
            parse_map(build_map()[:-1], build_catalog(self.root / "PROTO2"), scripts_list=self.scripts_list)

    def test_rejects_active_script_in_wrong_type_list(self) -> None:
        data = bytearray(build_map())
        script_id = struct.pack(">i", 0x04000002)
        offset = data.find(script_id, MAP_HEADER_SIZE)
        self.assertNotEqual(-1, offset)
        data[offset : offset + 4] = struct.pack(">i", 0x03000002)
        with self.assertRaisesRegex(MapFormatError, "SID type"):
            parse_map(bytes(data), self.catalog, scripts_list=self.scripts_list)


class MapExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.map_source = self.root / "sample.map"
        self.scripts_source = self.root / "SCRIPTS.LST"
        self.map_source.write_bytes(build_map())
        self.scripts_source.write_bytes(b"OTHER.INT\r\nHAROLD.INT\r\n")
        self.prototype_root = self.root / "PROTO"
        build_catalog(self.prototype_root)
        self.document = load_map(
            self.map_source,
            self.prototype_root,
            scripts_list_path=self.scripts_source,
        )
        self.output = Path("output/maps/sample/sample.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_writes_json_object_csv_and_checksum(self) -> None:
        json_path, csv_path, hash_path = write_map_export(
            self.document,
            self.workspace,
            self.output,
        )

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(2, payload["summary"]["referenced_prototypes"])
        self.assertEqual(142, payload["objects"]["entries"][0]["tile_x"])
        self.assertEqual(114, payload["objects"]["entries"][0]["tile_y"])
        self.assertEqual("00000001.pro", payload["prototype_lists"][1]["ordered_entries"][0]["filename"])
        self.assertIn("HAROLD.INT", csv_path.read_text(encoding="utf-8-sig"))
        expected = hashlib.sha256(json_path.read_bytes()).hexdigest().upper()
        self.assertEqual(expected, hash_path.read_text(encoding="ascii").split()[0])

    def test_refuses_overwrite_and_allows_explicit_atomic_overwrite(self) -> None:
        json_path, _, _ = write_map_export(self.document, self.workspace, self.output)
        with self.assertRaises(FileExistsError):
            write_map_export(self.document, self.workspace, self.output)
        json_path.write_text("broken", encoding="utf-8")
        write_map_export(self.document, self.workspace, self.output, overwrite=True)
        self.assertEqual(1, json.loads(json_path.read_text(encoding="utf-8"))["schema_version"])

    def test_rejects_absolute_and_parent_traversal_outputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            map_output_paths(self.workspace, self.root / "outside.json")
        with self.assertRaisesRegex(ValueError, "inside workspace"):
            map_output_paths(self.workspace, Path("../escape.json"))

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
            map_output_paths(self.workspace, Path("output/escape.json"))

    def test_refuses_to_replace_a_source_file(self) -> None:
        source = self.workspace / "output" / "source.json"
        source.parent.mkdir(parents=True)
        source.write_bytes(build_map())
        document = load_map(source, self.prototype_root, scripts_list_path=self.scripts_source)
        with self.assertRaisesRegex(ValueError, "replace a source"):
            write_map_export(document, self.workspace, source, overwrite=True)


if __name__ == "__main__":
    unittest.main()
