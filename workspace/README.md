# Versioned workspace

This directory is the only allowed destination for manifests, copied inputs, extracted resources, caches, and logs. Its current contents are tracked as a reproducible extraction snapshot so they can be restored without reading the game archives again. Review generated diffs before committing a refreshed snapshot.

Current layout:

```text
workspace/
├─ raw/
├─ cache/
├─ index/
├─ manifests/
├─ output/
├─ archive/
├─ replay-20260727/
└─ tmp/
```

Do not point any command at the Fallout installation directory as an output destination.

Converted MSG files use `output/text/<source>/...`; keep archive and loose-file sources in separate subdirectories so overrides remain auditable.

INT analysis uses `output/scripts/<source>/...` for JSON, disassembly text, and MSG-reference CSV files. These derived research artifacts are part of the versioned snapshot.

`index/derived.jsonl` exceeds GitHub's regular-file limit and is stored with Git LFS. Run `git lfs pull` after cloning if it was not downloaded automatically.

FRM/PAL conversion uses `output/images/<name>/` for metadata, a palette preview, and PNG files grouped by unique direction sequence. Shared direction pixels are not duplicated; all six logical mappings remain in metadata.

MAP/PRO/LST analysis uses `output/maps/<name>/` for complete JSON, a flattened object CSV, and checksums. Prototype and script lists remain ordered, and nested inventory paths are preserved in both outputs.

ACM conversion uses `output/audio/<name>/` for 16-bit PCM WAV, source/stream metadata, and checksums. Any silence added solely to complete a final multichannel WAV frame is recorded in JSON.

MVE conversion uses `output/video/<name>/` for native container metadata, a segment CSV, first-frame PNG, decoded PCM WAV, preview MP4, and checksums. The MP4 is a convenience transcode; source MVE files remain under `raw/`.
