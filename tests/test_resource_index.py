from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fallout1resource.resource_index import (
    ResourceIndexError,
    build_resource_index,
    write_resource_index,
)


class ResourceIndexTests(unittest.TestCase):
    def _inventory(self, workspace: Path, entries: list[dict[str, object]]) -> Path:
        path = workspace / "manifests" / "inventory.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at_utc": "2026-07-27T00:00:00+00:00",
                    "entries": entries,
                }
            ),
            encoding="utf-8",
        )
        return path

    def _extraction_manifest(
        self,
        workspace: Path,
        results: list[dict[str, object]],
        name: str = "extraction-test.json",
    ) -> Path:
        path = workspace / "manifests" / name
        path.write_text(json.dumps({"schema_version": 1, "results": results}), encoding="utf-8")
        return path

    def _extraction_result(
        self,
        workspace: Path,
        *,
        digest: str,
        offset: int | None = 10,
    ) -> dict[str, object]:
        return {
            "source_archive": "MASTER.DAT",
            "internal_path": "TEXT/TEST.MSG",
            "output_path": str(workspace / "raw" / "master" / "TEXT" / "TEST.MSG"),
            "size": 12,
            "sha256": digest,
            "source_offset": offset,
            "stored_size": 12 if offset is not None else None,
            "compression_mode": "0x20",
        }

    def _converted_acm(self, workspace: Path, *, tamper_wav: bool = False) -> None:
        source = workspace / "raw" / "master" / "TEXT" / "TEST.MSG"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"hello world!")
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest().upper()
        self._extraction_manifest(
            workspace,
            [self._extraction_result(workspace, digest=source_digest, offset=None)],
        )
        output = workspace / "output" / "audio" / "TEST"
        output.mkdir(parents=True)
        wav = output / "TEST.wav"
        wav.write_bytes(b"wave")
        wav_digest = hashlib.sha256(wav.read_bytes()).hexdigest().upper()
        metadata = output / "TEST.json"
        metadata.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "format": "Interplay ACM",
                    "generator": {"name": "fallout1resource", "version": "0.1.0"},
                    "source": {"path": str(source), "size": 12, "sha256": source_digest},
                    "derived": {
                        "wav": {
                            "path": "output/audio/TEST/TEST.wav",
                            "size": 4,
                            "sha256": wav_digest,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        metadata_digest = hashlib.sha256(metadata.read_bytes()).hexdigest().upper()
        (output / "TEST.json.sha256").write_text(
            f"{metadata_digest}  TEST.json\n", encoding="ascii"
        )
        if tamper_wav:
            wav.write_bytes(b"changed")

    @staticmethod
    def _entry(source: str, path: str, sha256: str | None = None) -> dict[str, object]:
        return {
            "source_kind": "loose" if source == "DATA" else "dat1",
            "source_name": source,
            "internal_path": path,
            "type": "text",
            "size": 12,
            "stored_size": 12,
            "offset": None,
            "compression_mode": None,
            "compression": "none",
            "sha256": sha256,
            "path_issues": [],
        }

    def test_build_is_write_free_and_ids_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            first = build_resource_index(workspace)
            second = build_resource_index(workspace)
            self.assertFalse((workspace / "index").exists())
            self.assertEqual(first.resources[0]["resource_id"], second.resources[0]["resource_id"])
            self.assertTrue(first.resources[0]["effective_source"])

    def test_case_insensitive_collision_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(
                workspace,
                [
                    self._entry("MASTER.DAT", "TEXT/DIALOG/HAROLD.MSG"),
                    self._entry("DATA", "text/dialog/harold.msg"),
                ],
            )
            plan = build_resource_index(workspace)
            self.assertEqual(len(plan.collisions), 1)
            self.assertEqual(plan.summary["collision_candidate_count"], 2)
            self.assertTrue(all(item["effective_source"] is None for item in plan.resources))
            self.assertTrue(all("source_collision" in item["warnings"] for item in plan.resources))

    def test_writes_complete_index_and_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            paths = write_resource_index(build_resource_index(workspace))
            self.assertTrue(all(path.is_file() for path in paths))
            checksum_lines = (
                (workspace / "index" / "index.json.sha256").read_text(encoding="ascii").splitlines()
            )
            for line in checksum_lines:
                digest, name = line.split("  ", 1)
                content = (workspace / "index" / name).read_bytes()
                self.assertEqual(digest, hashlib.sha256(content).hexdigest().upper())

    def test_merges_duplicate_extractions_and_verifies_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            entry = self._entry("MASTER.DAT", "TEXT/TEST.MSG")
            entry.update({"offset": 10, "compression_mode": "0x20"})
            self._inventory(workspace, [entry])
            output = workspace / "raw" / "master" / "TEXT" / "TEST.MSG"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"hello world!")
            digest = hashlib.sha256(output.read_bytes()).hexdigest().upper()
            self._extraction_manifest(
                workspace,
                [self._extraction_result(workspace, digest=digest, offset=None)],
                "extraction-a.json",
            )
            self._extraction_manifest(
                workspace,
                [self._extraction_result(workspace, digest=digest, offset=10)],
                "extraction-b.json",
            )
            plan = build_resource_index(workspace)
            extraction = plan.resources[0]["extraction"]
            self.assertEqual(extraction["status"], "extracted")
            self.assertEqual(extraction["source_offset"], 10)
            self.assertEqual(len(extraction["manifests"]), 2)
            self.assertEqual(plan.summary["extraction_duplicate_result_count"], 1)

    def test_marks_missing_extraction_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            digest = "A" * 64
            self._extraction_manifest(
                workspace, [self._extraction_result(workspace, digest=digest, offset=None)]
            )
            plan = build_resource_index(workspace)
            self.assertEqual(plan.resources[0]["extraction"]["status"], "stale")
            self.assertIn("extracted_file_missing", plan.resources[0]["warnings"])
            self.assertEqual(len(plan.failures), 1)
            self.assertEqual(plan.failures[0]["stage"], "extraction")

    def test_rejects_conflicting_extraction_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            self._extraction_manifest(
                workspace,
                [self._extraction_result(workspace, digest="A" * 64, offset=None)],
                "extraction-a.json",
            )
            self._extraction_manifest(
                workspace,
                [self._extraction_result(workspace, digest="B" * 64, offset=None)],
                "extraction-b.json",
            )
            with self.assertRaises(ResourceIndexError):
                build_resource_index(workspace)

    def test_rejects_extraction_output_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            result = self._extraction_result(workspace, digest="A" * 64, offset=None)
            result["output_path"] = str(root / "outside.msg")
            self._extraction_manifest(workspace, [result])
            with self.assertRaises(ValueError):
                build_resource_index(workspace)

    def test_indexes_and_validates_every_conversion_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            self._converted_acm(workspace)
            plan = build_resource_index(workspace)
            self.assertEqual(plan.summary["converted_resource_count"], 1)
            self.assertEqual(plan.summary["derived_file_count"], 3)
            self.assertEqual(plan.resources[0]["conversion"]["status"], "converted")
            self.assertEqual(
                {item["role"] for item in plan.derived},
                {"metadata_json", "checksum", "wav"},
            )
            self.assertTrue(all(item["validation"]["status"] == "valid" for item in plan.derived))

    def test_marks_tampered_derived_file_and_conversion_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            self._converted_acm(workspace, tamper_wav=True)
            plan = build_resource_index(workspace)
            wav = next(item for item in plan.derived if item["role"] == "wav")
            self.assertEqual(wav["validation"]["status"], "stale")
            self.assertEqual(plan.resources[0]["conversion"]["status"], "stale")
            self.assertEqual(plan.summary["stale_derived_file_count"], 1)
            self.assertEqual(plan.summary["failure_count"], 2)
            self.assertTrue(all(item["derived_id"] == wav["derived_id"] for item in plan.failures))

    def test_rejects_conversion_source_not_in_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            output = workspace / "output" / "audio" / "TEST"
            output.mkdir(parents=True)
            outside = workspace / "raw" / "master" / "OTHER.MSG"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(b"hello world!")
            digest = hashlib.sha256(outside.read_bytes()).hexdigest().upper()
            (output / "TEST.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "format": "Interplay ACM",
                        "generator": {"name": "fallout1resource", "version": "0.1.0"},
                        "source": {"path": str(outside), "size": 12, "sha256": digest},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ResourceIndexError):
                build_resource_index(workspace)

    def test_batch_id_changes_only_when_an_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            inventory = self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            first = build_resource_index(workspace).summary["batch_id"]
            second = build_resource_index(workspace).summary["batch_id"]
            self.assertEqual(first, second)
            document = json.loads(inventory.read_text(encoding="utf-8"))
            document["generated_at_utc"] = "2026-07-28T00:00:00+00:00"
            inventory.write_text(json.dumps(document), encoding="utf-8")
            third = build_resource_index(workspace).summary["batch_id"]
            self.assertNotEqual(first, third)

    def test_refuses_existing_index_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            plan = build_resource_index(workspace)
            write_resource_index(plan)
            original = (workspace / "index" / "resources.jsonl").read_bytes()
            with self.assertRaises(FileExistsError):
                write_resource_index(plan)
            self.assertEqual((workspace / "index" / "resources.jsonl").read_bytes(), original)

    def test_refuses_unmanaged_files_even_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            index_dir = workspace / "index"
            index_dir.mkdir()
            (index_dir / "notes.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(ResourceIndexError):
                write_resource_index(build_resource_index(workspace), overwrite=True)
            self.assertEqual((index_dir / "notes.txt").read_text(encoding="utf-8"), "keep")

    def test_failed_directory_swap_restores_previous_complete_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._inventory(workspace, [self._entry("MASTER.DAT", "TEXT/TEST.MSG")])
            plan = build_resource_index(workspace)
            write_resource_index(plan)
            original = {
                path.name: path.read_bytes()
                for path in (workspace / "index").iterdir()
                if path.is_file()
            }
            real_replace = __import__("os").replace
            calls = 0

            def fail_second_replace(source: object, target: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated interrupted directory swap")
                real_replace(source, target)

            with patch(
                "fallout1resource.resource_index.os.replace", side_effect=fail_second_replace
            ):
                with self.assertRaises(OSError):
                    write_resource_index(plan, overwrite=True)
            restored = {
                path.name: path.read_bytes()
                for path in (workspace / "index").iterdir()
                if path.is_file()
            }
            self.assertEqual(restored, original)
            self.assertFalse(any(path.name.startswith(".index.") for path in workspace.iterdir()))

    def test_rejects_output_escape_and_invalid_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            inventory = self._inventory(workspace, [])
            with self.assertRaises(ValueError):
                build_resource_index(workspace, output=root / "outside")
            inventory.write_text('{"schema_version": 2, "entries": []}', encoding="utf-8")
            with self.assertRaises(ResourceIndexError):
                build_resource_index(workspace)


if __name__ == "__main__":
    unittest.main()
