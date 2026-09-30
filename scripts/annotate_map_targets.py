#!/usr/bin/env python3
"""Annotate a rendered map with numbered markers for a chosen set of critters.

Reads a `render-map-critters` output pair (composite PNG + metadata JSON), selects critters by
script name or object id, draws numbered circles at their rendered anchor points, crops to the
selection, and appends a legend table (number, name, HP, AC, weapon) below the map.

Critter stats and carried weapons come from the critter catalog (build_critter_catalog.py).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MARKER_FILL = (200, 30, 30)
EXTRA_FILL = (40, 90, 210)
MARKER_EDGE = (255, 255, 255)
LEGEND_BG = (18, 18, 18)
LEGEND_FG = (235, 235, 235)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-json", type=Path, required=True)
    ap.add_argument("--render-png", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--scripts", default="", help="comma-separated script-name prefixes, case-insensitive")
    ap.add_argument("--object-ids", default="", help="comma-separated map object ids")
    ap.add_argument("--map", dest="map_name", default="", help="map name used to look up instances in the catalog")
    ap.add_argument("--title", default="")
    ap.add_argument("--extra", default="", help="extra markers not counted as targets, as id=label[,id=label]")
    ap.add_argument("--font", default="/System/Library/Fonts/Hiragino Sans GB.ttc")
    ap.add_argument("--margin", type=int, default=360)
    ap.add_argument("--save-map", type=Path, default=None,
                    help="a SLOTnn/<MAP>.SAV file: use the live positions from that save and keep only survivors")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    meta = json.loads(args.render_json.read_text())
    labels = {l["object_id"]: l for l in meta["critter_name_labels"]["labels"]}
    prefixes = tuple(s.strip().lower() for s in args.scripts.split(",") if s.strip())
    ids = {int(x) for x in args.object_ids.split(",") if x.strip()}
    targets = [
        c for c in meta["critters"]
        if (ids and c["object_id"] in ids)
        or (prefixes and (c["script_filename"] or "").lower().startswith(prefixes))
    ]
    targets.sort(key=lambda c: (labels[c["object_id"]]["target_canvas"][1], labels[c["object_id"]]["target_canvas"][0]))

    if not targets:
        raise SystemExit("no critters matched")

    catalog = json.loads(args.catalog.read_text())
    items = catalog["items"]
    by_instance = {}
    for c in catalog["critters"]:
        for inst in c["instances"]:
            if not args.map_name or inst["map"].upper() == args.map_name.upper():
                by_instance[inst["object_id"]] = (c, inst)

    live: dict[int, dict] = {}
    if args.save_map:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from fallout1resource.map_file import parse_map
        from fallout1resource.proto import PrototypeCatalog, load_lst
        proto_root = args.save_map.parent  # unused; catalog comes from the workspace copy
        catalog_root = Path(__file__).resolve().parents[1] / "workspace/raw/master"
        doc = parse_map(args.save_map.read_bytes(), PrototypeCatalog(catalog_root / "PROTO"),
                        source_path=args.save_map, scripts_list=load_lst(catalog_root / "SCRIPTS/SCRIPTS.LST"))
        from fallout1resource.map_render import hex_tile_screen_position
        tx, ty = meta["coordinates"]["canvas_translation"]
        for obj in doc.objects:
            if (obj.pid >> 24) != 1:
                continue
            data = obj.update_data or {}
            hp = data.get("hit_points", 0)
            dead = bool(data.get("combat", {}).get("results", 0) & 0x80) or hp <= 0
            hx, hy = hex_tile_screen_position(obj.tile)
            live[obj.object_id] = {"hp": hp, "dead": dead, "canvas": (hx + 16 + tx, hy + 8 + ty - 50)}
        targets = [c for c in targets if not live.get(c["object_id"], {"dead": True})["dead"]]
        if not targets:
            raise SystemExit("save has no surviving targets")

    def anchor(object_id: int):
        return live[object_id]["canvas"] if object_id in live else labels[object_id]["target_canvas"]

    image = Image.open(args.render_png).convert("RGB")
    draw = ImageDraw.Draw(image)
    number_font = font(args.font, 34)
    for number, critter in enumerate(targets, start=1):
        x, y = anchor(critter["object_id"])
        cy = y - 46
        r = 26
        draw.ellipse((x - r, cy - r, x + r, cy + r), fill=MARKER_FILL, outline=MARKER_EDGE, width=4)
        text = str(number)
        tw = draw.textbbox((0, 0), text, font=number_font)
        draw.text((x - (tw[2] - tw[0]) / 2, cy - (tw[3] - tw[1]) / 2 - tw[1]), text, font=number_font, fill=MARKER_EDGE)

    extra = {}
    for pair in args.extra.split(","):
        if "=" in pair:
            oid, text = pair.split("=", 1)
            extra[int(oid)] = text.strip()
    for oid, text in extra.items():
        if oid not in labels:
            continue
        x, y = anchor(oid)
        cy, r = y - 46, 26
        draw.ellipse((x - r, cy - r, x + r, cy + r), fill=EXTRA_FILL, outline=MARKER_EDGE, width=4)
        tb = draw.textbbox((0, 0), text, font=number_font)
        draw.text((x - (tb[2] - tb[0]) / 2, cy - (tb[3] - tb[1]) / 2 - tb[1]), text, font=number_font, fill=MARKER_EDGE)

    xs = [anchor(c["object_id"])[0] for c in targets] + [anchor(o)[0] for o in extra if o in labels]
    ys = [anchor(c["object_id"])[1] for c in targets] + [anchor(o)[1] for o in extra if o in labels]
    box = (max(0, min(xs) - args.margin), max(0, min(ys) - args.margin - 120),
           min(image.width, max(xs) + args.margin), min(image.height, max(ys) + args.margin))
    cropped = image.crop(box)

    title_font = font(args.font, 44)
    head_font = font(args.font, 30)
    row_font = font(args.font, 28)
    rows = []
    for number, critter in enumerate(targets, start=1):
        label = labels[critter["object_id"]]
        entry = by_instance.get(critter["object_id"])
        hp = ac = "—"
        live_hp = live.get(critter["object_id"], {}).get("hp")
        weapon = "徒手"
        if entry:
            c, inst = entry
            hp, ac = inst["hp"] or c["stats"]["MAX_HP"], c["stats"]["AC"]
            held = [items[str(i["pid"])] for i in inst["inventory"] if i["slot"] in ("right_hand", "left_hand")]
            worn = [items[str(i["pid"])] for i in inst["inventory"] if i["slot"] == "worn"]
            guns = [w for w in held if w.get("weapon")]
            weapon = "、".join((w["name_zh"] or w["name_en"]) for w in guns) or "徒手"
            if worn:
                weapon += "（" + "、".join((w["name_zh"] or w["name_en"]) for w in worn) + "）"
        name = label["display_name"]
        if entry and entry[0]["name_zh"] and name in ("管理者成员", "内城区警卫"):
            name = f'{entry[0]["name_zh"]}（{name}）'
        rows.append((str(number), name, str(live_hp if live_hp is not None else hp), str(ac), weapon, critter["script_filename"] or ""))

    line_h = 42
    legend_h = 40 + (1 if args.title else 0) * 70 + 46 + line_h * (len(rows) + len(extra)) + 24
    canvas = Image.new("RGB", (cropped.width, cropped.height + legend_h), LEGEND_BG)
    canvas.paste(cropped, (0, 0))
    d = ImageDraw.Draw(canvas)
    y = cropped.height + 24
    if args.title:
        d.text((32, y), args.title, font=title_font, fill=LEGEND_FG)
        y += 70
    cols = [32, 110, 620, 760, 900]
    for text, x in zip(("#", "名称", "生命", "护甲", "武器与护甲"), cols):
        d.text((x, y), text, font=head_font, fill=(150, 190, 255))
    y += 46
    for row in rows:
        for text, x in zip(row[:5], cols):
            d.text((x, y), text, font=row_font, fill=LEGEND_FG)
        y += line_h
    for oid, text in extra.items():
        if oid in labels:
            d.text((cols[0], y), text, font=row_font, fill=(140, 180, 255))
            d.text((cols[1], y), f'{labels[oid]["display_name"]}（蓝色标记，不是目标，别误伤）', font=row_font, fill=(140, 180, 255))
            y += line_h
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"{len(targets)} 个目标 -> {args.output} ({canvas.width}×{canvas.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
