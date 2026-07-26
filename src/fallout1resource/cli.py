"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .dat1 import Dat1FormatError
from .extract import ExtractionError, build_extraction_plan, execute_extraction, write_extraction_manifest
from .inventory import build_inventory, write_inventory
from .msg import MsgFormatError, load_msg, msg_output_paths, msg_summary, write_msg_export


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fallout1resource",
        description="Read-only Fallout 1 resource extraction and conversion tools.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="list DAT1 and loose DATA resources without extracting")
    inventory.add_argument("--game-dir", type=Path, required=True, help="read-only Fallout installation directory")
    inventory.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    inventory.add_argument("--output", type=Path, default=Path("manifests/inventory.json"))
    inventory.add_argument("--skip-source-hash", action="store_true", help="do not hash MASTER.DAT and CRITTER.DAT")
    inventory.add_argument("--hash-loose", action="store_true", help="hash each loose file below DATA")

    extract = subparsers.add_parser("extract", help="plan or extract explicitly selected DAT1 entries")
    extract.add_argument("--game-dir", type=Path, required=True, help="read-only Fallout installation directory")
    extract.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    extract.add_argument("--path", action="append", default=[], help="exact archive path; repeatable")
    extract.add_argument("--extension", action="append", default=[], help="file extension; repeatable")
    extract.add_argument("--type", action="append", default=[], dest="resource_types", help="resource type; repeatable")
    extract.add_argument("--archive", action="append", default=[], help="MASTER.DAT or CRITTER.DAT; repeatable")
    extract.add_argument("--execute", action="store_true", help="perform writes; omission is a dry-run")
    extract.add_argument("--overwrite", action="store_true", help="atomically replace existing workspace files")

    convert_msg = subparsers.add_parser("convert-msg", help="decode and parse a Fallout MSG file")
    convert_msg.add_argument("--input", type=Path, required=True, help="read-only source MSG file")
    convert_msg.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_msg.add_argument("--output", type=Path, help="JSON path below workspace")
    convert_msg.add_argument("--encoding", help="explicit source encoding, such as gbk or utf-8")
    convert_msg.add_argument("--execute", action="store_true", help="write UTF-8 JSON, CSV, and checksum")
    convert_msg.add_argument("--overwrite", action="store_true", help="atomically replace existing outputs")
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
        if args.command == "extract":
            if args.overwrite and not args.execute:
                raise ExtractionError("--overwrite requires --execute")
            plan = build_extraction_plan(
                args.game_dir,
                args.workspace,
                paths=args.path,
                extensions=args.extension,
                resource_types=args.resource_types,
                archives=args.archive,
            )
            if not args.execute:
                print(
                    json.dumps(
                        {
                            "mode": "dry-run",
                            "selected": len(plan),
                            "items": [
                                {
                                    "source_archive": item.archive_name,
                                    "internal_path": item.entry.internal_path,
                                    "size": item.entry.size,
                                    "compression_mode": f"0x{item.entry.compression_mode:02X}",
                                    "target": str(item.target_path),
                                    "exists": item.target_path.exists(),
                                }
                                for item in plan
                            ],
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            results = execute_extraction(plan, args.workspace, overwrite=args.overwrite)
            manifest_path = write_extraction_manifest(results, args.workspace)
            print(
                json.dumps(
                    {
                        "mode": "extract",
                        "extracted": len(results),
                        "manifest": str(manifest_path),
                        "items": [str(result.target_path) for result in results],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "convert-msg":
            if args.overwrite and not args.execute:
                raise MsgFormatError("--overwrite requires --execute")
            document = load_msg(args.input, encoding=args.encoding)
            output = args.output or Path("output/text") / f"{args.input.stem}.json"
            json_path, csv_path, hash_path = msg_output_paths(args.workspace, output)
            summary = msg_summary(document)
            result = {
                "mode": "convert-msg" if args.execute else "dry-run",
                "source": str(document.source_path),
                "entries": summary["entries"],
                "unique_numbers": summary["unique_numbers"],
                "duplicate_number_count": len(summary["duplicate_numbers"]),
                "encoding": summary["encoding"],
                "encoding_confidence": summary["encoding_confidence"],
                "newline_style": summary["newline_style"],
                "json": str(json_path),
                "csv": str(csv_path),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_msg_export(document, args.workspace, output, overwrite=args.overwrite)
            print(json.dumps(result, ensure_ascii=False))
            return 0
    except (Dat1FormatError, ExtractionError, MsgFormatError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
