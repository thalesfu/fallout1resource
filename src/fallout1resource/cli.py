"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .dat1 import Dat1FormatError
from .inventory import build_inventory, write_inventory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fallout1resource",
        description="Read-only Fallout 1 resource inventory tools.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="list DAT1 and loose DATA resources without extracting")
    inventory.add_argument("--game-dir", type=Path, required=True, help="read-only Fallout installation directory")
    inventory.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    inventory.add_argument("--output", type=Path, default=Path("manifests/inventory.json"))
    inventory.add_argument("--skip-source-hash", action="store_true", help="do not hash MASTER.DAT and CRITTER.DAT")
    inventory.add_argument("--hash-loose", action="store_true", help="hash each loose file below DATA")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inventory":
            manifest = build_inventory(
                args.game_dir,
                hash_sources=not args.skip_source_hash,
                hash_loose_files=args.hash_loose,
            )
            output_path, csv_path, hash_path = write_inventory(manifest, args.workspace, args.output)
            print(
                json.dumps(
                    {
                        "mode": manifest["mode"],
                        "entries": manifest["summary"]["entry_count"],
                        "duplicates": manifest["summary"]["duplicate_path_count"],
                        "unsafe_paths": manifest["summary"]["unsafe_path_count"],
                        "json": str(output_path),
                        "csv": str(csv_path),
                        "sha256": str(hash_path),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
    except (Dat1FormatError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1

