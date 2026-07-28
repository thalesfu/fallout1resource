from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_frm import _frm_bytes, _palette_bytes

from fallout1resource.frm_batch import build_frm_batch_plan, execute_frm_batch


class FrmBatchTests(unittest.TestCase):
    def _palette(self, workspace: Path) -> Path:
        path = workspace / "raw/master/COLOR.PAL"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_palette_bytes())
        return path

    def _image(self, workspace: Path, name: str = "TEST.FRM") -> Path:
        path = workspace / "raw/master/ART/CRITTERS" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_frm_bytes())
        return path

    def test_plan_preserves_family_extension_and_is_write_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            self._palette(workspace)
            self._image(workspace, "TEST.FRM")
            self._image(workspace, "TEST.FR0")

            plan, palette = build_frm_batch_plan(workspace, sources=["master"])

            self.assertEqual(len(plan), 2)
            self.assertEqual(palette, (workspace / "raw/master/COLOR.PAL").resolve())
            self.assertEqual(len({item.output for item in plan}), 2)
            self.assertTrue(any(item.output.as_posix().endswith("TEST.fr0.json") for item in plan))
            self.assertFalse((workspace / "output").exists())

    def test_continues_after_failure_and_rerun_verifies_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            palette = self._palette(workspace)
            self._image(workspace)
            bad = workspace / "raw/master/ART/CRITTERS/BAD.FRM"
            bad.write_bytes(b"invalid")
            plan, _ = build_frm_batch_plan(workspace)

            first = execute_frm_batch(plan, palette, workspace)
            second = execute_frm_batch(plan, palette, workspace)

            self.assertEqual((first.converted, first.failed), (1, 1))
            self.assertEqual((second.skipped_verified, second.failed), (1, 1))

    def test_tampered_frame_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            palette = self._palette(workspace)
            self._image(workspace)
            plan, _ = build_frm_batch_plan(workspace)
            execute_frm_batch(plan, palette, workspace)
            frame = next((workspace / "output").rglob("frame-000.png"))
            frame.write_bytes(b"tampered")

            failed = execute_frm_batch(plan, palette, workspace)
            recovered = execute_frm_batch(plan, palette, workspace, overwrite=True)

            self.assertEqual((failed.converted, failed.failed), (0, 1))
            self.assertEqual((recovered.converted, recovered.failed), (1, 0))
            self.assertNotEqual(frame.read_bytes(), b"tampered")

    def test_loose_data_is_read_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            self._palette(workspace)
            game_dir = root / "Fallout"
            source = game_dir / "DATA/ART/INVEN/ITEM.FRM"
            source.parent.mkdir(parents=True)
            source.write_bytes(_frm_bytes())

            plan, _ = build_frm_batch_plan(workspace, sources=["data"], game_dir=game_dir)

            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0].source_path, source.resolve())


if __name__ == "__main__":
    unittest.main()
