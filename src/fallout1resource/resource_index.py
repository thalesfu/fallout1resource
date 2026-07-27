"""Build a deterministic resource index from an inventory manifest."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import string
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .inventory import ensure_within_workspace, sha256_file

INDEX_FILES = (
    "resources.jsonl",
    "derived.jsonl",
    "failures.jsonl",
    "collisions.csv",
    "summary.json",
    "index.json.sha256",
)


class ResourceIndexError(ValueError):
    """Raised when an inventory cannot safely produce a resource index."""


@dataclass(frozen=True)
class ResourceIndexPlan:
    inventory_path: Path
    output_directory: Path
    resources: tuple[dict[str, Any], ...]
    derived: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]
    collisions: tuple[dict[str, Any], ...]
    summary: dict[str, Any]


def _require_string(entry: dict[str, Any], field: str, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        raise ResourceIndexError(f"inventory entry {index} has invalid {field}")
    return value


def _normalize_internal_path(path: str) -> str:
    return path.replace("\\", "/").casefold()


def _resource_id(source_kind: str, source_name: str, internal_path: str) -> str:
    identity = "\0".join((source_kind, source_name, internal_path)).encode("utf-8")
    return f"sha256:{hashlib.sha256(identity).hexdigest()}"


def _load_inventory(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResourceIndexError(f"invalid inventory JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ResourceIndexError("inventory root must be an object")
    if document.get("schema_version") != 1:
        raise ResourceIndexError(
            f"unsupported inventory schema_version: {document.get('schema_version')!r}"
        )
    if not isinstance(document.get("entries"), list):
        raise ResourceIndexError("inventory entries must be an array")
    return document


def _manifest_paths(
    workspace: Path,
    extraction_manifests: list[Path | str] | tuple[Path | str, ...] | None,
) -> tuple[Path, ...]:
    candidates: list[Path | str]
    if extraction_manifests is None:
        candidates = list((workspace / "manifests").glob("extraction-*.json"))
    else:
        candidates = list(extraction_manifests)
    resolved: dict[str, Path] = {}
    for candidate in candidates:
        path = ensure_within_workspace(workspace, candidate)
        if not path.is_file():
            raise FileNotFoundError(f"extraction manifest does not exist: {path}")
        resolved[str(path).casefold()] = path
    return tuple(sorted(resolved.values(), key=lambda path: path.as_posix().casefold()))


def _load_extraction_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResourceIndexError(f"invalid extraction manifest {path.name}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ResourceIndexError(f"unsupported extraction manifest schema: {path.name}")
    if not isinstance(document.get("results"), list):
        raise ResourceIndexError(f"extraction manifest results must be an array: {path.name}")
    return document


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in string.hexdigits for character in value)
    )


def _merge_optional(existing: Any, incoming: Any, *, field: str, resource_id: str) -> Any:
    if existing is None:
        return incoming
    if incoming is None or existing == incoming:
        return existing
    raise ResourceIndexError(f"conflicting {field} for {resource_id}")


def _apply_extraction_manifests(
    workspace: Path,
    resources: list[dict[str, Any]],
    manifest_paths: tuple[Path, ...],
) -> dict[str, int]:
    by_identity = {
        (record["source_kind"], record["source_name"].casefold(), record["internal_path"]): record
        for record in resources
    }
    merged: dict[str, dict[str, Any]] = {}
    result_count = 0

    for manifest_path in manifest_paths:
        manifest = _load_extraction_manifest(manifest_path)
        manifest_relative = manifest_path.relative_to(workspace).as_posix()
        for index, result in enumerate(manifest["results"]):
            result_count += 1
            if not isinstance(result, dict):
                raise ResourceIndexError(f"{manifest_path.name} result {index} must be an object")
            archive_name = _require_string(result, "source_archive", index)
            internal_path = _require_string(result, "internal_path", index)
            identity = ("dat1", archive_name.casefold(), internal_path)
            record = by_identity.get(identity)
            if record is None:
                raise ResourceIndexError(
                    f"extraction result is absent from inventory: {archive_name}/{internal_path}"
                )
            size = result.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ResourceIndexError(f"{manifest_path.name} result {index} has invalid size")
            digest = result.get("sha256")
            if not _valid_sha256(digest):
                raise ResourceIndexError(f"{manifest_path.name} result {index} has invalid sha256")
            digest = digest.upper()
            output_value = _require_string(result, "output_path", index)
            output_path = ensure_within_workspace(workspace, Path(output_value))
            output_relative = output_path.relative_to(workspace).as_posix()
            compression_mode = result.get("compression_mode")
            source_offset = result.get("source_offset")
            stored_size = result.get("stored_size")

            for field, value in (("source_offset", source_offset), ("stored_size", stored_size)):
                if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool) or value < 0
                ):
                    raise ResourceIndexError(
                        f"{manifest_path.name} result {index} has invalid {field}"
                    )
            expected_archive = record["archive"]
            for result_field, archive_field, value in (
                ("source_offset", "offset", source_offset),
                ("stored_size", "stored_size", stored_size),
                ("compression_mode", "compression_mode", compression_mode),
            ):
                expected = expected_archive[archive_field]
                if value is not None and expected is not None and value != expected:
                    raise ResourceIndexError(
                        f"{result_field} disagrees with inventory for {record['resource_id']}"
                    )

            current = merged.get(record["resource_id"])
            if current is None:
                merged[record["resource_id"]] = {
                    "record": record,
                    "path": output_relative,
                    "size": size,
                    "sha256": digest,
                    "source_offset": source_offset,
                    "stored_size": stored_size,
                    "compression_mode": compression_mode,
                    "manifests": [manifest_relative],
                }
                continue
            for field, value in (("path", output_relative), ("size", size), ("sha256", digest)):
                if current[field] != value:
                    raise ResourceIndexError(
                        f"conflicting extracted {field} for {record['resource_id']}"
                    )
            current["source_offset"] = _merge_optional(
                current["source_offset"],
                source_offset,
                field="source_offset",
                resource_id=record["resource_id"],
            )
            current["stored_size"] = _merge_optional(
                current["stored_size"],
                stored_size,
                field="stored_size",
                resource_id=record["resource_id"],
            )
            current["compression_mode"] = _merge_optional(
                current["compression_mode"],
                compression_mode,
                field="compression_mode",
                resource_id=record["resource_id"],
            )
            current["manifests"].append(manifest_relative)

    extracted_count = 0
    stale_count = 0
    for item in merged.values():
        record = item.pop("record")
        path = workspace / item["path"]
        warnings: list[str] = []
        if not path.is_file():
            warnings.append("extracted_file_missing")
        elif path.stat().st_size != item["size"]:
            warnings.append("extracted_file_size_mismatch")
        elif sha256_file(path) != item["sha256"]:
            warnings.append("extracted_file_sha256_mismatch")
        status = "stale" if warnings else "extracted"
        if status == "extracted":
            extracted_count += 1
        else:
            stale_count += 1
        record["sha256"] = item["sha256"]
        record["extraction"] = {
            "status": status,
            "path": item["path"],
            "size": item["size"],
            "sha256": item["sha256"],
            "source_offset": item["source_offset"],
            "stored_size": item["stored_size"],
            "compression_mode": item["compression_mode"],
            "manifests": sorted(set(item["manifests"])),
        }
        record["warnings"].extend(warnings)

    return {
        "extraction_manifest_count": len(manifest_paths),
        "extraction_result_count": result_count,
        "extraction_duplicate_result_count": result_count - len(merged),
        "extracted_resource_count": extracted_count,
        "stale_extraction_count": stale_count,
    }


CONVERSION_FORMATS = {
    "Fallout MSG": "msg",
    "Fallout INT": "int",
    "Fallout FRM with PAL": "frm",
    "Fallout MAP/PRO/LST": "map",
    "Interplay ACM": "acm",
    "Interplay MVE": "mve",
}


def _conversion_metadata_paths(
    workspace: Path,
    conversion_metadata: list[Path | str] | tuple[Path | str, ...] | None,
) -> tuple[Path, ...]:
    if conversion_metadata is None:
        output_root = workspace / "output"
        candidates: list[Path | str] = (
            list(output_root.rglob("*.json")) if output_root.is_dir() else []
        )
    else:
        candidates = list(conversion_metadata)
    resolved: dict[str, Path] = {}
    for candidate in candidates:
        path = ensure_within_workspace(workspace, candidate)
        if not path.is_file():
            raise FileNotFoundError(f"conversion metadata does not exist: {path}")
        resolved[os.path.normcase(str(path))] = path
    return tuple(sorted(resolved.values(), key=lambda path: path.as_posix().casefold()))


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _source_path_map(
    workspace: Path,
    resources: list[dict[str, Any]],
    inventory: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}
    for record in resources:
        extraction_path = record["extraction"].get("path")
        if extraction_path:
            paths[_path_key(workspace / extraction_path)] = record

    loose_roots = [
        Path(source["path"])
        for source in inventory.get("sources", [])
        if isinstance(source, dict)
        and source.get("kind") == "loose"
        and isinstance(source.get("path"), str)
    ]
    for record in resources:
        if record["source_kind"] != "loose":
            continue
        for root in loose_roots:
            paths[_path_key(root / PurePosixPath(record["internal_path"]))] = record
    return paths


def _resolve_conversion_source(
    workspace: Path,
    source: Any,
    source_paths: dict[str, dict[str, Any]],
    *,
    metadata_name: str,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(source, dict):
        raise ResourceIndexError(f"conversion metadata has invalid source: {metadata_name}")
    path_value = source.get("path")
    size = source.get("size")
    digest = source.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        raise ResourceIndexError(f"conversion metadata has invalid source path: {metadata_name}")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ResourceIndexError(f"conversion metadata has invalid source size: {metadata_name}")
    if not _valid_sha256(digest):
        raise ResourceIndexError(f"conversion metadata has invalid source sha256: {metadata_name}")
    digest = digest.upper()
    source_path = Path(path_value).resolve(strict=False)
    record = source_paths.get(_path_key(source_path))
    if record is None:
        raise ResourceIndexError(
            f"conversion source is absent from inventory/extractions: {path_value}"
        )
    if record["size"] != size:
        raise ResourceIndexError(
            f"conversion source size disagrees with inventory: {metadata_name}"
        )
    if record["sha256"] is not None and record["sha256"] != digest:
        raise ResourceIndexError(
            f"conversion source hash disagrees with extraction: {metadata_name}"
        )
    record["sha256"] = digest

    issues: list[str] = []
    if not source_path.is_file():
        issues.append("conversion_source_missing")
    elif source_path.stat().st_size != size:
        issues.append("conversion_source_size_mismatch")
    elif sha256_file(source_path) != digest:
        issues.append("conversion_source_sha256_mismatch")
    return record, issues


def _embedded_derivatives(value: Any, found: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        path = value.get("path")
        digest = value.get("sha256")
        if isinstance(path, str) and _valid_sha256(digest):
            size = value.get("size")
            if size is not None and (
                not isinstance(size, int) or isinstance(size, bool) or size < 0
            ):
                raise ResourceIndexError(f"invalid derived size for {path}")
            candidate = {"expected_sha256": digest.upper(), "expected_size": size}
            previous = found.get(path)
            if previous is not None and previous != candidate:
                raise ResourceIndexError(f"conflicting derived metadata for {path}")
            found[path] = candidate
        for child in value.values():
            _embedded_derivatives(child, found)
    elif isinstance(value, list):
        for child in value:
            _embedded_derivatives(child, found)


def _checksum_expected(metadata_path: Path) -> str | None:
    checksum_path = metadata_path.with_suffix(metadata_path.suffix + ".sha256")
    if not checksum_path.is_file():
        return None
    parts = checksum_path.read_text(encoding="ascii").strip().split("  ", 1)
    if len(parts) != 2 or not _valid_sha256(parts[0]) or parts[1] != metadata_path.name:
        raise ResourceIndexError(f"invalid metadata checksum file: {checksum_path}")
    return parts[0].upper()


def _derived_role(path: Path, metadata_path: Path) -> str:
    name = path.name.casefold()
    relative_parts = path.relative_to(metadata_path.parent).parts
    if path == metadata_path:
        return "metadata_json"
    if name.endswith(".json.sha256"):
        return "checksum"
    if ".frames" in relative_parts[0].casefold() and name.endswith(".png"):
        return "png_frame"
    if name.endswith(".palette.png"):
        return "palette_preview_png"
    if name.endswith(".poster.png"):
        return "poster_png"
    if name.endswith(".preview.mp4"):
        return "preview_mp4"
    if name.endswith(".audio.wav") or name.endswith(".wav"):
        return "wav"
    if name.endswith(".messages.csv"):
        return "message_links_csv"
    if name.endswith(".objects.csv"):
        return "map_objects_csv"
    if name.endswith(".segments.csv"):
        return "segments_csv"
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".disasm.txt"):
        return "disassembly_text"
    if name.endswith(".png"):
        return "png"
    return "other"


def _derived_id(resource_id: str, relative_path: str) -> str:
    value = f"{resource_id}\0{relative_path}".encode()
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _failure_id(stage: str, resource_id: str, code: str, context: str) -> str:
    value = "\0".join((stage, resource_id, code, context)).encode("utf-8")
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _build_failures(
    resources: tuple[dict[str, Any], ...],
    derived: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    failures: list[dict[str, Any]] = []
    for resource in resources:
        for code in sorted(set(resource["warnings"])):
            if code == "source_collision" or code.startswith("derived_file_"):
                continue
            if code.startswith("extracted_file_"):
                stage = "extraction"
                context = resource["extraction"].get("path") or resource["internal_path"]
                retryable = True
            elif code.startswith("conversion_source_") or code.startswith(
                "palette_conversion_source_"
            ):
                stage = "conversion"
                context = resource["conversion"].get("metadata_path") or resource["internal_path"]
                retryable = True
            else:
                stage = "inventory"
                context = resource["internal_path"]
                retryable = False
            failures.append(
                {
                    "schema_version": 1,
                    "failure_id": _failure_id(stage, resource["resource_id"], code, context),
                    "resource_id": resource["resource_id"],
                    "derived_id": None,
                    "stage": stage,
                    "status": "stale" if retryable else "failed",
                    "code": code,
                    "context": context,
                    "retryable": retryable,
                }
            )
    for item in derived:
        for code in item["validation"]["issues"]:
            context = item["relative_path"]
            failures.append(
                {
                    "schema_version": 1,
                    "failure_id": _failure_id("conversion", item["resource_id"], code, context),
                    "resource_id": item["resource_id"],
                    "derived_id": item["derived_id"],
                    "stage": "conversion",
                    "status": "stale",
                    "code": code,
                    "context": context,
                    "retryable": True,
                }
            )
    return tuple(sorted(failures, key=lambda item: item["failure_id"]))


def _input_records(workspace: Path, paths: tuple[Path, ...]) -> list[dict[str, str]]:
    return [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def _batch_id(input_descriptor: dict[str, Any]) -> str:
    canonical = json.dumps(input_descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _apply_conversion_metadata(
    workspace: Path,
    resources: list[dict[str, Any]],
    inventory: dict[str, Any],
    metadata_paths: tuple[Path, ...],
) -> tuple[tuple[dict[str, Any], ...], dict[str, int]]:
    source_paths = _source_path_map(workspace, resources, inventory)
    derived_records: list[dict[str, Any]] = []
    claimed_paths: dict[str, str] = {}
    converted_count = 0
    stale_count = 0

    for metadata_path in metadata_paths:
        try:
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ResourceIndexError(f"invalid conversion metadata {metadata_path}: {exc}") from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise ResourceIndexError(f"unsupported conversion metadata schema: {metadata_path}")
        format_name = document.get("format")
        conversion_format = CONVERSION_FORMATS.get(format_name)
        if conversion_format is None:
            raise ResourceIndexError(
                f"unsupported conversion format {format_name!r}: {metadata_path}"
            )
        generator = document.get("generator")
        if not isinstance(generator, dict) or not isinstance(generator.get("name"), str):
            raise ResourceIndexError(f"conversion metadata has invalid generator: {metadata_path}")
        source_record, source_issues = _resolve_conversion_source(
            workspace,
            document.get("source"),
            source_paths,
            metadata_name=metadata_path.name,
        )
        if source_record["conversion"]["status"] != "not_selected":
            raise ResourceIndexError(
                f"multiple conversion metadata files claim {source_record['resource_id']}"
            )

        input_resource_ids = [source_record["resource_id"]]
        palette = document.get("palette")
        if isinstance(palette, dict) and "source" in palette:
            palette_record, palette_issues = _resolve_conversion_source(
                workspace,
                palette["source"],
                source_paths,
                metadata_name=metadata_path.name,
            )
            input_resource_ids.append(palette_record["resource_id"])
            source_issues.extend(f"palette_{issue}" for issue in palette_issues)

        expected: dict[str, dict[str, Any]] = {}
        _embedded_derivatives(document.get("derived"), expected)
        metadata_relative = metadata_path.relative_to(workspace).as_posix()
        metadata_expected = _checksum_expected(metadata_path)
        expected[metadata_relative] = {
            "expected_sha256": metadata_expected,
            "expected_size": metadata_path.stat().st_size,
        }
        checksum_path = metadata_path.with_suffix(metadata_path.suffix + ".sha256")
        if checksum_path.is_file():
            checksum_relative = checksum_path.relative_to(workspace).as_posix()
            expected.setdefault(checksum_relative, {"expected_sha256": None, "expected_size": None})

        first_component_prefix = metadata_path.stem + "."
        for candidate in metadata_path.parent.rglob("*"):
            if not candidate.is_file():
                continue
            first_component = candidate.relative_to(metadata_path.parent).parts[0]
            if first_component == metadata_path.stem or first_component.startswith(
                first_component_prefix
            ):
                relative = candidate.relative_to(workspace).as_posix()
                expected.setdefault(relative, {"expected_sha256": None, "expected_size": None})

        conversion_issues = list(source_issues)
        metadata_derived: list[dict[str, Any]] = []
        for relative_path, expectation in sorted(expected.items()):
            candidate = ensure_within_workspace(workspace, relative_path)
            owner = claimed_paths.get(relative_path.casefold())
            if owner is not None and owner != source_record["resource_id"]:
                raise ResourceIndexError(
                    f"derived path claimed by multiple resources: {relative_path}"
                )
            claimed_paths[relative_path.casefold()] = source_record["resource_id"]
            issues: list[str] = []
            actual_size: int | None = None
            actual_digest: str | None = None
            if not candidate.is_file():
                issues.append("derived_file_missing")
            else:
                actual_size = candidate.stat().st_size
                actual_digest = sha256_file(candidate)
                if (
                    expectation["expected_size"] is not None
                    and actual_size != expectation["expected_size"]
                ):
                    issues.append("derived_file_size_mismatch")
                if (
                    expectation["expected_sha256"] is not None
                    and actual_digest != expectation["expected_sha256"]
                ):
                    issues.append("derived_file_sha256_mismatch")
            status = "stale" if issues else "valid"
            conversion_issues.extend(issues)
            role = _derived_role(candidate, metadata_path)
            derived_record = {
                "schema_version": 1,
                "derived_id": _derived_id(source_record["resource_id"], relative_path),
                "resource_id": source_record["resource_id"],
                "input_resource_ids": sorted(set(input_resource_ids)),
                "role": role,
                "relative_path": relative_path,
                "size": actual_size,
                "sha256": actual_digest,
                "generator": generator["name"],
                "generator_version": generator.get("version"),
                "generator_schema_version": document["schema_version"],
                "lossless_from_source": role != "preview_mp4",
                "metadata_path": metadata_relative,
                "validation": {"status": status, "issues": issues},
            }
            derived_records.append(derived_record)
            metadata_derived.append(
                {"derived_id": derived_record["derived_id"], "role": role, "path": relative_path}
            )

        conversion_status = "stale" if conversion_issues else "converted"
        if conversion_status == "converted":
            converted_count += 1
        else:
            stale_count += 1
        source_record["conversion"] = {
            "status": conversion_status,
            "format": conversion_format,
            "schema_version": document["schema_version"],
            "metadata_path": metadata_relative,
            "generator": generator["name"],
            "generator_version": generator.get("version"),
            "derived_count": len(metadata_derived),
        }
        source_record["warnings"].extend(sorted(set(conversion_issues)))

    derived_tuple = tuple(
        sorted(
            derived_records,
            key=lambda item: (item["resource_id"], item["relative_path"].casefold()),
        )
    )
    return derived_tuple, {
        "conversion_metadata_count": len(metadata_paths),
        "converted_resource_count": converted_count,
        "stale_conversion_count": stale_count,
        "derived_file_count": len(derived_tuple),
        "stale_derived_file_count": sum(
            1 for record in derived_tuple if record["validation"]["status"] == "stale"
        ),
    }


def build_resource_index(
    workspace: Path | str,
    inventory: Path | str = Path("manifests/inventory.json"),
    output: Path | str = Path("index"),
    extraction_manifests: list[Path | str] | tuple[Path | str, ...] | None = None,
    conversion_metadata: list[Path | str] | tuple[Path | str, ...] | None = None,
) -> ResourceIndexPlan:
    """Validate an inventory and build an in-memory, write-free index plan."""
    workspace_path = Path(workspace).resolve()
    inventory_path = ensure_within_workspace(workspace_path, inventory)
    if not inventory_path.is_file():
        raise FileNotFoundError(f"inventory does not exist: {inventory_path}")
    output_directory = ensure_within_workspace(
        workspace_path, Path(output) / "resources.jsonl"
    ).parent
    if output_directory == workspace_path:
        raise ResourceIndexError("index output must be a directory below workspace")

    manifest = _load_inventory(inventory_path)
    prepared: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for index, entry in enumerate(manifest["entries"]):
        if not isinstance(entry, dict):
            raise ResourceIndexError(f"inventory entry {index} must be an object")
        source_kind = _require_string(entry, "source_kind", index)
        source_name = _require_string(entry, "source_name", index)
        internal_path = _require_string(entry, "internal_path", index)
        resource_type = _require_string(entry, "type", index)
        size = entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ResourceIndexError(f"inventory entry {index} has invalid size")
        identity = (source_kind, source_name, internal_path)
        if identity in identities:
            raise ResourceIndexError(
                f"duplicate source identity: {source_kind}/{source_name}/{internal_path}"
            )
        identities.add(identity)

        normalized_path = _normalize_internal_path(internal_path)
        path_issues = entry.get("path_issues", [])
        if not isinstance(path_issues, list) or not all(
            isinstance(item, str) for item in path_issues
        ):
            raise ResourceIndexError(f"inventory entry {index} has invalid path_issues")
        warnings = list(path_issues)
        record = {
            "schema_version": 1,
            "resource_id": _resource_id(source_kind, source_name, internal_path),
            "source_kind": source_kind,
            "source_name": source_name,
            "internal_path": internal_path,
            "normalized_path": normalized_path,
            "resource_type": resource_type,
            "extension": PurePosixPath(internal_path.replace("\\", "/")).suffix.upper(),
            "size": size,
            "sha256": entry.get("sha256"),
            "archive": {
                "stored_size": entry.get("stored_size"),
                "offset": entry.get("offset"),
                "compression_mode": entry.get("compression_mode"),
                "compression": entry.get("compression"),
            },
            "extraction": {"status": "not_selected", "path": None},
            "conversion": {"status": "not_selected", "format": None, "schema_version": None},
            "effective_source": None,
            "warnings": warnings,
        }
        prepared.append(record)
        grouped[normalized_path].append(record)

    manifest_paths = _manifest_paths(workspace_path, extraction_manifests)
    extraction_summary = _apply_extraction_manifests(workspace_path, prepared, manifest_paths)
    metadata_paths = _conversion_metadata_paths(workspace_path, conversion_metadata)
    derived, conversion_summary = _apply_conversion_metadata(
        workspace_path, prepared, manifest, metadata_paths
    )

    collisions: list[dict[str, Any]] = []
    for normalized_path, candidates in grouped.items():
        if len(candidates) == 1:
            candidates[0]["effective_source"] = True
            continue
        for candidate in candidates:
            candidate["warnings"].append("source_collision")
        hashes = [candidate["sha256"] for candidate in candidates]
        content_identical = len(set(hashes)) == 1 if all(hashes) else None
        collisions.append(
            {
                "normalized_path": normalized_path,
                "candidate_count": len(candidates),
                "content_identical": content_identical,
                "suggested_effective_source": None,
                "decision_basis": "manual_review_required",
                "candidates": [
                    {
                        "resource_id": candidate["resource_id"],
                        "source_kind": candidate["source_kind"],
                        "source_name": candidate["source_name"],
                        "internal_path": candidate["internal_path"],
                        "size": candidate["size"],
                        "sha256": candidate["sha256"],
                    }
                    for candidate in sorted(
                        candidates,
                        key=lambda item: (
                            item["source_kind"],
                            item["source_name"].casefold(),
                            item["internal_path"],
                        ),
                    )
                ],
            }
        )

    resources = tuple(
        sorted(
            prepared,
            key=lambda item: (
                item["normalized_path"],
                item["source_kind"],
                item["source_name"].casefold(),
                item["internal_path"],
            ),
        )
    )
    failures = _build_failures(resources, derived)
    collisions_tuple = tuple(sorted(collisions, key=lambda item: item["normalized_path"]))
    type_counts = Counter(record["resource_type"] for record in resources)
    source_counts = Counter(
        f"{record['source_kind']}:{record['source_name']}" for record in resources
    )
    input_descriptor = {
        "inventory": {
            "path": inventory_path.relative_to(workspace_path).as_posix(),
            "sha256": sha256_file(inventory_path),
        },
        "extraction_manifests": _input_records(workspace_path, manifest_paths),
        "conversion_metadata": _input_records(workspace_path, metadata_paths),
        "generator": {"name": "fallout1resource", "version": __version__},
        "index_schema_version": 1,
    }
    failure_counts = Counter(item["stage"] for item in failures)
    summary = {
        "schema_version": 1,
        "batch_id": _batch_id(input_descriptor),
        "generator": input_descriptor["generator"],
        "input": {
            "inventory": input_descriptor["inventory"]["path"],
            "inventory_schema_version": manifest["schema_version"],
            "inventory_sha256": input_descriptor["inventory"]["sha256"],
            "inventory_generated_at_utc": manifest.get("generated_at_utc"),
            "extraction_manifests": input_descriptor["extraction_manifests"],
            "conversion_metadata": input_descriptor["conversion_metadata"],
        },
        "resource_count": len(resources),
        "collision_path_count": len(collisions_tuple),
        "collision_candidate_count": sum(item["candidate_count"] for item in collisions_tuple),
        "unresolved_effective_source_count": sum(
            1 for record in resources if record["effective_source"] is None
        ),
        "unsafe_path_count": sum(
            1
            for record in resources
            if any(warning != "source_collision" for warning in record["warnings"])
        ),
        "type_counts": dict(sorted(type_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "failure_count": len(failures),
        "failure_counts_by_stage": dict(sorted(failure_counts.items())),
        **extraction_summary,
        **conversion_summary,
    }
    return ResourceIndexPlan(
        inventory_path=inventory_path,
        output_directory=output_directory,
        resources=resources,
        derived=derived,
        failures=failures,
        collisions=collisions_tuple,
        summary=summary,
    )


def _render_resources(resources: tuple[dict[str, Any], ...]) -> bytes:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in resources
    ).encode("utf-8")


def _render_derived(derived: tuple[dict[str, Any], ...]) -> bytes:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in derived
    ).encode("utf-8")


def _render_failures(failures: tuple[dict[str, Any], ...]) -> bytes:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in failures
    ).encode("utf-8")


def _render_collisions(collisions: tuple[dict[str, Any], ...]) -> bytes:
    text = io.StringIO(newline="")
    fields = [
        "normalized_path",
        "candidate_count",
        "content_identical",
        "suggested_effective_source",
        "decision_basis",
        "candidates_json",
    ]
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for collision in collisions:
        writer.writerow(
            {
                **{field: collision[field] for field in fields[:-1]},
                "candidates_json": json.dumps(
                    collision["candidates"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    return ("\ufeff" + text.getvalue()).encode("utf-8")


def _render_outputs(plan: ResourceIndexPlan) -> dict[str, bytes]:
    outputs = {
        "resources.jsonl": _render_resources(plan.resources),
        "derived.jsonl": _render_derived(plan.derived),
        "failures.jsonl": _render_failures(plan.failures),
        "collisions.csv": _render_collisions(plan.collisions),
        "summary.json": (
            json.dumps(plan.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }
    checksum_lines = []
    for name in sorted(outputs):
        checksum_lines.append(f"{hashlib.sha256(outputs[name]).hexdigest().upper()}  {name}\n")
    outputs["index.json.sha256"] = "".join(checksum_lines).encode("ascii")
    return outputs


def write_resource_index(plan: ResourceIndexPlan, *, overwrite: bool = False) -> tuple[Path, ...]:
    """Write the complete index by swapping a staged directory into place."""
    output_directory = plan.output_directory
    parent = output_directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output_directory.exists():
        if not output_directory.is_dir():
            raise ResourceIndexError(f"index output is not a directory: {output_directory}")
        existing = {item.name for item in output_directory.iterdir()}
        unexpected = existing.difference(INDEX_FILES)
        if unexpected:
            raise ResourceIndexError(
                f"index directory contains unmanaged files: {', '.join(sorted(unexpected))}"
            )
        if existing and not overwrite:
            raise FileExistsError(f"index already exists: {output_directory}")

    outputs = _render_outputs(plan)
    stage = parent / f".{output_directory.name}.stage-{uuid.uuid4().hex}"
    backup = parent / f".{output_directory.name}.backup-{uuid.uuid4().hex}"
    try:
        stage.mkdir()
        for name, data in outputs.items():
            target = stage / name
            with target.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

        if output_directory.exists():
            if not any(output_directory.iterdir()):
                output_directory.rmdir()
            else:
                os.replace(output_directory, backup)
        try:
            os.replace(stage, output_directory)
        except Exception:
            if backup.exists() and not output_directory.exists():
                os.replace(backup, output_directory)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup.exists() and output_directory.exists():
            shutil.rmtree(backup)
    return tuple(output_directory / name for name in INDEX_FILES)
