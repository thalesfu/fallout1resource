# Repository Guidelines

## Project Structure

Python package code lives in `src/fallout1resource/`; tests are under `tests/`. Format research and tool reviews belong in `docs/`, while reusable, machine-independent examples belong in `config/`. `workspace/` contains the versioned extraction snapshot: source resources under `raw/`, conversions under `output/`, run records under `manifests/`, and the unified catalog under `index/`. Do not add original DAT archives or write into the game installation.

## Development Commands

Use Python 3.11+ and the standard library where practical:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m fallout1resource --help
python -m unittest discover -s tests -v
```

Run inventory only against a legally owned installation and keep `--workspace` inside this repository. The game directory is read-only input.

## Style and Naming

Use four-space indentation, UTF-8, type hints, and small functions with explicit errors. Modules, functions, and variables use `snake_case`; classes use `PascalCase`; constants use `UPPER_SNAKE_CASE`. Prefer `pathlib.Path`, dataclasses, and standard-library parsers. Do not silently repair malformed archives or guess ambiguous encodings—preserve raw metadata and report validation issues.

## Testing

Use `unittest`. Test files follow `test_*.py`; test methods describe behavior, such as `test_rejects_truncated_header`. Build unit-test fixtures in temporary directories instead of duplicating snapshot bytes under `tests/`. Every path-writing feature needs tests for absolute paths, `..`, symlink escape, duplicate names, and overwrite refusal.

## Commits and Pull Requests

Use short scoped commits, for example `feat(inventory): list DAT1 entries` or `test(safety): reject traversal paths`. Pull requests should explain the resource formats affected, list validation commands, and state whether any real game installation was read. Changes to `workspace/` must identify the generating command, expected file-count or size change, and relevant manifest; do not commit unrelated saves or installation files.
