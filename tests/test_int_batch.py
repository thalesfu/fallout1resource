from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_int_script import build_int

from fallout1resource.int_batch import build_int_batch_plan, execute_int_batch


class IntBatchTests(unittest.TestCase):
    def _script(self, workspace: Path, name: str = "TEST.INT") -> Path:
        path = workspace / "raw" / "master" / "SCRIPTS" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        build_int(path)
        return path

    def test_plan_prefers_effective_loose_message_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = self._script(workspace)
            master_msg = workspace / "raw/master/TEXT/ENGLISH/DIALOG/TEST.MSG"
            master_msg.parent.mkdir(parents=True)
            master_msg.write_bytes(b"{100}{}{master}")
            game_dir = root / "Fallout"
            data_msg = game_dir / "DATA/TEXT/ENGLISH/DIALOG/TEST.MSG"
            data_msg.parent.mkdir(parents=True)
            data_msg.write_bytes(b"{100}{}{loose}")

            plan = build_int_batch_plan(workspace, sources=["master"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())
            self.assertEqual(plan[0].message_path, data_msg.resolve())
            self.assertEqual(plan[0].message_source_name, "data")
            self.assertEqual(plan[0].output.as_posix(), "output/scripts/master/SCRIPTS/TEST.json")
            self.assertFalse((workspace / "output").exists())

    def test_continues_after_failure_and_records_message_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._script(workspace)
            bad = workspace / "raw/master/SCRIPTS/BAD.INT"
            bad.write_bytes(b"invalid")
            msg = workspace / "raw/master/TEXT/ENGLISH/DIALOG/TEST.MSG"
            msg.parent.mkdir(parents=True)
            msg.write_bytes(b"{100}{}{linked}")

            result = execute_int_batch(build_int_batch_plan(workspace), workspace)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual((result.converted, result.failed), (1, 1))
            converted = next(item for item in manifest["results"] if item["status"] == "converted")
            self.assertEqual(converted["linked_message_references"], 1)

    def test_rerun_skips_verified_outputs_and_tamper_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._script(workspace)
            plan = build_int_batch_plan(workspace)
            execute_int_batch(plan, workspace)

            skipped = execute_int_batch(plan, workspace)
            disassembly = workspace / "output/scripts/master/SCRIPTS/TEST.disasm.txt"
            disassembly.write_text("tampered", encoding="utf-8")
            failed = execute_int_batch(plan, workspace)
            recovered = execute_int_batch(plan, workspace, overwrite=True)

            self.assertEqual((skipped.skipped_verified, skipped.failed), (1, 0))
            self.assertEqual((failed.converted, failed.failed), (0, 1))
            self.assertEqual((recovered.converted, recovered.failed), (1, 0))
            self.assertNotEqual(disassembly.read_text(encoding="utf-8"), "tampered")

    def test_loose_data_excludes_savegame_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_dir = root / "Fallout"
            source = game_dir / "DATA/SCRIPTS/TEST.INT"
            source.parent.mkdir(parents=True)
            build_int(source)
            save = game_dir / "DATA/SAVEGAME/SLOT01/PRIVATE.INT"
            save.parent.mkdir(parents=True)
            build_int(save)

            plan = build_int_batch_plan(root / "workspace", sources=["data"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())


if __name__ == "__main__":
    unittest.main()
