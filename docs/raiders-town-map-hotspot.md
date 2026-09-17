# Raiders town-map poster and hotspot annotation

## Source identity

`TWNMAP04.FRM` is the Raiders town-map poster. The location index and artwork index both use `4`; the poster itself shows the Khans emblem. Its decoded frame is `453 × 444` pixels.

The engine town-hotspot table defines exactly one Raiders selector:

| Index | Display name | Button anchor | Map index | Destination |
|---:|---|---:|---:|---|
| 0 | Base | `241, 398` | 1 | `RAIDERS.MAP` |

The effective localized `WORLDMAP.MSG` entry `240` renders this button as “营地”. The knowledge-base annotation uses “主营地 / Base” to connect that engine label with the canonical region page. `RAIDERS.MAP` elevation 1 is not a second town-map selector and is therefore not marked on the poster.

The hotspot table was checked against Fallout Community Edition [`worldmap.cc`](https://github.com/alexbatalov/fallout1-ce/blob/0609bcfd0ec40ff0571d0f57fab2821eb461dc8b/src/game/worldmap.cc). The reproducible data is stored in `config/raiders-town-map-hotspots.zh-CN.csv`.

## Assets

- `docs/assets/raiders-town-map-original.png`: decoded source frame copied without scaling;
- `docs/assets/raiders-town-map-annotated.svg`: editable bilingual layout;
- `docs/assets/raiders-town-map-annotated.png`: rendered delivery image.

Source hashes:

- `TWNMAP04.FRM`: `d9d090310fb1b27915cea5a00cd6c7338c7240b7c41d30480ee43dbe45870c1f`
- decoded PNG: `aa0757640e83837e0e884a3cf6b9dc0bf4b4c8c64924841144dd90a01091a7ed`
- annotated SVG: `f52c3a9874486d06b64e8a3cde73d8d8bdc69eae25a8606d3ca9d6fc15468903`
- annotated PNG: `a583faba308fff956b393db5fe5635dce3e8ebef268a2c0bbe7b4423af8c5e74`

Render the SVG with:

```sh
rsvg-convert --width 1280 --height 900 \
  --output docs/assets/raiders-town-map-annotated.png \
  docs/assets/raiders-town-map-annotated.svg
```

After rendering, verify the PNG dimensions and compare its SHA-256 on deterministic reruns.
