# Local workspace

This directory is the only allowed destination for manifests, copied inputs, extracted resources, caches, and logs. Its contents are ignored by Git.

Planned local layout:

```text
workspace/
├─ input/
├─ raw/
├─ cache/
├─ manifests/
├─ output/
└─ logs/
```

Do not point any command at the Fallout installation directory as an output destination.

Converted MSG files use `output/text/<source>/...`; keep archive and loose-file sources in separate subdirectories so overrides remain auditable.

INT analysis uses `output/scripts/<source>/...` for JSON, disassembly text, and MSG-reference CSV files. These are derived research artifacts and remain ignored by Git.

FRM/PAL conversion uses `output/images/<name>/` for metadata, a palette preview, and PNG files grouped by unique direction sequence. Shared direction pixels are not duplicated; all six logical mappings remain in metadata.
