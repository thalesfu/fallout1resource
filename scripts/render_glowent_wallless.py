#!/usr/bin/env python3
"""Render GLOWENT through the standard object pipeline despite its zero-wall surface."""

from __future__ import annotations

from pathlib import Path

import fallout1resource.map_render as mr
from fallout1resource.proto import load_lst


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
MAP_JSON = WORKSPACE / "output/maps/master/MAPS/GLOWENT/GLOWENT.json"
TILES_LIST = WORKSPACE / "raw/master/ART/TILES/TILES.LST"
TILES_DIR = WORKSPACE / "raw/master/ART/TILES"
WALLS_LIST = WORKSPACE / "raw/master/ART/WALLS/WALLS.LST"
WALLS_DIR = WORKSPACE / "raw/master/ART/WALLS"
SCENERY_LIST = WORKSPACE / "raw/master/ART/SCENERY/SCENERY.LST"
SCENERY_DIR = WORKSPACE / "raw/master/ART/SCENERY"
ITEMS_LIST = WORKSPACE / "raw/master/ART/ITEMS/ITEMS.LST"
ITEMS_DIR = WORKSPACE / "raw/master/ART/ITEMS"
CRITTERS_LIST = WORKSPACE / "raw/critter/ART/CRITTERS/CRITTERS.LST"
CRITTERS_DIR = WORKSPACE / "raw/critter/ART/CRITTERS"
PALETTE = WORKSPACE / "raw/master/COLOR.PAL"
FONT = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")


def main() -> None:
    elevation = 0
    floor_output = Path("output/maps-rendered/GLOWENT/elevation-0-floor.json")
    floor = mr.build_floor_render_plan(
        MAP_JSON, TILES_LIST, TILES_DIR, PALETTE, elevation, WORKSPACE, floor_output
    )
    mr.write_floor_render(floor, overwrite=True)

    wall_output = Path("output/maps-rendered/GLOWENT/elevation-0-floor-walls.json")
    output_json, wall_png, wall_composite, output_hash = mr.wall_render_output_paths(
        WORKSPACE, wall_output
    )
    empty_wall = mr.WallRenderPlan(
        floor=floor,
        wall_list=load_lst(WALLS_LIST),
        wall_root=WALLS_DIR.resolve(),
        placements=(),
        used_wall_ids=(),
        hidden_placements=0,
        transparent_placements=0,
        flat_placements=0,
        bounds_left=floor.bounds_left,
        bounds_top=floor.bounds_top,
        bounds_right=floor.bounds_right,
        bounds_bottom=floor.bounds_bottom,
        output_json=output_json,
        output_wall_png=wall_png,
        output_composite_png=wall_composite,
        output_hash=output_hash,
    )

    original = mr.build_wall_render_plan
    mr.build_wall_render_plan = lambda *args, **kwargs: empty_wall
    try:
        final_output = Path(
            "output/maps-rendered/GLOWENT/"
            "elevation-0-floor-walls-doors-scenery-items-critters.json"
        )
        plan = mr.build_critter_render_plan(
            MAP_JSON,
            TILES_LIST,
            TILES_DIR,
            WALLS_LIST,
            WALLS_DIR,
            SCENERY_LIST,
            SCENERY_DIR,
            ITEMS_LIST,
            ITEMS_DIR,
            CRITTERS_LIST,
            CRITTERS_DIR,
            PALETTE,
            elevation,
            WORKSPACE,
            final_output,
            names_message_path=WORKSPACE / "raw/master/TEXT/ENGLISH/GAME/PRO_CRIT.MSG",
            name_translations_path=ROOT / "config/glow-critter-names.zh-CN.json",
            item_names_message_path=WORKSPACE / "raw/master/TEXT/ENGLISH/GAME/PRO_ITEM.MSG",
            item_name_translations_path=ROOT / "config/glow-item-names.zh-CN.json",
            label_font_path=FONT,
            label_font_pixels=28,
        )
    finally:
        mr.build_wall_render_plan = original
    mr.write_critter_render(plan, overwrite=True)
    print(mr.critter_render_summary(plan))


if __name__ == "__main__":
    main()
