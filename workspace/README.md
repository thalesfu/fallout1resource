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
