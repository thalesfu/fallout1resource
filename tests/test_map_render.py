from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.map_render import (
    MapRenderError,
    build_floor_render_plan,
    square_tile_screen_position,
    write_floor_render,
)


def _frm_bytes(pixels: bytes, width: int = 2, height: int = 2) -> bytes:
    frame = struct.pack(">hhi2h", width, height, len(pixels), 0, 0) + pixels
    return b"".join(
        (
            struct.pack(">ihhh", 4, 0, 0, 1),
            struct.pack(">6h", *([0] * 6)),
            struct.pack(">6h", *([0] * 6)),
            struct.pack(">6i", *([0] * 6)),
            struct.pack(">i", len(frame)),
            frame,
        )
    )


def _palette_bytes() -> bytes:
    colors = bytearray()
    for index in range(256):
        value = index % 64
        colors.extend((value, value, value))
    return bytes(colors)


class SquareTileCoordinateTests(unittest.TestCase):
    def test_matches_fallout_square_coord_without_viewport_translation(self) -> None:
        self.assertEqual((4752, -1188), square_tile_screen_position(0, 100))
        self.assertEqual((0, 0), square_tile_screen_position(99, 100))
        self.assertEqual((4784, -1164), square_tile_screen_position(100, 100))


class FloorRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.tiles = self.workspace / "raw" / "master" / "ART" / "TILES"
        self.tiles.mkdir(parents=True)
        self.tiles_list = self.tiles / "TILES.LST"
        self.tiles_list.write_bytes(b"tile0.frm\r\ntile1.frm\r\n")
        (self.tiles / "TILE0.FRM").write_bytes(_frm_bytes(bytes((1, 0, 2, 3))))
        (self.tiles / "TILE1.FRM").write_bytes(_frm_bytes(bytes(4)))
        self.palette = self.workspace / "raw" / "master" / "COLOR.PAL"
        self.palette.write_bytes(_palette_bytes())
        self.map_json = self.workspace / "output" / "maps" / "TEST" / "TEST.json"
        self.map_json.parent.mkdir(parents=True)
        self.payload = {
            "schema_version": 1,
            "format": "Fallout MAP/PRO/LST",
            "summary": {"name": "TEST.MAP"},
            "tiles": [
                {
                    "elevation": 0,
                    "width": 2,
                    "height": 2,
                    "floor_ids": [0, 1, 0, 1],
                    "floor_flags": [0, 0, 1, 0],
                }
            ],
        }
        self._write_map()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_map(self) -> None:
        self.map_json.write_text(json.dumps(self.payload), encoding="utf-8")

    def _plan(self):
        return build_floor_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.palette,
            0,
            self.workspace,
            Path("output/maps-rendered/TEST/elevation-0-floor.json"),
        )

    def test_plans_visible_hidden_and_transparent_tiles(self) -> None:
        plan = self._plan()

        self.assertEqual(1, len(plan.placements))
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(2, plan.transparent_placements)
        self.assertEqual((0,), plan.used_tile_ids)
        self.assertEqual((2, 2), (plan.canvas_width, plan.canvas_height))

    def test_writes_deterministic_png_metadata_and_checksum(self) -> None:
        plan = self._plan()
        json_path, png_path, hash_path = write_floor_render(plan)
        first_png = png_path.read_bytes()
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertTrue(first_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((2, 2), struct.unpack_from(">II", first_png, 16))
        self.assertEqual(
            hashlib.sha256(first_png).hexdigest().upper(),
            metadata["derived"]["floor_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )
        write_floor_render(plan, overwrite=True)
        self.assertEqual(first_png, png_path.read_bytes())

    def test_rejects_tile_id_outside_list(self) -> None:
        self.payload["tiles"][0]["floor_ids"][0] = 2
        self._write_map()

        with self.assertRaisesRegex(MapRenderError, "outside TILES.LST range"):
            self._plan()
