from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fallout1resource.msg_batch import build_msg_batch_plan, execute_msg_batch


class MsgBatchTests(unittest.TestCase):
    def _source(self, workspace: Path, name: str, content: bytes = b"{1}{}{hello}") -> Path:
        path = workspace / "raw" / "master" / "TEXT" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_plan_is_write_free_and_uses_source_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            source = self._source(workspace, "HELLO.MSG")

            plan = build_msg_batch_plan(workspace, sources=["master"])

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())
            self.assertEqual(plan[0].output.as_posix(), "output/text/master/TEXT/HELLO.json")
            self.assertFalse((workspace / "output").exists())

    def test_plans_loose_data_without_copying_and_excludes_savegames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "Fallout"
            data = game_dir / "DATA"
            dialog = data / "TEXT" / "ENGLISH" / "DIALOG"
            dialog.mkdir(parents=True)
            source = dialog / "HAROLD.MSG"
            source.write_bytes(b"{1}{}{hello}")
            save = data / "SAVEGAME" / "SLOT01" / "IGNORED.MSG"
            save.parent.mkdir(parents=True)
            save.write_bytes(b"{2}{}{private}")
            workspace = root / "workspace"

            plan = build_msg_batch_plan(workspace, sources=["data"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())
            self.assertEqual(
                plan[0].output.as_posix(),
                "output/text/data/TEXT/ENGLISH/DIALOG/HAROLD.json",
            )
            self.assertFalse(workspace.exists())

    def test_converts_loose_data_and_records_absolute_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "Fallout"
            source = game_dir / "DATA" / "TEXT" / "HELLO.MSG"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"{1}{}{hello}")
            workspace = root / "workspace"
            plan = build_msg_batch_plan(workspace, sources=["data"], game_dir=game_dir)

            result = execute_msg_batch(plan, workspace)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual((result.converted, result.failed), (1, 0))
            self.assertEqual(manifest["results"][0]["source_path"], str(source.resolve()))

    def test_continues_after_failure_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._source(workspace, "GOOD.MSG")
            self._source(workspace, "BAD.MSG", b"{1}{}{unterminated")

            result = execute_msg_batch(build_msg_batch_plan(workspace), workspace)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual((result.converted, result.failed), (1, 1))
            self.assertEqual(manifest["summary"]["failed"], 1)
            statuses = {item["internal_path"]: item["status"] for item in manifest["results"]}
            self.assertEqual(statuses["TEXT/GOOD.MSG"], "converted")
            self.assertEqual(statuses["TEXT/BAD.MSG"], "failed")

    def test_rerun_skips_only_verified_current_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._source(workspace, "HELLO.MSG")
            plan = build_msg_batch_plan(workspace)
            execute_msg_batch(plan, workspace)

            result = execute_msg_batch(plan, workspace)

            self.assertEqual((result.converted, result.skipped_verified, result.failed), (0, 1, 0))

    def test_master_uses_reversible_western_encoding_instead_of_cjk_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._source(workspace, "FRENCH.MSG", b"{1}{}{Caf\xe9}")

            execute_msg_batch(build_msg_batch_plan(workspace), workspace)
            payload = json.loads(
                (workspace / "output/text/master/TEXT/FRENCH.json").read_text(encoding="utf-8")
            )

            self.assertEqual(payload["entries"][0]["text"], "Café")
            self.assertEqual(payload["summary"]["encoding"], "iso8859-1")
            self.assertEqual(payload["decoding"]["method"], "explicit")

    def test_tampered_csv_fails_without_overwrite_and_recovers_with_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._source(workspace, "HELLO.MSG")
            plan = build_msg_batch_plan(workspace)
            execute_msg_batch(plan, workspace)
            csv_path = workspace / "output/text/master/TEXT/HELLO.csv"
            csv_path.write_text("tampered", encoding="utf-8")

            failed = execute_msg_batch(plan, workspace)
            recovered = execute_msg_batch(plan, workspace, overwrite=True)

            self.assertEqual((failed.converted, failed.failed), (0, 1))
            self.assertEqual((recovered.converted, recovered.failed), (1, 0))
            self.assertNotEqual(csv_path.read_text(encoding="utf-8"), "tampered")


if __name__ == "__main__":
    unittest.main()
