# Hub town-map poster and hotspot annotations

## Final display asset

`TWNMAP06.FRM` is the Hub town-map poster. Its decoded artwork is `453 × 444` pixels. The accepted display image is the existing `1268 × 1241` raster stored at:

- `docs/assets/hub-town-map-annotated.png`

SHA-256:

```text
c4d3c745d5e54a8490ddbd13065c3e8f4791eeb0581110d3876c8fa0fe06c8b8
```

This PNG is the selected finished artwork with bilingual labels and leader lines distributed on both sides. It was copied as-is rather than regenerated. `docs/assets/hub-town-map-annotated.svg` is a reusable layout template for making similar posters; it is not claimed to be the source of the selected PNG.

The Obsidian vault receives only the finished PNG and game-facing information. Extraction commands, coordinate provenance, and production notes remain in this repository.

## Coordinate sources

There are two intentionally separate coordinate sets in `config/hub-town-map-hotspots.zh-CN.csv`:

- `button_x`, `button_y`: exact in-game town-map button anchors, measured from the upper-left corner of the `453 × 444` poster. These were checked against the Hub entry in Fallout Community Edition's `TownHotSpots` table in `src/game/worldmap.cc`.
- `annotation_x`, `annotation_y`: visual anchor points used by the accepted annotated image. They are placed on the corresponding printed area so that the leader lines read clearly. They are not engine hotspot coordinates.

| Index | Label | Chinese label | Button anchor | Display anchor | Map |
|---:|---|---|---:|---:|---|
| 0 | Entrance | 城门 | `238, 78` | `230, 95` | `HUBENT.MAP` |
| 1 | Downtown | 中心区 | `205, 172` | `185, 198` | `HUBDWNTN.MAP` |
| 2 | Heights | 高地区 | `128, 138` | `151, 136` | `HUBHEIGT.MAP` |
| 3 | Old Town | 旧城区 | `306, 137` | `281, 168` | `HUBOLDTN.MAP` |
| 4 | Water Merchants | 纯水商人区 | `272, 238` | `229, 249` | `HUBWATER.MAP` |
| 5 | Cave | 死亡爪的窝 | `125, 216` | — | `DETHCLAW.MAP` |

The artwork prints the first five destinations. Cave is a functional town-map hotspot but has no printed label on the poster, so the display image does not add it.

## Reproducible method for similar posters

### 1. Decode the FRM artwork

Run from the repository root after the game resources have been extracted into `workspace/raw/master`:

```bash
PYTHONPATH=src python -m fallout1resource convert-frm \
  --input "$PWD/workspace/raw/master/ART/INTRFACE/TWNMAP06.FRM" \
  --palette "$PWD/workspace/raw/master/COLOR.PAL" \
  --workspace "$PWD/workspace" \
  --output "output/images/master/ART/INTRFACE/TWNMAP06.frm/TWNMAP06.frm.json" \
  --execute
```

Copy the decoded frame intended for annotation to `docs/assets/hub-town-map-original.png`. Keep the source image unscaled while choosing coordinates.

### 2. Prepare the coordinate table

Record the destination's English and Chinese names, exact engine anchor, map index, and map file. When the engine anchor obscures printed artwork or makes the line hard to read, add a separate visual annotation anchor. Never overwrite the engine coordinate with the adjusted one.

For a different town poster, create an equivalent CSV with both coordinate pairs. An empty annotation pair means the destination is deliberately omitted from the poster.

### 3. Build a two-sided SVG overlay

Use `docs/assets/hub-town-map-annotated.svg` as the layout reference:

1. Place the decoded poster with an SVG `<image>` element.
2. Draw a marker at each display anchor.
3. Divide labels between the left and right margins according to their anchor positions.
4. Connect each marker to its label with `<polyline>` or `<line>` elements.
5. Put the Chinese name, English name, and source coordinate in each label box.
6. Keep leader lines outside important printed text and avoid crossing them.

When the poster is scaled or offset inside the SVG, transform source coordinates with:

```text
display_x = image_x + source_x × scale_x
display_y = image_y + source_y × scale_y
```

For proportional scaling, `scale_x` and `scale_y` should be identical. Compute label-box positions separately; do not treat them as image coordinates.

### 4. Export a PNG

Render the SVG with librsvg:

```bash
rsvg-convert \
  --output docs/assets/hub-town-map-annotated.preview.png \
  docs/assets/hub-town-map-annotated.svg
```

The `.preview.png` name is deliberate: inspect the result before replacing any accepted display asset. Verify every anchor, line, bilingual label, and absence of overlap first. Only promote a reviewed preview to the final filename.

### 5. Verify the artifact

```bash
sips -g pixelWidth -g pixelHeight docs/assets/hub-town-map-annotated.png
shasum -a 256 docs/assets/hub-town-map-annotated.png
```

Finally, copy the reviewed PNG into the nearby Obsidian `attachments/` directory and embed it with an Obsidian wikilink. Do not place extraction commands or implementation notes in the game-content page.

## Artifacts

- `config/hub-town-map-hotspots.zh-CN.csv`: engine and display coordinates
- `docs/assets/hub-town-map-original.png`: decoded source artwork
- `docs/assets/hub-town-map-annotated.svg`: reusable two-sided layout template
- `docs/assets/hub-town-map-annotated.png`: accepted display image
