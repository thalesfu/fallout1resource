from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from fallout1resource.map_render import (
    MapRenderError,
    _critter_label_text,
    _item_label_text,
    build_critter_render_plan,
    build_door_render_plan,
    build_floor_render_plan,
    build_item_render_plan,
    build_scenery_render_plan,
    build_wall_render_plan,
    hex_tile_screen_position,
    square_tile_screen_position,
    write_critter_render,
    write_door_render,
    write_floor_render,
    write_item_render,
    write_scenery_render,
    write_wall_render,
)


def _frm_bytes(
    pixels: bytes,
    width: int = 2,
    height: int = 2,
    *,
    x_offsets: tuple[int, ...] = (0, 0, 0, 0, 0, 0),
    y_offsets: tuple[int, ...] = (0, 0, 0, 0, 0, 0),
) -> bytes:
    return _frm_multi_bytes(
        ((pixels, width, height, 0, 0),),
        x_offsets=x_offsets,
        y_offsets=y_offsets,
    )


def _frm_multi_bytes(
    frames: tuple[tuple[bytes, int, int, int, int], ...],
    *,
    x_offsets: tuple[int, ...] = (0, 0, 0, 0, 0, 0),
    y_offsets: tuple[int, ...] = (0, 0, 0, 0, 0, 0),
) -> bytes:
    frame_data = b"".join(
        struct.pack(">hhi2h", width, height, len(pixels), x_offset, y_offset) + pixels
        for pixels, width, height, x_offset, y_offset in frames
    )
    return b"".join(
        (
            struct.pack(">ihhh", 4, 0, 0, len(frames)),
            struct.pack(">6h", *x_offsets),
            struct.pack(">6h", *y_offsets),
            struct.pack(">6i", *([0] * 6)),
            struct.pack(">i", len(frame_data)),
            frame_data,
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

    def test_hex_coordinates_share_the_floor_global_origin(self) -> None:
        self.assertEqual((16, 2), hex_tile_screen_position(199))
        self.assertEqual((48, 2), hex_tile_screen_position(198))
        self.assertEqual((32, 14), hex_tile_screen_position(399))


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


class WallRenderTests(FloorRenderTests):
    def setUp(self) -> None:
        super().setUp()
        self.walls = self.workspace / "raw" / "master" / "ART" / "WALLS"
        self.walls.mkdir(parents=True)
        self.walls_list = self.walls / "WALLS.LST"
        self.walls_list.write_bytes(b"wall0.frm\r\n")
        (self.walls / "WALL0.FRM").write_bytes(
            _frm_bytes(
                bytes((5, 5, 5, 5, 5, 5)),
                width=2,
                height=3,
                x_offsets=(3, 0, 0, 0, 0, 0),
                y_offsets=(-2, 0, 0, 0, 0, 0),
            )
        )
        self.payload["objects"] = {
            "entries": [
                {
                    "elevation_group": 0,
                    "object_id": 1,
                    "tile": 199,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x03000000,
                    "flags": 0,
                    "prototype": {"type": "wall"},
                },
                {
                    "elevation_group": 0,
                    "object_id": 2,
                    "tile": 198,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x03000000,
                    "flags": 0x08,
                    "prototype": {"type": "wall"},
                },
                {
                    "elevation_group": 0,
                    "object_id": 3,
                    "tile": 197,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x03000000,
                    "flags": 0x01,
                    "prototype": {"type": "wall"},
                },
            ]
        }
        self._write_map()

    def _wall_plan(self):
        return build_wall_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.walls_list,
            self.walls,
            self.palette,
            0,
            self.workspace,
            Path("output/maps-rendered/TEST/elevation-0-floor-walls.json"),
        )

    def test_plans_wall_anchor_bounds_and_game_draw_order(self) -> None:
        plan = self._wall_plan()

        self.assertEqual([2, 1], [item.object_id for item in plan.placements])
        self.assertEqual((66, 6), (plan.placements[0].screen_x, plan.placements[0].screen_y))
        self.assertEqual((34, 6), (plan.placements[1].screen_x, plan.placements[1].screen_y))
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(1, plan.flat_placements)
        self.assertEqual((34, 21), (plan.canvas_width, plan.canvas_height))

    def test_writes_matching_wall_and_composite_outputs(self) -> None:
        plan = self._wall_plan()
        json_path, wall_path, composite_path, hash_path = write_wall_render(plan)
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual((34, 21), struct.unpack_from(">II", wall_path.read_bytes(), 16))
        self.assertEqual((34, 21), struct.unpack_from(">II", composite_path.read_bytes(), 16))
        self.assertEqual(
            hashlib.sha256(wall_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["wall_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(composite_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["floor_walls_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )

        with self.assertRaises(FileExistsError):
            write_wall_render(plan)

    def test_rejects_wall_output_outside_workspace(self) -> None:
        with self.assertRaises(ValueError):
            build_wall_render_plan(
                self.map_json,
                self.tiles_list,
                self.tiles,
                self.walls_list,
                self.walls,
                self.palette,
                0,
                self.workspace,
                Path("../escape.json"),
            )


class DoorRenderTests(WallRenderTests):
    def setUp(self) -> None:
        super().setUp()
        self.scenery = self.workspace / "raw" / "master" / "ART" / "SCENERY"
        self.scenery.mkdir(parents=True)
        self.scenery_list = self.scenery / "SCENERY.LST"
        self.scenery_list.write_bytes(b"door0.frm\r\n")
        (self.scenery / "DOOR0.FRM").write_bytes(
            _frm_multi_bytes(
                (
                    (bytes((6, 6, 6, 6, 6, 6)), 2, 3, 0, 0),
                    (bytes((7, 7, 7, 7, 7, 7)), 3, 2, 1, -1),
                ),
                x_offsets=(1, 0, 0, 0, 0, 0),
                y_offsets=(2, 0, 0, 0, 0, 0),
            )
        )
        self.payload["objects"]["entries"].extend(
            (
                {
                    "elevation_group": 0,
                    "object_id": 4,
                    "tile": 197,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x02000000,
                    "flags": 0,
                    "prototype": {"type": "scenery", "subtype": 0, "subtype_name": "door"},
                    "update_data": {"open_flags": 0},
                },
                {
                    "elevation_group": 0,
                    "object_id": 5,
                    "tile": 196,
                    "x": 0,
                    "y": 0,
                    "frame": 1,
                    "rotation": 0,
                    "fid": 0x02000000,
                    "flags": 0,
                    "prototype": {"type": "scenery", "subtype": 0, "subtype_name": "door"},
                    "update_data": {"open_flags": 1},
                },
                {
                    "elevation_group": 0,
                    "object_id": 6,
                    "tile": 195,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x02000000,
                    "flags": 1,
                    "prototype": {"type": "scenery", "subtype": 0, "subtype_name": "door"},
                    "update_data": {"open_flags": 0},
                },
            )
        )
        self._write_map()

    def _door_plan(self):
        return build_door_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.walls_list,
            self.walls,
            self.scenery_list,
            self.scenery,
            self.palette,
            0,
            self.workspace,
            Path("output/maps-rendered/TEST/elevation-0-floor-walls-doors.json"),
        )

    def test_plans_saved_door_frames_states_and_order(self) -> None:
        plan = self._door_plan()

        self.assertEqual([5, 4], [item.object_id for item in plan.placements])
        self.assertEqual([1, 0], [item.frame_index for item in plan.placements])
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(2, plan.closed_placements)
        self.assertEqual(1, plan.open_or_transition_placements)
        self.assertEqual(1, plan.target_open_placements)
        self.assertEqual((0,), plan.used_door_ids)

    def test_writes_matching_door_and_composite_outputs(self) -> None:
        plan = self._door_plan()
        json_path, door_path, composite_path, hash_path = write_door_render(plan)
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(
            struct.unpack_from(">II", door_path.read_bytes(), 16),
            struct.unpack_from(">II", composite_path.read_bytes(), 16),
        )
        self.assertEqual(3, metadata["summary"]["validated_door_objects"])
        self.assertEqual(
            hashlib.sha256(door_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["door_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(composite_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["floor_walls_doors_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )

        with self.assertRaises(FileExistsError):
            write_door_render(plan)

    def test_rejects_door_output_outside_workspace(self) -> None:
        with self.assertRaises(ValueError):
            build_door_render_plan(
                self.map_json,
                self.tiles_list,
                self.tiles,
                self.walls_list,
                self.walls,
                self.scenery_list,
                self.scenery,
                self.palette,
                0,
                self.workspace,
                Path("../escape.json"),
            )


class SceneryRenderTests(DoorRenderTests):
    def setUp(self) -> None:
        super().setUp()
        self.scenery_list.write_bytes(b"door0.frm\r\nscene1.frm\r\n")
        (self.scenery / "SCENE1.FRM").write_bytes(
            _frm_bytes(
                bytes((8, 8, 8, 8, 8, 8)),
                width=2,
                height=3,
                x_offsets=(2, 0, 0, 0, 0, 0),
                y_offsets=(-1, 0, 0, 0, 0, 0),
            )
        )
        self.payload["objects"]["entries"].extend(
            (
                {
                    "elevation_group": 0,
                    "object_id": 7,
                    "tile": 194,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x02000001,
                    "flags": 0,
                    "prototype": {"type": "scenery", "subtype": 5, "subtype_name": "generic"},
                },
                {
                    "elevation_group": 0,
                    "object_id": 8,
                    "tile": 193,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x02000001,
                    "flags": 0x08,
                    "prototype": {"type": "scenery", "subtype": 1, "subtype_name": "stairs"},
                },
                {
                    "elevation_group": 0,
                    "object_id": 9,
                    "tile": 192,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x02000001,
                    "flags": 0x01,
                    "prototype": {"type": "scenery", "subtype": 5, "subtype_name": "generic"},
                },
            )
        )
        self._write_map()

    def _scenery_plan(self):
        return build_scenery_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.walls_list,
            self.walls,
            self.scenery_list,
            self.scenery,
            self.palette,
            0,
            self.workspace,
            Path("output/maps-rendered/TEST/elevation-0-floor-walls-doors-scenery.json"),
        )

    def test_plans_non_door_scenery_with_unified_draw_order(self) -> None:
        plan = self._scenery_plan()

        self.assertEqual([8, 7], [item.object_id for item in plan.placements])
        self.assertEqual((177, -29), (plan.placements[0].screen_x, plan.placements[0].screen_y))
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(1, plan.flat_placements)
        self.assertEqual((("generic", 2), ("stairs", 1)), plan.subtype_counts)
        self.assertEqual((1,), plan.used_scenery_ids)

    def test_writes_matching_scenery_and_composite_outputs(self) -> None:
        plan = self._scenery_plan()
        json_path, scenery_path, composite_path, hash_path = write_scenery_render(plan)
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(
            struct.unpack_from(">II", scenery_path.read_bytes(), 16),
            struct.unpack_from(">II", composite_path.read_bytes(), 16),
        )
        self.assertEqual(3, metadata["summary"]["validated_scenery_objects"])
        self.assertEqual(
            hashlib.sha256(scenery_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["scenery_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(composite_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["floor_walls_doors_scenery_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )


class ItemRenderTests(SceneryRenderTests):
    def setUp(self) -> None:
        super().setUp()
        self.items = self.workspace / "raw" / "master" / "ART" / "ITEMS"
        self.items.mkdir(parents=True)
        self.items_list = self.items / "ITEMS.LST"
        self.items_list.write_bytes(b"item0.frm\r\n")
        (self.items / "ITEM0.FRM").write_bytes(
            _frm_bytes(
                bytes((9, 9, 9, 9, 9, 9)),
                width=2,
                height=3,
                x_offsets=(1, 0, 0, 0, 0, 0),
                y_offsets=(2, 0, 0, 0, 0, 0),
            )
        )
        self.payload["summary"]["inventory_objects"] = 4
        self.payload["objects"]["entries"].extend(
            (
                {
                    "elevation_group": 0,
                    "object_id": 10,
                    "tile": 191,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0,
                    "flags": 0,
                    "prototype": {
                        "type": "item",
                        "list_index": 3,
                        "subtype": 1,
                        "subtype_name": "container",
                    },
                    "inventory": [
                        {
                            "quantity": 2,
                            "item": {
                                "prototype": {
                                    "type": "item",
                                    "list_index": 4,
                                    "subtype": 5,
                                    "subtype_name": "misc",
                                }
                            },
                        }
                    ],
                },
                {
                    "elevation_group": 0,
                    "object_id": 11,
                    "tile": 190,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0,
                    "flags": 0x08,
                    "prototype": {
                        "type": "item",
                        "list_index": 5,
                        "subtype": 3,
                        "subtype_name": "weapon",
                    },
                },
                {
                    "elevation_group": 0,
                    "object_id": 12,
                    "tile": 189,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0,
                    "flags": 0x01,
                    "prototype": {"type": "item", "subtype": 5, "subtype_name": "misc"},
                },
            )
        )
        self._write_map()

    def _item_plan(self):
        return build_item_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.walls_list,
            self.walls,
            self.scenery_list,
            self.scenery,
            self.items_list,
            self.items,
            self.palette,
            0,
            self.workspace,
            Path("output/maps-rendered/TEST/elevation-0-floor-walls-doors-scenery-items.json"),
        )

    def test_plans_only_top_level_items_with_unified_draw_order(self) -> None:
        plan = self._item_plan()

        self.assertEqual([11, 10], [item.object_id for item in plan.placements])
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(1, plan.flat_placements)
        self.assertEqual((("container", 1), ("misc", 1), ("weapon", 1)), plan.subtype_counts)
        self.assertEqual(4, plan.contained_item_objects)
        self.assertEqual((0,), plan.used_item_ids)

    def test_writes_matching_item_and_composite_outputs(self) -> None:
        plan = self._item_plan()
        json_path, item_path, composite_path, highlight_path, hash_path = write_item_render(plan)
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(
            struct.unpack_from(">II", item_path.read_bytes(), 16),
            struct.unpack_from(">II", composite_path.read_bytes(), 16),
        )
        self.assertEqual(
            struct.unpack_from(">II", composite_path.read_bytes(), 16),
            struct.unpack_from(">II", highlight_path.read_bytes(), 16),
        )
        self.assertNotEqual(composite_path.read_bytes(), highlight_path.read_bytes())
        self.assertEqual(3, metadata["summary"]["validated_item_objects"])
        self.assertEqual(4, metadata["summary"]["contained_item_objects_not_rendered"])
        self.assertEqual(
            hashlib.sha256(item_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["item_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(composite_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["floor_walls_doors_scenery_items_png"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(highlight_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["floor_walls_doors_scenery_items_highlighted_png"]["sha256"],
        )
        self.assertEqual(2, metadata["item_outline"]["radius_pixels"])
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )


class CritterRenderTests(ItemRenderTests):
    def setUp(self) -> None:
        super().setUp()
        self.critters = self.workspace / "raw" / "critter" / "ART" / "CRITTERS"
        self.critters.mkdir(parents=True)
        self.critters_list = self.critters / "CRITTERS.LST"
        self.critters_list.write_bytes(b"person,0\r\nmissing,0\r\n")
        (self.critters / "PERSONHA.FRM").write_bytes(
            _frm_bytes(
                bytes((10, 10, 10, 10, 10, 10)),
                width=2,
                height=3,
                x_offsets=(0, 0, 3, 0, 0, 0),
                y_offsets=(0, 0, -2, 0, 0, 0),
            )
        )
        (self.critters / "PERSONBA.FR2").write_bytes(
            _frm_bytes(
                bytes((11, 11, 11, 11)),
                width=2,
                height=2,
                x_offsets=(0, 0, 1, 0, 0, 0),
                y_offsets=(0, 0, 2, 0, 0, 0),
            )
        )
        self.payload["objects"]["entries"].extend(
            (
                {
                    "elevation_group": 0,
                    "object_id": 13,
                    "tile": 188,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 2,
                    "fid": 0x01005000,
                    "flags": 0x08,
                    "script_filename": "Person.int",
                    "prototype": {"type": "critter", "list_index": 1},
                },
                {
                    "elevation_group": 0,
                    "object_id": 14,
                    "tile": 187,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 2,
                    "fid": 0x31140000,
                    "flags": 0,
                    "prototype": {"type": "critter", "list_index": 1},
                },
                {
                    "elevation_group": 0,
                    "object_id": 15,
                    "tile": 186,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x01005000,
                    "flags": 0x01,
                    "prototype": {"type": "critter", "list_index": 1},
                },
                {
                    "elevation_group": 0,
                    "object_id": 16,
                    "tile": 185,
                    "x": 0,
                    "y": 0,
                    "frame": 0,
                    "rotation": 0,
                    "fid": 0x01000001,
                    "flags": 0,
                    "script_filename": "Missing.int",
                    "prototype": {"type": "critter", "list_index": 2},
                },
            )
        )
        self._write_map()

    def _critter_plan(self, **kwargs):
        return build_critter_render_plan(
            self.map_json,
            self.tiles_list,
            self.tiles,
            self.walls_list,
            self.walls,
            self.scenery_list,
            self.scenery,
            self.items_list,
            self.items,
            self.critters_list,
            self.critters,
            self.palette,
            0,
            self.workspace,
            Path(
                "output/maps-rendered/TEST/"
                "elevation-0-floor-walls-doors-scenery-items-critters.json"
            ),
            **kwargs,
        )

    def test_plans_saved_critter_fids_split_art_and_missing_art(self) -> None:
        plan = self._critter_plan()

        self.assertEqual([13, 14], [item.object_id for item in plan.placements])
        self.assertEqual(
            ["personha.frm", "personba.fr2"], [item.filename for item in plan.placements]
        )
        self.assertEqual(1, plan.hidden_placements)
        self.assertEqual(1, plan.flat_placements)
        self.assertEqual((0,), plan.used_critter_ids)
        self.assertEqual([16], [item.object_id for item in plan.missing_art])
        self.assertEqual("missingaa.frm", plan.missing_art[0].filename)

    def test_writes_matching_critter_composite_and_highlight_outputs(self) -> None:
        plan = self._critter_plan()
        json_path, critter_path, composite_path, highlight_path, hash_path = write_critter_render(
            plan
        )
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

        dimensions = struct.unpack_from(">II", critter_path.read_bytes(), 16)
        self.assertEqual(dimensions, struct.unpack_from(">II", composite_path.read_bytes(), 16))
        self.assertEqual(dimensions, struct.unpack_from(">II", highlight_path.read_bytes(), 16))
        self.assertNotEqual(composite_path.read_bytes(), highlight_path.read_bytes())
        self.assertEqual(4, metadata["summary"]["validated_critter_objects"])
        self.assertEqual(1, metadata["summary"]["missing_critter_art_placements"])
        self.assertEqual("Missing.int", metadata["missing_critter_art"][0]["script_filename"])
        self.assertEqual(
            hashlib.sha256(critter_path.read_bytes()).hexdigest().upper(),
            metadata["derived"]["critter_png"]["sha256"],
        )
        self.assertEqual(2, metadata["item_outline"]["radius_pixels"])
        self.assertEqual(2, metadata["critter_outline"]["radius_pixels"])
        self.assertEqual(
            "non-transparent pixels of every visible top-level item placement",
            metadata["item_outline"]["scope"],
        )
        self.assertEqual(
            hashlib.sha256(json_path.read_bytes()).hexdigest().upper(),
            hash_path.read_text(encoding="ascii").split()[0],
        )

    def test_extracts_prototype_and_script_names_for_chinese_labels(self) -> None:
        names_message = self.root / "PRO_CRIT.MSG"
        names_message.write_bytes(b"{100}{}{Person}\r\n{200}{}{Missing}\r\n")
        translations = self.root / "names.zh-CN.json"
        translations.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "locale": "zh-CN",
                    "prototype_names": {"Person": "人物", "Missing": "缺图人物"},
                    "bilingual_names": {"Person": "Person"},
                    "script_names": {"Person.int": "人物甲"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        font = self.root / "font.ttf"
        font.write_bytes(b"font fixture")

        plan = self._critter_plan(
            names_message_path=names_message,
            name_translations_path=translations,
            label_font_path=font,
            label_font_pixels=24,
        )

        self.assertEqual(3, len(plan.name_labels))
        labels = {item.object_id: item for item in plan.name_labels}
        self.assertEqual(
            ("Person", "人物甲", "script_filename"),
            (
                labels[13].source_name,
                labels[13].chinese_name,
                labels[13].name_source,
            ),
        )
        self.assertEqual("人物", labels[14].chinese_name)
        self.assertEqual("Person", labels[13].english_name)
        self.assertEqual("Person", labels[14].english_name)
        self.assertEqual("人物甲 / Person", _critter_label_text(labels[13]))
        self.assertEqual("缺图人物", labels[16].chinese_name)
        self.assertIsNone(labels[16].english_name)
        self.assertEqual("缺图人物", _critter_label_text(labels[16]))
        self.assertTrue(labels[16].missing_art)
        self.assertEqual("zh-CN", plan.label_resources.locale)
        self.assertTrue(plan.output_label_png.name.endswith("-labeled-zh-CN.png"))

    def test_extracts_item_names_and_container_contents_for_combined_labels(self) -> None:
        critter_names = self.root / "PRO_CRIT.MSG"
        critter_names.write_bytes(b"{100}{}{Person}\r\n{200}{}{Missing}\r\n")
        critter_translations = self.root / "critter-names.zh-CN.json"
        critter_translations.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "locale": "zh-CN",
                    "prototype_names": {"Person": "人物", "Missing": "缺图人物"},
                    "script_names": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        item_names = self.root / "PRO_ITEM.MSG"
        item_names.write_bytes(
            b"{300}{}{Container}\r\n{400}{}{Junk}\r\n{500}{}{Weapon}\r\n"
        )
        item_translations = self.root / "item-names.zh-CN.json"
        item_translations.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "locale": "zh-CN",
                    "prototype_names": {
                        "Container": "容器",
                        "Junk": "废料",
                        "Weapon": "武器",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        font = self.root / "font.ttf"
        font.write_bytes(b"font fixture")

        plan = self._critter_plan(
            names_message_path=critter_names,
            name_translations_path=critter_translations,
            item_names_message_path=item_names,
            item_name_translations_path=item_translations,
            label_font_path=font,
        )

        self.assertEqual(2, len(plan.item_name_labels))
        labels = {item.object_id: item for item in plan.item_name_labels}
        self.assertEqual("容器", labels[10].chinese_name)
        self.assertEqual(("废料", 2), (
            labels[10].contents[0].chinese_name,
            labels[10].contents[0].quantity,
        ))
        self.assertEqual("武器", labels[11].chinese_name)
        self.assertEqual("容器\n　　废料 ×2", _item_label_text(labels[10]))
        self.assertEqual("武器", _item_label_text(labels[11]))
        self.assertEqual("zh-CN", plan.item_label_resources.locale)
