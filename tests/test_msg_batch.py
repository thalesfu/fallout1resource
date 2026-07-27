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
