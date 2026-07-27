"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .acm import AcmFormatError, acm_output_paths, acm_summary, load_acm, write_acm_export
from .dat1 import Dat1FormatError
from .extract import (
    ExtractionError,
    build_extraction_plan,
    execute_extraction,
    write_extraction_manifest,
)
from .frm import (
    FrmFormatError,
    frm_output_paths,
    frm_summary,
    load_frm,
    load_palette,
    write_frm_export,
)
from .int_script import (
    IntFormatError,
    int_output_paths,
    int_summary,
    link_messages,
    load_int,
    write_int_export,
)
from .inventory import build_inventory, write_inventory
from .map_file import MapFormatError, load_map, map_output_paths, map_summary, write_map_export
from .msg import MsgFormatError, load_msg, msg_output_paths, msg_summary, write_msg_export
from .msg_batch import (
    MsgBatchError,
    build_msg_batch_plan,
    execute_msg_batch,
    msg_batch_plan_summary,
)
from .mve import MveFormatError, load_mve, mve_output_paths, mve_summary, write_mve_export
from .resource_index import ResourceIndexError, build_resource_index, write_resource_index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fallout1resource",
        description="Read-only Fallout 1 resource extraction and conversion tools.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="list DAT1 and loose DATA resources without extracting"
    )
    inventory.add_argument(
        "--game-dir", type=Path, required=True, help="read-only Fallout installation directory"
    )
    inventory.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    inventory.add_argument("--output", type=Path, default=Path("manifests/inventory.json"))
    inventory.add_argument(
        "--skip-source-hash", action="store_true", help="do not hash MASTER.DAT and CRITTER.DAT"
    )
    inventory.add_argument(
        "--hash-loose", action="store_true", help="hash each loose file below DATA"
    )

    extract = subparsers.add_parser(
        "extract", help="plan or extract explicitly selected DAT1 entries"
    )
    extract.add_argument(
        "--game-dir", type=Path, required=True, help="read-only Fallout installation directory"
    )
    extract.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    extract.add_argument(
        "--path", action="append", default=[], help="exact archive path; repeatable"
    )
    extract.add_argument(
        "--extension", action="append", default=[], help="file extension; repeatable"
    )
    extract.add_argument(
        "--type",
        action="append",
        default=[],
        dest="resource_types",
        help="resource type; repeatable",
    )
    extract.add_argument(
        "--archive", action="append", default=[], help="MASTER.DAT or CRITTER.DAT; repeatable"
    )
    extract.add_argument(
        "--execute", action="store_true", help="perform writes; omission is a dry-run"
    )
    extract.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing workspace files"
    )

    convert_msg = subparsers.add_parser("convert-msg", help="decode and parse a Fallout MSG file")
    convert_msg.add_argument("--input", type=Path, required=True, help="read-only source MSG file")
    convert_msg.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_msg.add_argument("--output", type=Path, help="JSON path below workspace")
    convert_msg.add_argument("--encoding", help="explicit source encoding, such as gbk or utf-8")
    convert_msg.add_argument(
        "--execute", action="store_true", help="write UTF-8 JSON, CSV, and checksum"
    )
    convert_msg.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    convert_msg_batch = subparsers.add_parser(
        "convert-msg-batch", help="convert extracted MSG files as a recoverable batch"
    )
    convert_msg_batch.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_msg_batch.add_argument(
        "--source",
        action="append",
        default=[],
        help="raw source directory such as master; repeatable",
    )
    convert_msg_batch.add_argument(
        "--execute", action="store_true", help="convert files and write a batch manifest"
    )
    convert_msg_batch.add_argument(
        "--overwrite", action="store_true", help="replace stale or older MSG outputs"
    )

    disassemble_int = subparsers.add_parser(
        "disassemble-int", help="parse and disassemble a Fallout INT file"
    )
    disassemble_int.add_argument(
        "--input", type=Path, required=True, help="read-only source INT file"
    )
    disassemble_int.add_argument(
        "--msg", type=Path, help="optional matching MSG source for text links"
    )
    disassemble_int.add_argument("--msg-encoding", help="explicit encoding for --msg")
    disassemble_int.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    disassemble_int.add_argument("--output", type=Path, help="JSON path below workspace")
    disassemble_int.add_argument(
        "--execute", action="store_true", help="write JSON, disassembly, links CSV, and checksum"
    )
    disassemble_int.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    convert_frm = subparsers.add_parser(
        "convert-frm", help="parse a Fallout FRM and export indexed PNG frames"
    )
    convert_frm.add_argument("--input", type=Path, required=True, help="read-only source FRM file")
    convert_frm.add_argument(
        "--palette", type=Path, required=True, help="read-only Fallout PAL color table"
    )
    convert_frm.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_frm.add_argument("--output", type=Path, help="metadata JSON path below workspace")
    convert_frm.add_argument(
        "--execute",
        action="store_true",
        help="write metadata, palette preview, PNG frames, and checksum",
    )
    convert_frm.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    convert_map = subparsers.add_parser(
        "convert-map", help="parse MAP objects and link their LST/PRO records"
    )
    convert_map.add_argument("--input", type=Path, required=True, help="read-only source MAP file")
    convert_map.add_argument(
        "--prototype-root",
        type=Path,
        required=True,
        help="read-only PROTO directory containing six LST files",
    )
    convert_map.add_argument(
        "--scripts-lst", type=Path, help="optional SCRIPTS.LST for script filename links"
    )
    convert_map.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_map.add_argument("--output", type=Path, help="metadata JSON path below workspace")
    convert_map.add_argument(
        "--execute", action="store_true", help="write JSON, object CSV, and checksum"
    )
    convert_map.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    convert_acm = subparsers.add_parser(
        "convert-acm", help="decode an Interplay ACM file to PCM WAV"
    )
    convert_acm.add_argument("--input", type=Path, required=True, help="read-only source ACM file")
    convert_acm.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_acm.add_argument("--output", type=Path, help="metadata JSON path below workspace")
    convert_acm.add_argument(
        "--execute", action="store_true", help="write WAV, metadata JSON, and checksum"
    )
    convert_acm.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    convert_mve = subparsers.add_parser(
        "convert-mve", help="inspect an Interplay MVE and create preview artifacts"
    )
    convert_mve.add_argument("--input", type=Path, required=True, help="read-only source MVE file")
    convert_mve.add_argument(
        "--ffmpeg", type=Path, help="audited FFmpeg executable; required with --execute"
    )
    convert_mve.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    convert_mve.add_argument("--output", type=Path, help="metadata JSON path below workspace")
    convert_mve.add_argument(
        "--execute", action="store_true", help="write MP4, PNG, WAV, JSON, CSV, and checksum"
    )
    convert_mve.add_argument(
        "--overwrite", action="store_true", help="atomically replace existing outputs"
    )

    build_index = subparsers.add_parser(
        "build-index", help="build a unified index from an inventory manifest"
    )
    build_index.add_argument("--workspace", type=Path, default=Path.cwd() / "workspace")
    build_index.add_argument("--inventory", type=Path, default=Path("manifests/inventory.json"))
    build_index.add_argument(
        "--extraction-manifest",
        type=Path,
        action="append",
        help="specific extraction manifest below workspace; repeatable (default: discover all)",
    )
    build_index.add_argument(
        "--conversion-metadata",
        type=Path,
        action="append",
        help="specific conversion metadata JSON below workspace; repeatable (default: discover all)",
    )
    build_index.add_argument(
        "--output", type=Path, default=Path("index"), help="directory below workspace"
    )
    build_index.add_argument(
        "--execute", action="store_true", help="write JSONL, CSV, summary, and checksums"
    )
    build_index.add_argument(
        "--overwrite", action="store_true", help="atomically replace the managed index directory"
    )
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
            output_path, csv_path, hash_path = write_inventory(
                manifest, args.workspace, args.output
            )
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
        if args.command == "convert-msg-batch":
            if args.overwrite and not args.execute:
                raise MsgBatchError("--overwrite requires --execute")
            plan = build_msg_batch_plan(args.workspace, sources=args.source)
            summary = msg_batch_plan_summary(plan)
            if not args.execute:
                print(
                    json.dumps(
                        {
                            "mode": "dry-run",
                            "selected": summary["selected"],
                            "source_bytes": summary["source_bytes"],
                            "source_counts": summary["source_counts"],
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            result = execute_msg_batch(plan, args.workspace, overwrite=args.overwrite)
            print(
                json.dumps(
                    {
                        "mode": "convert-msg-batch",
                        "selected": result.selected,
                        "converted": result.converted,
                        "skipped_verified": result.skipped_verified,
                        "failed": result.failed,
                        "source_bytes": result.source_bytes,
                        "output_bytes": result.output_bytes,
                        "duration_seconds": round(result.duration_seconds, 6),
                        "manifest": str(result.manifest_path),
                    },
                    ensure_ascii=False,
                )
            )
            return 2 if result.failed else 0
        if args.command == "disassemble-int":
            if args.overwrite and not args.execute:
                raise IntFormatError("--overwrite requires --execute")
            program = load_int(args.input)
            msg_document = load_msg(args.msg, encoding=args.msg_encoding) if args.msg else None
            references, inferred_list = link_messages(program, msg_document)
            output = args.output or Path("output/scripts") / f"{args.input.stem}.json"
            json_path, disasm_path, messages_path, hash_path = int_output_paths(
                args.workspace, output
            )
            result = {
                "mode": "disassemble-int" if args.execute else "dry-run",
                "source": str(program.source_path),
                **int_summary(program, references),
                "inferred_message_list_id": inferred_list,
                "json": str(json_path),
                "disassembly": str(disasm_path),
                "message_links": str(messages_path),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_int_export(
                    program,
                    references,
                    inferred_list,
                    msg_document,
                    args.workspace,
                    output,
                    overwrite=args.overwrite,
                )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "convert-frm":
            if args.overwrite and not args.execute:
                raise FrmFormatError("--overwrite requires --execute")
            document = load_frm(args.input)
            palette = load_palette(args.palette)
            output = (
                args.output or Path("output/images") / args.input.stem / f"{args.input.stem}.json"
            )
            json_path, palette_path, frame_paths, hash_path = frm_output_paths(
                args.workspace, output, document
            )
            result = {
                "mode": "convert-frm" if args.execute else "dry-run",
                "source": str(document.source_path),
                "palette_source": str(palette.source_path),
                **frm_summary(document),
                "metadata": str(json_path),
                "palette_preview": str(palette_path),
                "frame_pngs": len(frame_paths),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_frm_export(
                    document, palette, args.workspace, output, overwrite=args.overwrite
                )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "convert-map":
            if args.overwrite and not args.execute:
                raise MapFormatError("--overwrite requires --execute")
            document = load_map(
                args.input,
                args.prototype_root,
                scripts_list_path=args.scripts_lst,
            )
            output = (
                args.output or Path("output/maps") / args.input.stem / f"{args.input.stem}.json"
            )
            json_path, csv_path, hash_path = map_output_paths(args.workspace, output)
            result = {
                "mode": "convert-map" if args.execute else "dry-run",
                "source": str(document.source_path),
                **map_summary(document),
                "metadata": str(json_path),
                "objects_csv": str(csv_path),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_map_export(document, args.workspace, output, overwrite=args.overwrite)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "convert-acm":
            if args.overwrite and not args.execute:
                raise AcmFormatError("--overwrite requires --execute")
            audio = load_acm(args.input)
            output = (
                args.output or Path("output/audio") / args.input.stem / f"{args.input.stem}.json"
            )
            json_path, wav_path, hash_path = acm_output_paths(args.workspace, output)
            result = {
                "mode": "convert-acm" if args.execute else "dry-run",
                "source": str(audio.source_path),
                **acm_summary(audio),
                "metadata": str(json_path),
                "wav": str(wav_path),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_acm_export(audio, args.workspace, output, overwrite=args.overwrite)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "convert-mve":
            if args.overwrite and not args.execute:
                raise MveFormatError("--overwrite requires --execute")
            if args.execute and args.ffmpeg is None:
                raise MveFormatError("--ffmpeg is required with --execute")
            document = load_mve(args.input)
            output = (
                args.output or Path("output/video") / args.input.stem / f"{args.input.stem}.json"
            )
            json_path, csv_path, poster_path, audio_path, preview_path, hash_path = (
                mve_output_paths(args.workspace, output, document)
            )
            result = {
                "mode": "convert-mve" if args.execute else "dry-run",
                "source": str(document.source_path),
                **mve_summary(document),
                "ffmpeg": str(args.ffmpeg.resolve()) if args.ffmpeg else None,
                "metadata": str(json_path),
                "segments_csv": str(csv_path),
                "poster_png": str(poster_path),
                "audio_wav": str(audio_path) if audio_path else None,
                "preview_mp4": str(preview_path),
                "sha256": str(hash_path),
            }
            if args.execute:
                write_mve_export(
                    document,
                    args.workspace,
                    output,
                    args.ffmpeg,
                    overwrite=args.overwrite,
                )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "build-index":
            if args.overwrite and not args.execute:
                raise ResourceIndexError("--overwrite requires --execute")
            plan = build_resource_index(
                args.workspace,
                args.inventory,
                args.output,
                args.extraction_manifest,
                args.conversion_metadata,
            )
            result = {
                "mode": "build-index" if args.execute else "dry-run",
                "inventory": str(plan.inventory_path),
                "output_directory": str(plan.output_directory),
                "resources": plan.summary["resource_count"],
                "collision_paths": plan.summary["collision_path_count"],
                "unresolved_effective_sources": plan.summary["unresolved_effective_source_count"],
                "extraction_manifests": plan.summary["extraction_manifest_count"],
                "extracted_resources": plan.summary["extracted_resource_count"],
                "stale_extractions": plan.summary["stale_extraction_count"],
                "conversion_metadata": plan.summary["conversion_metadata_count"],
                "converted_resources": plan.summary["converted_resource_count"],
                "derived_files": plan.summary["derived_file_count"],
                "stale_conversions": plan.summary["stale_conversion_count"],
                "failures": plan.summary["failure_count"],
                "batch_id": plan.summary["batch_id"],
                "files": [
                    str(plan.output_directory / name)
                    for name in (
                        "resources.jsonl",
                        "derived.jsonl",
                        "failures.jsonl",
                        "collisions.csv",
                        "summary.json",
                        "index.json.sha256",
                    )
                ],
            }
            if args.execute:
                write_resource_index(plan, overwrite=args.overwrite)
            print(json.dumps(result, ensure_ascii=False))
            return 0
    except (
        AcmFormatError,
        Dat1FormatError,
        ExtractionError,
        FrmFormatError,
        IntFormatError,
        MapFormatError,
        MsgBatchError,
        MsgFormatError,
        MveFormatError,
        ResourceIndexError,
        FileNotFoundError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
