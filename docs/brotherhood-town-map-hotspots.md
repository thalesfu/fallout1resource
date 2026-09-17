# Brotherhood town-map hotspots

The Brotherhood town poster is `TWNMAP07.FRM` (453×444). Its five normal-game hotspots are taken from the `TownHotSpots` table in `fallout1-ce/src/game/worldmap.cc`:

| Label | MAP | Elevation | Source coordinate |
|---|---|---:|---:|
| Entrance / 入口 | `BROHDENT.MAP` | 0 | (172, 167) |
| Level 1 / 第一层 | `BROHD12.MAP` | 0 | (254, 194) |
| Level 2 / 第二层 | `BROHD12.MAP` | 1 | (136, 263) |
| Level 3 / 第三层 | `BROHD34.MAP` | 0 | (280, 306) |
| Level 4 / 第四层 | `BROHD34.MAP` | 1 | (161, 373) |

`BRODEAD.MAP` is the alternate destroyed entrance selected by a separate hotspot table entry at (172, 167); it does not add a sixth visible button to the poster.

The source coordinates are preserved in `config/brotherhood-town-map-hotspots.zh-CN.csv`. The annotated SVG uses the original decoded poster without altering its pixels, adds bilingual external labels, and keeps leader lines away from the five circular hotspot markers.
